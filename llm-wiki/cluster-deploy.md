# Выкатка на кластер Socrat

Срез на **1 ноября 2026**. Это рабочий контракт для новых релизов. Пилот — приложение `blog`. Остальные workload ещё на Fleet/Helm и GHCR; их не переводить этим документом.

Подробный журнал пилота: `docs/harbor.md`, раздел Blog CI/CD pilot. Registry: `llm-wiki/harbor.md`.

## Единый способ

Новый релиз приложения делается только так:

1. GitHub Actions собирает и проверяет артефакт.
2. CI пушит immutable-образ в Harbor. Тег — полный git SHA коммита, не `latest`.
3. CI один раз вызывает Argo CD API и записывает в Application пушеный `sha256` digest.
4. Argo CD сам синкает этот Application. Отдельный Sync из CI не вызывается.
5. Чарт и базовые values остаются в `homelab` на `main`. Digest в Git не коммитится: живой образ лежит в объекте Application.

Чего не делать для приложения, которое уже на этом пути:

- не коммитить bump тега или digest в values ради релиза;
- не вызывать `helm upgrade` и `helm uninstall` — старый Helm release блога оставлен для аудита, Fleet/Helm его больше не реконсилируют;
- не дергать Deployment через `kubectl set image` и не ждать, что Fleet image automation сама подхватит тег. Учётные данные Fleet для Harbor ещё не настроены.

## Что вызывает CI

Своей ручки на homelab-кластере нет. CI ходит в Argo CD напрямую.

| | |
| --- | --- |
| URL | `https://argocd.socrat.alchemmist.xyz` |
| Метод | `PATCH` |
| Путь | `/api/v1/applications/blog` |
| Авторизация | `Authorization: Bearer <project token>` |
| Эффект | одна замена списка Helm-parameters Application на пушеный Harbor digest |

Токен — секрет GitHub Actions репозитория приложения. В Git его нет. Срок — один год; ротировать до истечения.

Роль `ci` в AppProject `blog` имеет только `applications, update` на `blog/blog`. RBAC Argo ограничивает Application целиком, а не отдельным полем: токен технически может менять и другие поля этого одного Application. «Только digest» — договор воркфлоу. Защита проекта: source только этот репозиторий, destination только namespace `blog`, cluster-scoped ресурсы запрещены. В namespace разрешены `Service`, `Deployment`, `ReplicaSet`, `Pod`, `Ingress`. `ReplicaSet` и `Pod` нужны, чтобы дочерние объекты Deployment были в resource tree.

Образ:

```text
harbor.socrat.alchemmist.xyz/homelab/blog:<git-sha>
```

Выкатка идёт по digest, не по мутабельному тегу. Push-робот Harbor живёт в secret store CI. Pull в namespace даёт Secret `blog-harbor-pull` (`kubernetes.io/dockerconfigjson`), на него ссылается `imagePullSecrets`. Анонимного registry и insecure TLS нет.

Следующий релиз CI заменяет весь список Helm-parameters на новый Harbor digest. Поэтому ручной rollback и следующий CI-релиз нельзя смешивать в одном списке параметров: CI перезапишет список целиком.

## Как это сходится на кластере

Argo CD стоит на socrat-0. UI: `https://argocd.socrat.alchemmist.xyz`, TLS через cert-manager HTTP-01, ingress Traefik, в том числе через VPS edge. Браузер входит через Authentik OIDC (`homelab-owner` и `homelab-platform-operator` — admin). Встроенный admin — break-glass, пока OIDC не выключен. Значения: `deploy/argocd/values.yaml`, playbook `ansible/playbooks/argocd.yml`.

У пилота `blog`:

- auto-sync включён только у этого Application;
- `prune=false`, `selfHeal=false`;
- source — этот репозиторий, destination — namespace `blog`;
- чарт и база — `deploy/blog/values.yaml` и chart блога в homelab. Поле `image.digest` в Git пустое: боевой digest приходит параметром Application;
- две реплики, ingress `alchemmist.xyz` и `www.alchemmist.xyz`.

AppProject и Application созданы через Argo API и пока не лежат манифестами в Git. Пока это так, источник правды для самого Application — живой объект, а не файл в репозитории.

После PATCH Argo сам подтягивает Helm-рендер с новым digest и катит Deployment. Ноды тянут слои из Harbor сами. На первом релизе слой контента ~235 МБ на socrat-3 шёл около 13 минут; нода ненадолго не писала status и потом вернулась. Пока образ качается, смотреть здоровье Application, а не считать тишину успехом.

Первый CI-релиз прошёл: обе реплики Ready на socrat-1 и socrat-3, Argo `Synced/Healthy`, оба публичных хоста блога ответили HTTP 200.

Harbor один на socrat-0. Падение socrat-0 ломает push и незакешированный pull, уже запущенные контейнеры при этом не останавливаются. Trivy, GC и retention deletion выключены: удаление тега, который ещё нужен Deployment, сломает следующий рестарт. Off-node backup registry ещё не настроен.

## Откат

Аварийный rollback блога: в Helm-parameters Application вернуть предыдущий GHCR repository/tag и очистить `image.digest`. Auto-sync подхватит это без отдельного Sync.

Предыдущий живой образ до Harbor-пилота:

```text
ghcr.io/alchemmist/blog:7da9b66790ef5c669561ad4791977eb42ae14c08
```

Следующий успешный CI-релиз снова заменит список параметров на Harbor digest.

## Как подключать следующее приложение

Тот же контракт, отдельный Application и отдельный токен. Не расширять токен блога на чужие Application.

1. Чарт и values в homelab: `image.repository` вида `harbor.socrat.alchemmist.xyz/homelab/<app>`, пустой `image.digest`, `imagePullSecrets`.
2. В namespace приложения — pull Secret от cluster-pull робота Harbor. Робот проектный, только pull в проекте `homelab`.
3. AppProject: свой source, свой namespace, узкий allowlist, роль `ci` только на этот Application.
4. Auto-sync включать точечно у этого Application, с теми же `prune=false` и `selfHeal=false`, пока отдельно не решено иначе.
5. CI: push `<git-sha>`, один PATCH `/api/v1/applications/<name>` с digest, без Sync и без коммита версии в homelab.
6. Проверить `Synced/Healthy` и живой HTTP, учитывая долгий pull на холодную ноду.

Пока Application не лежит в Git, создание идёт через Argo API так же, как у блога. Это временный зазор: права и граница проекта должны быть воспроизводимы, digest по-прежнему приходит только из CI.
