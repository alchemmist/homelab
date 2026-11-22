# Authentik: машинный admin API вместо akadmin

Срез: 2 ноября 2026. Это отдельная owner-admin миграция, не часть обычного reconcile.

## Идентичности и границы

- `alchemmist` — личный superuser с существующими UUID/password/MFA; `tim` — личный пользователь с прежними ограниченными правами.
- `ak-outpost-…` — **internal** service-account встроенного outpost. Не удалять/не переносить его токен: он обслуживает n8n/3x-ui gateways.
- `homelab-identity-automation` — отдельный **service_account** для скриптов управления identity. Пароль непригоден для входа (`has_usable_password=False` проверено). Единственный участник `homelab-identity-automation-admin`.
- `akadmin` — прежний Default Admin/владелец bootstrap API token. После проверенной миграции удаляется отдельным guarded action, вместе с привязанным старым token.

**Административные права автоматизации широкие**, не least-privilege per-resource: текущие controllers управляют users/groups/flows/policies/providers. Это перенос существовавшего admin API доступа на машинную идентичность, не утверждение о завершённой RBAC-декомпозиции. Нет членства в `homelab-owner`, immutable links людей и app-role mappings не менялись.

API token имеет прежний класс deployment credential: non-expiring admin secret. Это **не** OIDC access token; пятиминутные bearer lifetimes приложений не увеличивались. Следующий отдельный этап — декомпозиция прав/потребителей и управляемая ротация.

## Секреты и совместимость

Private root на socrat-0: `~/.cache/homelab-authentik/`,0700; файлы0600.

- `automation-api.json`: journal с exact user PK/UUID, group PK, nonce, новым token, recovery evidence и retirement state. Не печатать/не публиковать.
- `credentials.json.AUTHENTIK_BOOTSTRAP_TOKEN` — **историческое имя совместимости**, после миграции содержит новый машинный token. Поэтому существующие consumers не требуют массовой замены кода. Это больше не token akadmin.
- `credentials-before-automation-*.json`, runtime Secret snapshot — guarded pre-change состояние; после retirement старый ключ недействителен. Не восстанавливать этот credential поверх работающей новой DB.
- Bootstrap password удаляется из активного credentials после retirement. Старые зашифрованные/защищённые snapshots могут его содержать; это не действующий вход.

Новый machine token **не доставляется в pod runtime**: bootstrap.py при active journal исключает обе bootstrap-переменные из runtime Secret. Во время миграции удаляются только эти поля и их last-applied копии, остальные Secret fields сохраняются. Существующие процессы могут держать старый env до следующего запуска, но старый key становится недействительным при удалении его user. Специально ради очистки env IdP не перезапускали. После рестарта bootstrap env уже не поступит из Secret.

## Управляемые действия

`ansible/roles/authentik/files/automation.py` устанавливается оператором в private root, не вызывается автоматически routine playbook. Запускать на socrat-0 с существующим owner-admin API и kubeconfig; secrets не передавать в argv/extra-vars.

```sh
python3 ~/.cache/homelab-authentik/automation.py ~/.cache/homelab-authentik --action check
# Явное создание service user/group/token и atomic переключение credential alias:
python3 ~/.cache/homelab-authentik/automation.py ~/.cache/homelab-authentik --action apply
```

При коллизии чужих имён/nonce/UUID/groups, смене owner UUID или неполном journal — остановка, не adoption и не обход проверок. Нативный API запрещает создавать `internal_service_account`; для нашей автоматизации используется поддерживаемый `service_account`. Первый rejected create оставил только пустую journal-owned group; повтор продолжил по тому же nonce без изменения людей.

Отдельное удаление Default Admin требует: exact reviewed UUID/PK, active service token, personal owner admin, отсутствие неожиданных token dependencies, migration-aware bootstrap.py, отсутствие bootstrap env в Secret/explicit pod env, journal evidence реального recovery drill и digest новой off-node encrypted backup.

```sh
python3 ~/.cache/homelab-authentik/automation.py ~/.cache/homelab-authentik \
  --action retire-akadmin --confirm-delete-akadmin
```

Это **удаление**, не routine check. Не копировать recovery evidence из примера или чужого journal для обхода реального теста. После удаления старый token/пароль не служат rollback. Восстановление — через существующий node-admin канал/официальный recovery либо reviewed полный backup restore.

## Независимое восстановление

Owner node/kube access — отдельная trust boundary от IdP. Официальная команда внутри Authentik worker:

```sh
# Через доверенный kubeconfig, на identity worker; вывод содержит СЕКРЕТНУЮ ссылку!
ak create_recovery_key 2 <reviewed-username>
```

Полученная ссылка — bearer credential, не вставлять её в чат/Git/log. Относительный URL открывают на проверенном публичном Authentik HTTPS hostname, не на произвольном домене. Не выполнять команду для реального владельца в обычном smoke.

Проверено на disposable admin: временная отдельная group/user, официальный двухминутный recovery key из node-admin канала, свежий Chromium, native browser session и `/core/users/me/` с exact fixture PK/username и superuser=true; затем точная очистка user/group/tokens. Диагностика сначала ожидала UUID в сокращённом `/me/` serializer; исправлено на PK/username с separate API UUID guard. Один прерванный диагностический fixture был найден и точно удалён; финальный drill прошёл, остатки отдельно проверены.

Это проверка независимого механизма, **не личная owner recovery acceptance и не full DR**. Нужны доступ к ноде/kube API и работоспособные Authentik/DB. Потеря кластера/backup key/off-site escrow остаётся отдельной задачей.

## Приёмка и backup

- 12 unit tests migration/retirement +14 foundation tests; no-adoption, wrong UUID, Secret guard, idempotence, fail-closed incomplete journal, fresh-install bootstrap и runtime exclusion.
- Новый token прошёл API user/group/provider/app/flow/outpost reads; существующий xui controller `--action check` без изменений; live gateway fixture/native MFA на обоих edges.
- n8n оба edges: root302, health200, keyless API401. Это не закрывает ранее открытое owner login/session сообщение.
- Owner/Tim/Outpost immutable IDs/группы, provider/app/binding configuration сохраняются; native x-ui/VPN/Traefik не меняются. IdP pods не перезапускаются этой процедурой.
- AES-GCM backup до миграции и с активной новой машинной идентичностью. `backup.py` включает private automation journal и pre-migration credentials. Полный restore новой snapshot не заявлен.

После любого шага сначала `--action check`; при сбое не удалять пользователей/группы по одному имени. Сохранить private journal для восстановления точного состояния.
