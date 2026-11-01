# Выкатка на кластер Socrat

Срез на **1 ноября 2026**. Контракт для новых релизов. Пилот — `blog`. Остальные workload ещё на Fleet/Helm и GHCR.

Журнал того, что уже сделано на кластере: `docs/harbor.md`, раздел Blog CI/CD pilot. Registry: `llm-wiki/harbor.md`.

## Единый способ

Живая версия образа должна лежать в Git репозитория homelab. Argo CD читает этот коммит и катит Deployment. CI сам в homelab не коммитит и не пишет digest в объект Application.

1. GitHub Actions собирает и проверяет артефакт.
2. CI пушит immutable-образ в Harbor. Тег — полный git SHA, не `latest`. Выкатка идёт по `sha256` digest.
3. CI вызывает `alchemmist/deploy-to-socrat/.github/workflows/deploy.yml` и передаёт digest.
4. Этот workflow кладёт коммит в `homelab`: обновляет `image.tag` и `image.digest` в `deploy/<app>/values.yaml` и пушит в `main`. Ключ записи лежит только в секретах `deploy-to-socrat`.
5. Argo CD видит новый коммит и синкает Application. Отдельный Sync из CI не вызывается.

Образ:

```text
harbor.socrat.alchemmist.xyz/homelab/<app>:<git-sha>
```

Чарт берёт digest, если он задан, иначе тег: `charts/blog/templates/deployment.yaml`.

Чего не делать:

- не патчить Application из CI, чтобы версия жила только в объекте Argo;
- не вызывать `helm upgrade` / `helm uninstall` для приложения, которое уже отдано Argo;
- не менять образ через `kubectl set image`.

## Ручка

Ручка — reusable workflow `alchemmist/deploy-to-socrat/.github/workflows/deploy.yml`. Она принимает digest уже запушенного образа и коммитит версию в homelab. CI после пуша в Harbor вызывает её один раз.

Она:

- принимает имя приложения и digest или тег;
- меняет только `image.tag` и `image.digest` в `deploy/<app>/values.yaml` и, если файл есть, в `charts/<app>/values.yaml`;
- коммитит и пушит в `main` deploy key-ом из секрета `HOMELAB_DEPLOY_KEY`;
- не вызывает Sync и не отдаёт ключ вызывающему репозиторию.

Push-робот Harbor остаётся в secret store CI. Pull в namespace — Secret `kubernetes.io/dockerconfigjson` и `imagePullSecrets`. Для блога это `blog-harbor-pull`.

## Как это сходится на кластере

Argo CD на socrat-0. UI: `https://argocd.socrat.alchemmist.xyz`, TLS cert-manager HTTP-01, ingress Traefik, в том числе через VPS edge. Браузер входит через Authentik OIDC. Значения: `deploy/argocd/values.yaml`, playbook `ansible/playbooks/argocd.yml`.

У пилота `blog` auto-sync включён, `prune=false`, `selfHeal=true`. Source — этот репозиторий, destination — namespace `blog`. В AppProject разрешены `Service`, `Deployment`, `ReplicaSet`, `Pod`, `Ingress`. `ReplicaSet` и `Pod` нужны, чтобы дочерние объекты Deployment были в resource tree. Cluster-scoped ресурсы запрещены.

Application `root` смотрит `deploy/argocd/apps` и восстанавливает оттуда AppProject и Application блога. Сам root лежит в `deploy/argocd/root.yaml` и применяется один раз: если удалить его, дочерние приложения остаются. Чарт и values — в Git: `deploy/blog/values.yaml`.

После коммита версии Argo подтягивает Helm и катит Deployment. Ноды тянут слои из Harbor сами. На первом релизе слой ~235 МБ на socrat-3 шёл около 13 минут. Пока образ качается, смотреть здоровье Application.

Harbor один на socrat-0. Падение socrat-0 ломает push и незакешированный pull. Уже запущенные контейнеры при этом не останавливаются.

## Что сейчас сделано у блога

Первый CI-релиз записал digest в Helm-parameters Application и не коммитил homelab. Это больше не контракт. Боевая версия теперь в `deploy/blog/values.yaml`. Параметр на Application не нужен: его снимает sync из манифеста в `deploy/argocd/apps/blog.yaml`.

Токен роли `ci` больше не входит в желаемый AppProject. Релиз пишет в Git, а не в API Argo.

Проверка первого релиза: обе реплики Ready на socrat-1 и socrat-3, Argo `Synced/Healthy`, оба публичных хоста блога ответили HTTP 200. Старый Helm release оставлен для аудита. Fleet блог больше не реконсилирует.

## Откат

Откат — коммит в values: предыдущий repository, tag и digest. Auto-sync подхватит его из Git. Правка Helm-parameters в UI не сохраняется: следующий sync возвращает манифест из Git.

## Следующее приложение

Тот же контракт, свой Application. Токен блога на него не расширять.

1. Чарт и values в homelab, pull Secret в namespace.
2. Манифесты AppProject и Application в `deploy/argocd/apps`. Root подхватит их сам. Auto-sync точечно, `prune=false`, `selfHeal=true`.
3. CI пушит образ и вызывает `deploy-to-socrat`. Workflow коммитит версию в values этого приложения.
4. Argo синкает коммит. Проверить `Synced/Healthy` и живой HTTP, с учётом долгого pull на холодную ноду.
