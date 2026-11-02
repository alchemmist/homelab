# Socrat bot

Контракт выкатки тот же, что в [cluster-deploy.md](cluster-deploy.md): образ в Harbor, версия в Git, Argo CD синкает сам. CI не вызывает `helm upgrade` и не пишет Helm parameters.

## Границы слоёв

Три слоя. Секреты через git не ходят.

1. **Репозиторий бота** собирает один образ `harbor.socrat.alchemmist.xyz/homelab/socrat-bot`. В нём три процесса: `python -m socrat_bot`, `python -m socrat_bot.updater`, `python -m socrat_bot.broker`. Токен Telegram, пароль Postgres и `INTERNAL_TOKEN` живут только в Secret кластера `socrat-bot-env`. Его заполняет оператор. Чарт пароль не придумывает и через `lookup` сохраняет уже записанные ключи, а не затирает их пустым рендером.

2. **Homelab** держит чарт, values и Application. `deploy-to-socrat` меняет только корневые `image.tag` и `image.digest` в `deploy/socrat-bot/values.yaml` и `charts/socrat-bot/values.yaml`. Образ Postgres — отдельный ключ `postgres.image` (`postgres:17`). Под корневой `image` он не вложен, action его не переписывает. До первого релиза `image.tag` равен `bootstrap`, `image.digest` — пустая строка: шаблон берёт `repository:tag`, а когда digest непустой — `repository@digest`.

3. **n8n** принимает webhook Alertmanager и зовёт внутренний `/v1/messages`. Токен бота в Grafana не вводится. В конфиге Alertmanager нет учёток, только URL. `X-Internal-Token` остаётся credential n8n.

## Адреса

- Публичный webhook Telegram: `https://bot.socrat.alchemmist.xyz/telegram/webhook`. Ingress пускает только префикс `/telegram`. Маршрута `/v1` снаружи нет.
- Внутренний API: `http://socrat-bot.socrat-bot.svc:8080`.
- Updater: `http://socrat-bot-xui-updater.socrat-bot.svc:8080`.
- Broker: `http://socrat-bot-sudo-broker.socrat-bot.svc:8080`.
- Alertmanager → n8n: `https://n8n.socrat.alchemmist.xyz/webhook/socrat-alerts`.

Все три процесса бота слушают порт 8080 и отвечают на `GET /healthz`. У каждого по одной реплике.

## Где лежит

| Что | Путь |
| --- | --- |
| Чарт | `charts/socrat-bot` |
| Values релиза | `deploy/socrat-bot/values.yaml` |
| Application | `deploy/argocd/apps/socrat-bot.yaml` |
| Приёмник Alertmanager | `deploy/platform/kube-prometheus-stack/values.yaml` |
| Workflow | `docs/n8n/socrat-bot/workflow.json` |
| Импорт | `docs/n8n/socrat-bot/setup.md` |
| Клиент sudo | `ansible/files/socrat-sudo`, `ansible/files/socrat_sudo`, playbook `ansible/playbooks/socrat-sudo.yml` |

Application: проект `default`, namespace `socrat-bot`, `parameters: []`, `prune: false`, `selfHeal: true`, `CreateNamespace=true`, finalizer `resources-finalizer.argocd.argoproj.io`. Каталог `deploy/argocd/apps` подхватывает `root`, отдельно создавать Application в UI не нужно.

Pull Secret `socrat-bot-harbor-pull` чарт не создаёт: в нём учётка Harbor, её кладёт оператор, как `blog-harbor-pull`.

## Postgres

StatefulSet `socrat-bot-postgres`, одна реплика, образ `postgres:17`, диск 5Gi. StorageClass `socrat-bot-retain`: provisioner `rancher.io/local-path`, `reclaimPolicy: Retain`, привязка тома `WaitForFirstConsumer`. На PVC аннотация `helm.sh/resource-policy: keep`.

Пароль берётся из ключа `POSTGRES_PASSWORD`. Пользователь и база — `socrat`, хост — `socrat-bot-postgres:5432`. Ключ `DATABASE_URL` оператор записывает сам (драйвер `postgresql+psycopg`). Чарт URL из пароля не собирает.

Остальные ключи Secret, без значений: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_OWNER_ID`, `INTERNAL_TOKEN`.

## Updater и x-ui

ServiceAccount `socrat-bot-xui-updater` в namespace `socrat-bot`. Role с тем же именем в namespace `x-ui`: `get`/`patch`/`update` на `deployments` с `resourceNames: [x-ui]`, плюс `get`/`list`/`watch` на pods. RoleBinding в `x-ui` смотрит на этот ServiceAccount. Wildcard на запись манифестов нет.

На контейнере бота заданы `ALERTMANAGER_URL` (`http://kube-prometheus-stack-alertmanager.cattle-monitoring-system.svc:9093`) и `XUI_UPDATER_URL` (`http://socrat-bot-xui-updater.socrat-bot.svc:8080`).

## sudo

Пакет ещё не публикуется, поэтому playbook копирует `/usr/local/bin/socrat-sudo` и модуль в `/usr/local/lib/socrat_sudo`. Команда читает `BROKER_URL` и `INTERNAL_TOKEN` из `/etc/socrat-sudo.env` режима 0600. Playbook этот файл с токеном не создаёт и sudoers не меняет.

Клиент шлёт `POST /v1/sudo` с `user_name`, `node`, `argv` и заголовком `X-Internal-Token`, затем `GET /v1/sudo/{id}`, пока `status` не станет `approved`, `denied` или `expired`. После `approved` процесс заменяется на исходный argv от имени текущего пользователя. Прав это не повышает.
