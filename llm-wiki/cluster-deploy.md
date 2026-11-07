# Выкатка на кластер Socrat

Срез на **1 ноября 2026**. Это контракт релиза для сервисов, которые уже живут в Argo CD. Пилот — `blog`. На ту дату остальные workload ещё были на Fleet/Helm и GHCR; этот снимок сам по себе их не переводил.

**Снятие GitOps Fleet.** В репозитории больше нет Fleet `GitRepo` и `deploy/**/fleet.yaml`. Выкладка приложений — только Argo CD (`deploy/argocd/apps`). Это не удаление контроллеров Fleet из кластера: Rancher v2.15.2 снова включает Feature Fleet, пока включён multi-cluster-management. Бюджеты `cattle-fleet-*`, размещение `gitjob`/`helmops` и описания исключённых Fleet-дашбордов поэтому оставлены. Не возвращать GitRepo и не считать multi-cluster-management выключенным. Образы на GHCR — отдельная миграция registry, не повод оставлять Fleet-бандл.

Журнал первого пилота и registry: `docs/harbor.md`, `llm-wiki/harbor.md`.

## Что является правдой

Живая версия образа лежит в Git, в `alchemmist/homelab`, ветка `main`. Argo CD читает этот репозиторий и сам приводит кластер к коммиту. CI не вызывает API Argo CD и не делает Sync.

Ручная правка в UI Argo CD, `kubectl set image`, `helm upgrade` и Helm-parameters на Application не сохраняются. Следующий sync возвращает объект к манифесту из Git. У блога `selfHeal: true`.

Ожидаемая цепочка:

1. Репозиторий сервиса собирает и проверяет артефакт.
2. CI пушит immutable-образ в Harbor. Тег образа — полный git SHA коммита сервиса, не `latest`.
3. Тот же job одним шагом вызывает `alchemmist/deploy-to-socrat@v1` и передаёт digest, который вернул `docker/build-push-action`.
4. Action коммитит в `homelab` `main` только поля образа этого приложения.
5. Argo CD на следующем опросе репозитория видит коммит и синкает Application. Обычный интервал опроса — около трёх минут. Webhook на GitHub не настроен.

Образ:

```text
harbor.socrat.alchemmist.xyz/homelab/<app>:<git-sha>
```

В под уходит `repository@sha256:...`, если `image.digest` непустой. Тег в values остаётся как запись, какой коммит сервиса этот digest собрал. Шаблон блога: `charts/blog/templates/deployment.yaml`.

## Чего не делать

- Не патчить Application из CI и не писать digest в Helm-parameters. Пустой список в манифесте нужен явно: `parameters: []`. Если поля нет, `kubectl apply` старый список не стирает, и параметр перекроет файл в Git.
- Не вызывать из CI `argocd app sync`, `helm upgrade`, `helm uninstall`, `kubectl set image`.
- Не класть второй GitHub Actions job ради коммита версии. Точка входа одна: шаг `Deploy to Socrat` внутри job, который уже собрал и запушил образ.
- Не заводить свои AppProject и ApplicationSet. Все Application стоят в встроенном проекте `default`. Поле `spec.project` у Argo обязательное; `default` создаётся вместе с Argo CD, отдельным манифестом мы его не описываем.
- Не коммитить версию образа руками в обход action, кроме аварийного отката.

## Как пользоваться action

Репозиторий: `alchemmist/deploy-to-socrat`, тег `v1`. Это composite action, не отдельный workflow.

```yaml
- name: Deploy to Socrat
  uses: alchemmist/deploy-to-socrat@v1
  with:
    token: ${{ secrets.HOMELAB_DEPLOY_KEY }}
    image_version: ${{ steps.image.outputs.digest }}
```

Имя Application берётся из имени репозитория. Если они разные, передать `app`. Имя — строчные буквы, цифры и дефис, не длиннее 41 символа.

`image_version`:

- `sha256:` и 64 hex. Action пишет это в `image.digest` и ставит `image.tag` равным полному SHA вызывающего коммита. Так надо делать релиз.
- Обычный тег образа. Action пишет его в `image.tag` и очищает `image.digest`. Это запасной вариант, не основной путь.

Файлы, которые он меняет:

- обязательный `deploy/<app>/values.yaml`;
- `charts/<app>/values.yaml`, если файл уже есть.

В обоих в корневом ключе `image` должны уже быть строки `tag` и `digest`. Action не создаёт файл и не добавляет ключи. В коммит попадают только эти файлы. Автор коммита — `socrat-releaser`. Сообщение: `chore(<app>): deploy <image_version>` и строка `Source: <repo>@<sha>`.

Если к моменту коммита `GITHUB_SHA` уже не верхушка ветки, action выходит успешно и ничего не пушит. Старая сборка не откатывает более новый коммит. Если значения уже такие, коммита тоже нет.

Перед коммитом action делает `git pull --rebase origin main`, чтобы два релиза подряд не затирали чужой коммит версии.

Пример живого вызова: `.github/workflows/deploy.yaml` в `alchemmist/blog`, job `publish-and-deploy`.

## Ключ и права

`token` — приватный ключ write deploy key `socrat-releaser` на репозиторий `alchemmist/homelab`. В GitHub он лежит секретом `HOMELAB_DEPLOY_KEY` у каждого репозитория, который вызывает action. Сейчас это `blog` и сам `deploy-to-socrat`.

Ключ пушит в `homelab` что угодно. Ограничение «только поля образа» сидит в коде action, а не в правах ключа. Кто может менять workflow репозитория с этим секретом, может забрать ключ и запушить в `homelab` любой файл.

`main` у `homelab` ruleset-ом не закрыт. Deploy key нельзя добавить в bypass ruleset, поэтому закрытая ветка отрежет и робота. Пока в репозиторий пушит только владелец, это принятый зазор. Когда появятся другие люди с правом менять workflow, ключ надо заменить на GitHub App, который можно внести в bypass, а приватный ключ держать только в репозитории action.

Токен Argo CD релизу не нужен. Старый секрет `ARGOCD_AUTH_TOKEN` в репозитории блога к этому пути не относится.

Harbor: push-учётка в секретах CI (`HARBOR_USERNAME`, `HARBOR_PASSWORD`). Pull в namespace — Secret `kubernetes.io/dockerconfigjson` и `imagePullSecrets`. У блога это `blog-harbor-pull`.


## Иконка на плитке и внешние Helm-репозитории

Срез **3 ноября 2026**. Иконка на плитке Application — тип первого источника, а не то, что лежит внутри чарта. У `cats`, `format-quorum`, `blog` и `authentik` первый источник — git `alchemmist/homelab` (`charts/<app>`), поэтому Git. У `cert-manager` и `harbor` первый источник — внешний Helm-чарт (`chart:`), git с values подключён вторым (`ref: values`), поэтому Helm.

`authentik` больше не качает `charts.goauthentik.io`. Чарт `2026.8.5` лежит в `charts/authentik`, Application читает `deploy/platform/authentik/values.yaml`. Условные субчарты PostgreSQL и `authentik-remote-cluster` в вендоренную копию не входят: в этом кластере оба выключены, а `helm dependency build` до них обрывался по таймауту. Живой Postgres — отдельный StatefulSet, не субчарт.

`ComparisonError` / `failed to generate manifest for source 1 of 2` / `context deadline exceeded` на оставшихся внешних Helm-приложениях — это не падение подов. Repo-server не успевает за 90 секунд выполнить `helm pull`, в частности с `helm.goharbor.io`. Кэш манифеста при промахе качается заново. Пока pull не проходит, sync остаётся `Unknown`, уже запущенные поды не останавливаются.

## Аннотации релизов на графиках Grafana

Контроллер `argo-cd-argocd-notifications-controller` подписан на все Application, кроме `root`. Условие `on-deployed` в `deploy/platform/argo-cd/values.yaml`: sync `Succeeded`, здоровье `Healthy`, операция закончилась меньше 10 минут назад. `oncePer: app.status.sync.revision` не даёт повторную отметку на тот же коммит. Приложение без `operationState` условие пропускает.

Срабатывание шлёт `POST /api/annotations` на Service `kube-prometheus-stack-grafana` в `cattle-monitoring-system`. Тело: `"<app> deployed <revision>"`, теги `deploy` и имя приложения. Токен сервисного аккаунта Grafana `argocd-deploys` (роль Editor) лежит только в Secret `argocd/argocd-notifications-secret`, ключ `grafana-api-key`. Helm этот Secret не создаёт.

На Overview, Services, Nodes, Metrics и LLM переменная `deploy` — выпадающий список имён Application. Прочерк `-` не совпадает ни с одним тегом, поэтому линии скрыты. Выбор сервиса оставляет аннотации, у которых есть оба тега: `deploy` и имя этого сервиса. Переключателя «показать все» на дашборде нет. На Traffic light слоя нет. Отдельной отправки в каждый дашборд нет.

## Локальный API-аккаунт для агента

В `deploy/platform/argo-cd/values.yaml` заведён локальный пользователь `accounts.mcp: apiKey` (в UI паролем не входит). RBAC по умолчанию `role:readonly`, плюс одна строка `p, mcp, applications, sync, */*, allow`. Создавать и удалять Application этот аккаунт не может. Токен выпускается через API Argo CD и хранится только на машине агента (`~/.pi/agent/argocd-mcp-token`). Клиент — stdio-сервер `argocd-mcp` в пользовательском `mcp.json`, URL `https://argocd.socrat.alchemmist.xyz`. Браузерный вход через Authentik от этого не меняется.

Пока Application `argo-cd` не может скачать свой чарт с `argoproj.github.io`, self-heal не подтянет этот values. До успешного sync аккаунт живёт ещё и прямой правкой `argocd-cm` / `argocd-rbac-cm`. Следующий успешный sync с `main` без этого коммита аккаунт сотрёт.

## Как устроен Argo CD

Argo CD стоит на socrat-0. UI: `https://argocd.socrat.alchemmist.xyz`. TLS cert-manager HTTP-01, ingress Traefik, в том числе через VPS edge. Браузер входит через Authentik OIDC. Значения: `deploy/argocd/values.yaml`, playbook `ansible/playbooks/argocd.yml`.

Базовая схема и NetBird:

| Имя | Откуда | Что делает |
| --- | --- | --- |
| `root` | `deploy/argocd/root.yaml`, применён один раз | Смотрит каталог `deploy/argocd/apps` и держит там Application. `prune: true`, `selfHeal: true`. Самого себя в каталоге нет. |
| `netbird` | `deploy/argocd/apps/netbird.yaml` | Чарт `charts/netbird`, values `deploy/netbird/values.yaml`. Весь NetBird Kubernetes stack, включая management/dashboard, edge, relays, STUN и machine agents; `prune: false`, `selfHeal: true`. PVC/собственные namespaces защищены `Prune=false,Delete=false`; секреты остаются private bootstrap dependencies. |
| `blog` | `deploy/argocd/apps/blog.yaml` | Чарт `charts/blog`, values `deploy/blog/values.yaml`, namespace `blog`. `prune: false`, `selfHeal: true`, `CreateNamespace=true`. |

`root` — обычный вариант схемы app of apps без ApplicationSet. Удалил Application `blog` — `root` создаст его снова из Git. Удалил файл из `deploy/argocd/apps` — `root` удалит и Application. У блога стоит finalizer `resources-finalizer.argocd.argoproj.io`, поэтому удаление Application сносит и его ресурсы. У `root` finalizer нет: удаление самого `root` дочерние Application не стирает. Вернуть `root` можно только повторным `kubectl apply -f deploy/argocd/root.yaml`.

Поды восстанавливает ReplicaSet Deployment, не `root`. `root` восстанавливает Application. Старые ReplicaSet с нулём подов — история Deployment (`revisionHistoryLimit` по умолчанию 10). Живые реплики только у текущего.

Harbor один, на socrat-0. Падение socrat-0 ломает push и незакешированный pull. Уже запущенные контейнеры при этом не останавливаются. На холодной ноде слой блога шёл около 13 минут. Пока образ качается, Application может быть `Synced` и ещё не `Healthy`.

## Строгий порядок для нового сервиса

Делать по одному сервису. Не копировать шаг в CI, пока в Git нет Application и values.

1. Чарт в `charts/<app>`. В шаблоне Deployment один образ: если `image.digest` задан, использовать `repository@digest`, иначе `repository:tag`.
2. `deploy/<app>/values.yaml` с корневым `image.repository`, `image.tag`, `image.digest`. До первого релиза digest пустой, tag — тот образ, который уже можно катить. Те же ключи в `charts/<app>/values.yaml`, если файл есть. Application должен читать `deploy/<app>/values.yaml` через `helm.valueFiles`.
3. В namespace — pull Secret от проектного робота Harbor и ссылка на него в `imagePullSecrets`.
4. Манифест Application в `deploy/argocd/apps/<app>.yaml`: `project: default`, `parameters: []`, `targetRevision: main`, auto-sync, `prune: false`, `selfHeal: true`. Закоммитить. `root` создаст Application сам. Не создавать его руками в UI.
5. Дождаться `Synced`. Первый рендер должен совпасть с тем, что уже работает, либо это сознательный первый выкат.
6. В CI сервиса положить секрет `HOMELAB_DEPLOY_KEY` с тем же приватным ключом и добавить шаг из раздела выше. Запушить образ в `harbor.socrat.alchemmist.xyz/homelab/<app>`.
7. Проверить коммит `socrat-releaser` в `homelab`, затем `Synced/Healthy` и живой HTTP. На холодной ноде здоровье может опоздать на время pull.

Action умеет один образ на приложение и только ключи `image.tag` / `image.digest` в этих двух путях. Несколько образов в одном чарте, другое имя поля или другой каталог values он не обновит.

## Откат

Откат — новый коммит в `deploy/<app>/values.yaml` и в парный chart values: предыдущие `repository`, `tag` и `digest`. Auto-sync подхватит его. Правка digest в UI пропадёт на следующем sync.

Если нужно вернуть конкретный уже запушенный digest, его можно взять из предыдущего коммита `chore(<app>): deploy ...`. Образ в Harbor не удалять, пока на него ссылается Deployment: следующий рестарт пода не сможет его скачать.

## Как проверять, что релиз дошёл

1. Job сервиса зелёный, в нём есть шаг `Deploy to Socrat`, отдельного job нет.
2. В `homelab` есть коммит `socrat-releaser` с этим digest.
3. `kubectl -n argocd get application <app>` показывает `Synced` на этот коммит и потом `Healthy`.
4. Образ Deployment равен `harbor.socrat.alchemmist.xyz/homelab/<app>@sha256:...`.
5. `spec.source.helm.parameters` пустой.
6. Живой HTTP сервиса отвечает.

Если Git уже новый, а кластер старый, это ожидание опроса, а не повод вызывать Sync из CI. Принудительный refresh из UI допустим, когда нужно посмотреть результат сразу.

### NetBird: переход существующего сервиса под Argo CD

Пользовательский onboarding, топология, результаты отказных тестов и незакрытые
границы: [актуальный NetBird runbook](netbird.md).

NetBird больше не исключение: Application создаёт `root` из каталога apps, не
ручной apply/UI. Подробнее: [netbird-argocd.md](../docs/netbird-argocd.md). Сохраняются
существующие версии upstream-образов по digest; миграция не обновляет образы и
не переиздаёт идентичности/секреты. Значения секретов и содержимое PVC не в Git.
Для нового узла: inventory → `scripts/netbird-gitops-nodes.py` → commit inventory
и values → Argo CD → обычный Ansible machine enrollment/API grants. Ansible не
создаёт Kubernetes Deployment/PVC и не конкурирует с selfHeal.

### Release transport recovery — 2026-11-04

`deploy-to-socrat@v1` (56037a9) uses an isolated temporary 0600 deploy key, pinned official GitHub host keys, SSH-over-443, bounded retries and rebases the same commit when concurrent `main` updates cause either non-fast-forward or remote ref-lock rejection. It remains one composite step; no Argo API calls. Static shell tests plus eight image/component unit tests pass.

The GitHub Git Operations incident has cleared. Local SSH authentication and `git ls-remote` work again. End-to-end LMS run **41811725828** succeeded on the final retry: robot commit **76e9902** recorded `sha256:9890519389652cdd8c8436a76f81be6bc81131174a728144ab268c4150a80167`; live Deployment uses that GHCR digest and its rollout completed. Earlier failed attempts are not successful releases. LMS remains on GHCR intentionally during HA ownership work.


## Публичные входы принадлежат приложениям — 2026-11-07

**Отдельная Argo Application `public-web-entry` удалена из Git и кластера.**
Удалён и `charts/public-web-entry`. Не восстанавливать этот сборный слой при
настройке нового сервиса: Ingress и специфичный защитный proxy/config должны
принадлежать той же Application, что и сервис.

| Argo Application | Публичный вход / policy | Источник |
| --- | --- | --- |
| `kube-prometheus-stack` | Grafana, policy proxy и TV JS | `deploy/platform/kube-prometheus-stack/public-entry` |
| `rancher` | Rancher, policy proxy | `deploy/platform/rancher/public-entry` |
| `litellm` | `litellm.socrat…` alias | `deploy/platform/litellm/public-entry` |
| `searxng` | Search | `charts/searxng`, `publicEntry` |
| `open-webui` | `llm.socrat…` alias | `charts/open-webui`, `publicEntry` |
| `grafana-mcp` | bearer-only `/mcp` | `charts/grafana-mcp`, `publicEntry` |
| `syncthing` | оба GUI-входа, policy proxy | `charts/syncthing`, `publicEntry` |
| `uptime-kuma` | admin-вход, policy proxy | `charts/uptime-kuma`, `publicEntry` |

Для сторонних Helm-чартов `deploy/platform/<app>/public-entry` добавлен как
ещё один `spec.sources` **существующей** Application; это не новые Applications.
Основные upstream chart/version/values сохранены. У локальных чартов public
шаблоны включены непосредственно в chart. Traefik, cert-manager и Authentik —
общие платформенные компоненты; admission allowlist/группы по-прежнему управляются
identity tooling (`deploy/public-web/services.json`), а не дублируются в чартах.

### Передача владения и проверенные границы

1. Старую Application сначала отключили от auto-sync и сняли deletion finalizer
   **через Git**, чтобы root не запустил каскадное удаление.
2. Все 22 ресурса передали восьми владельцам; offline-render до/после полностью
   совпал. Live tracking annotation у каждого ресурса указывает на нового владельца.
3. UID всех 22 ресурсов и 18 объектов Certificate/TLS Secret сохранены. У 186
   существовавших проверенных подов UID/readiness/restart counts не изменились.
4. Затем удалили старую Application и общий chart. Детям оставили `prune: false`,
   `selfHeal: true`; root после удаления вернулся в `Synced / Healthy`.

Префикс `public-web-` в **именах ресурсов** намеренно сохранён: он не означает
наличие старой Application. Namespace `identity` у Authentik-gated Ingress также
не означает владение Authentik/общим public app. Смотреть на Argo tracking и
источник соответствующей Application; не переименовывать/пересоздавать TLS или
Ingress только ради косметики.

LiteLLM full sync попытался запустить существующий DB migration hook. Job остался
Pending из-за 512Mi request на socrat-0, до запуска контейнера. На время handoff
его auto-sync приостановили в Git, операцию остановили, pending Job убрал Argo;
отдельным resource-only sync передали только alias Ingress без hooks. Обычный
`prune: false / selfHeal: true` auto-sync восстановлен, активных операций/Jobs
на закрытии нет. БД/идентичности не мигрировали, scheduling hook не меняли;
его вместимость при будущем реальном релизе — отдельная проверка.

Приёмка миграции: **134/134** public TLS/anonymous/forged-header/invalid-token
checks до и после, **88 профильных тестов**. Пять старых ошибок
`test_syncthing_scheduling.py` воспроизведены на исходном `c612d71` (ожидание
DaemonSet при текущем Deployment); полный repository suite не объявлялся зелёным.
Новый browser MFA/enrollment этой передачей владения не проверялся.

Коммиты: disarm `41e10a2`, перенос `7ae691a`, временная пауза LiteLLM `4e2c72e`,
окончательное удаление/возврат auto-sync **`e7fe891`**. Подробности:
[операционная миграция](../docs/public-web-migration.md),
[доступ и авторизация](network-access.md). Старый aggregate chart не возвращать
при откате одного приложения; менять только источник его действующего владельца.
