---
weight: 50
title: Как задеплоить сервис на кластере
---

Штатная цепочка: **репозиторий сервиса → GitHub Actions → Harbor → коммит версии в homelab → Argo CD → Kubernetes**. Версия и конфигурация живут в Git; CI не делает `helm upgrade`, `kubectl set image` или `argocd app sync`.

## 0. Получить доступ и согласовать границы

Нужны личный Authentik/MFA, права на репозиторий сервиса и review изменений [homelab](https://github.com/alchemmist/homelab), project membership в [Harbor](https://harbor.socrat.alchemmist.xyz) и scoped доступ в [Argo CD](https://argocd.socrat.alchemmist.xyz). Вход через OIDC не выдаёт автоматически push/delete, cluster-admin или право менять чужие приложения.

До первого релиза согласуйте имя `<app>`, namespace, domain/Ingress, ресурсы, зависимости, данные/PVC и backup/rollback. Для новых публичных UI предпочтителен native OIDC с Authentik; если его нет, отдельно согласуйте auth-gateway, native login и исключения machine/public endpoints. Не публикуйте БД, debug/metrics или storage API по умолчанию.

SSH на ноды для обычного релиза не нужен. Подключение GitHub, registry и secrets выполняется отдельно от браузерного SSO.

## 1. Подготовить чарт и values в homelab

Создайте:

```text
charts/<app>/Chart.yaml
charts/<app>/values.yaml
charts/<app>/templates/...
deploy/<app>/values.yaml
deploy/argocd/apps/<app>.yaml
```

Рабочий образец — `charts/blog`, `deploy/blog/values.yaml` и `deploy/argocd/apps/blog.yaml`. Адаптируйте имена/labels/порты/домены, не копируйте чужие Secret, storage paths и права. Минимум: Deployment, внутренний Service, requests/limits, readiness/liveness и при необходимости HTTPS Ingress с cert-manager. Для stateful сервиса отдельно оформите PVC, размещение и восстановление; не рассчитывайте, что локальный диск автоматически станет HA.

В обоих values предусмотрите корневой блок:

```yaml
image:
  repository: harbor.socrat.alchemmist.xyz/homelab/<app>
  tag: "<FULL_SOURCE_COMMIT_SHA>"
  digest: "sha256:<EXISTING_IMAGE_DIGEST>"
  pullPolicy: IfNotPresent
imagePullSecrets:
  - <app>-harbor-pull
```

Это шаблон: до merge подставьте **существующий** образ, не оставляйте placeholders в auto-sync Application. Deployment должен использовать `repository@digest`, если digest непустой, иначе `repository:tag`. Например:

```yaml
image: "{{ .Values.image.repository }}{{ if .Values.image.digest }}@{{ .Values.image.digest }}{{ else }}:{{ .Values.image.tag }}{{ end }}"
```

Secrets не коммитятся в открытом виде и не передаются в wiki/issue. Согласованный оператор создаёт namespace-scoped pull Secret типа `kubernetes.io/dockerconfigjson` от Harbor robot с pull-only правами, а также app Secrets. Chart ссылается на них, но не регенерирует действующие пароли при upgrade.

## 2. Добавить Application

Образец `deploy/argocd/apps/<app>.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <app>
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/alchemmist/homelab.git
    targetRevision: main
    path: charts/<app>
    helm:
      releaseName: <app>
      valueFiles:
        - ../../deploy/<app>/values.yaml
      parameters: []
  destination:
    server: https://kubernetes.default.svc
    namespace: <app>
  syncPolicy:
    automated:
      prune: false
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

Сначала `helm lint`, `helm template`, проверки репозитория и review, затем merge в `main`. `root` следит за `deploy/argocd/apps` и создаёт Application сам. Не создавайте дубликат вручную в UI и не добавляйте AppProject/ApplicationSet без отдельного изменения архитектуры. Для нового сервиса начинаем с `prune: false`; finalizer с каскадным удалением нельзя копировать без понимания последствий.

Проверьте Application и осознанный первый rollout до подключения автоматического releaser. Если сервис уже работает, первоначальный render должен сохранять его состояние, а не случайно пересоздавать данные.

## 3. Настроить CI репозитория сервиса

Оператор настраивает secrets `HARBOR_USERNAME`, `HARBOR_PASSWORD` от scoped push robot и `HOMELAB_DEPLOY_KEY` для release action. Последний сейчас **SSH write deploy key**, а не обычный GitHub API token; параметр action исторически называется `token`.

Write deploy key даёт широкую запись в homelab. Не выдавайте его каждому админу и не добавляйте в недоверенный workflow: возможность менять такой workflow равна возможности извлечь ключ. Расширение числа workflow maintainers требует отдельного решения о GitHub App/branch protection. Не копируйте ключ владельца.

Пример одного job, выполняемого только для доверенного push в `main` после тестов:

```yaml
name: Publish and deploy
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  publish-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # Здесь обязательные тесты приложения.
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: harbor.socrat.alchemmist.xyz
          username: ${{ secrets.HARBOR_USERNAME }}
          password: ${{ secrets.HARBOR_PASSWORD }}
      - name: Build and push
        id: image
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: harbor.socrat.alchemmist.xyz/homelab/<app>:${{ github.sha }}
      - name: Deploy to Socrat
        uses: alchemmist/deploy-to-socrat@v1
        with:
          token: ${{ secrets.HOMELAB_DEPLOY_KEY }}
          app: <app>
          image_version: ${{ steps.image.outputs.digest }}
```

Замените `<app>`. `app` можно опустить, если имя Application совпадает с именем репозитория. Dockerfile должен быть пригоден для архитектуры нод. Версии Actions согласуйте с политикой репозитория; пример не разрешает запускать release secrets на недоверенном PR.

Action меняет image tag/digest в существующих values, коммитит их в homelab и учитывает конкурирующие push/rebase. Основной контракт выше — корневой image block; дополнительные multi-component возможности action требуют отдельной настройки. Не добавляйте второй CI job с ручным коммитом образа и не вызывайте Argo API из CI.

## 4. Проверить релиз

1. CI прошёл тесты и push; digest существует в Harbor.
2. В `homelab/main` появился коммит releaser с ожидаемым digest и Source commit.
3. Argo CD увидел этот Git revision: сначала `Synced`, затем `Healthy`. Опрос Git может занять несколько минут, cold pull — дольше; GitHub webhook не следует предполагать настроенным.
4. Deployment использует точный `repository@sha256:...`, а Helm parameters не перекрывают Git values.
5. Проверены настоящий HTTPS, OIDC/native role, health и полезная функция. Для нового сервиса проверьте также неавторизованный отказ и необходимые API/WebSocket paths. При обновлении темы/runtime проверьте фактическую отдачу новых CSS/JS и сохранение OIDC scopes/MCP: готовый pod сам по себе не подтверждает обновление интерфейса.
6. Есть dashboards/алерты, владелец сервиса и краткий runbook. См. [Socrat Overview]({{< relref "observability/grafana.md" >}}).

При выданном namespace-scoped kubectl можно дополнительно посмотреть Deployment image и rollout status. Не запрашивайте cluster-admin ради этой проверки.

## 5. Откат и типовые ошибки

Откат — **новый Git-коммит** предыдущих repository/tag/digest в release values и парный chart values. Argo подхватит его. UI image overrides и `kubectl set image` self-heal вернёт назад. Не удаляйте образ, пока на него ссылается Deployment.

Откат контейнера не откатывает миграцию БД: предварительно проверьте совместимость и approved restore procedure. Не удаляйте namespace/PVC/Application как «rollback»; удаление Application с finalizer может удалить его ресурсы.

| Симптом | Где искать |
| --- | --- |
| Harbor push denied | Scope/срок push robot, адрес проекта и имя образа |
| `Permission denied (publickey)` у releaser | Release deploy key/transport; не обходить ручным helm upgrade |
| Git обновился, Argo ещё старый | Poll/refresh и состояние repo-server, не второй deploy из CI |
| `ComparisonError` | Render/загрузка chart/source; это не обязательно падение работающих pod |
| `ImagePullBackOff` | Digest, pull Secret в правильном namespace, registry/network |
| `Synced`, но не `Healthy` | Pull, probes, ресурсы, dependencies; изучить Events/logs |
| `403` после SSO | Отдельная native роль/RBAC, не отключать авторизацию |

Не синкайте/пруньте посторонние приложения ради своего релиза. Общая деградация — повод остановить rollout и перейти к incident procedure.
