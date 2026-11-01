# Выкатка на кластер Socrat

Срез на **1 ноября 2026**. Контракт для новых релизов. Пилот — `blog`. Остальные workload ещё на Fleet/Helm и GHCR.

Журнал того, что уже сделано на кластере: `docs/harbor.md`, раздел Blog CI/CD pilot. Registry: `llm-wiki/harbor.md`.

## Единый способ

Живая версия образа должна лежать в Git репозитория homelab. Argo CD читает этот коммит и катит Deployment. CI сам в homelab не коммитит и не пишет digest в объект Application.

1. GitHub Actions собирает и проверяет артефакт.
2. CI пушит immutable-образ в Harbor. Тег — полный git SHA, не `latest`. Выкатка идёт по `sha256` digest.
3. CI вызывает одну ручку homelab и передаёт имя приложения, тег и digest.
4. Ручка сама кладёт коммит в `homelab`: обновляет `image.repository`, `image.tag` и `image.digest` в values этого приложения и пушит в `main`.
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

Ручка — сервис homelab, не API Argo CD. Её задача: принять уже запушенный digest и сделать коммит версии в homelab. CI после пуша в Harbor вызывает её один раз.

Этой ручки в репозитории ещё нет. Пока её нет, коммит версии сам не появляется.

Она должна:

- принимать только заранее заведённое приложение, repository в проекте Harbor `homelab`, тег-ша и digest;
- менять только поля образа в values этого приложения;
- коммитить и пушить в `main`;
- не вызывать Sync и не хранить токен Argo у CI приложения.

Push-робот Harbor остаётся в secret store CI. Pull в namespace — Secret `kubernetes.io/dockerconfigjson` и `imagePullSecrets`. Для блога это `blog-harbor-pull`.

## Как это сходится на кластере

Argo CD на socrat-0. UI: `https://argocd.socrat.alchemmist.xyz`, TLS cert-manager HTTP-01, ingress Traefik, в том числе через VPS edge. Браузер входит через Authentik OIDC. Значения: `deploy/argocd/values.yaml`, playbook `ansible/playbooks/argocd.yml`.

У пилота `blog` auto-sync включён только у этого Application, `prune=false`, `selfHeal=false`. Source — этот репозиторий, destination — namespace `blog`. В AppProject разрешены `Service`, `Deployment`, `ReplicaSet`, `Pod`, `Ingress`. `ReplicaSet` и `Pod` нужны, чтобы дочерние объекты Deployment были в resource tree. Cluster-scoped ресурсы запрещены.

AppProject и Application созданы через Argo API и пока не лежат манифестами в Git. Чарт и базовые values — в Git: `deploy/blog/values.yaml`.

После коммита версии Argo подтягивает Helm и катит Deployment. Ноды тянут слои из Harbor сами. На первом релизе слой ~235 МБ на socrat-3 шёл около 13 минут. Пока образ качается, смотреть здоровье Application.

Harbor один на socrat-0. Падение socrat-0 ломает push и незакешированный pull. Уже запущенные контейнеры при этом не останавливаются.

## Что сейчас сделано у блога

Первый CI-релиз прошёл в обход этого контракта. CI сам сделал `PATCH /api/v1/applications/blog` и записал digest в Helm-parameters Application. Коммита в homelab не было. Поэтому `deploy/blog/values.yaml` в Git всё ещё с пустым `image.digest` и старым тегом, а боевая версия видна только в объекте Argo.

Этот PATCH не становится единым способом. Следующий релиз должен обновить values коммитом через ручку. Пока ручка не написана, повторный CI-релиз блога снова перезапишет список Helm-parameters и обойдёт Git.

Токен проекта у роли `ci` имеет `applications, update` только на `blog/blog` и лежит в секрете GitHub Actions. Он нужен был для этого обхода. RBAC Argo ограничивает Application целиком, не отдельным полем.

Проверка первого релиза: обе реплики Ready на socrat-1 и socrat-3, Argo `Synced/Healthy`, оба публичных хоста блога ответили HTTP 200. Старый Helm release оставлен для аудита. Fleet блог больше не реконсилирует.

## Откат

Откат — тоже коммит в values: предыдущий repository, tag и digest. Auto-sync подхватит его из Git.

Пока боевая версия блога сидит в Helm-parameters, аварийный откат без ручки делается там же: вернуть GHCR repository/tag и очистить `image.digest`.

```text
ghcr.io/alchemmist/blog:7da9b66790ef5c669561ad4791977eb42ae14c08
```

Следующий CI-релиз текущего пилота снова заменит весь список параметров на Harbor digest.

## Следующее приложение

Тот же контракт, свой Application. Токен блога на него не расширять.

1. Чарт и values в homelab, pull Secret в namespace.
2. AppProject: свой source, свой namespace, тот же allowlist. Auto-sync точечно, `prune=false`, `selfHeal=false`.
3. CI пушит образ и вызывает общую ручку. Ручка коммитит версию в values этого приложения.
4. Argo синкает коммит. Проверить `Synced/Healthy` и живой HTTP, с учётом долгого pull на холодную ноду.
