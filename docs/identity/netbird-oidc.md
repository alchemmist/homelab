# NetBird: вход через Authentik на существующих узлах

Узкий контроллер: `ansible/roles/identity_integrations/files/netbird_oidc.py`.
Он готовит OIDC-провайдер Authentik для уже работающего management
`netbird.socrat.alchemmist.xyz`. Новых VM, платных сервисов и отдельного IdP нет.
Полный `configure.py` не запускать и не импортировать: у него чужие side effects.

Live private stage3 выполнен 2026-11-02: dedicated Authentik application и
native NetBird connector созданы и прочитаны обратно. См.
[фактический отчёт](netbird-stage3-record.md). Это **не** личный OIDC-вход
владельца, перенос ownership или публичное включение; bootstrap не повторять.

## Что закрепляет код

Проверено по дереву NetBird **v0.82.0** (`idp/dex/connector.go`, SHA256
`3ef9df52d86ea9205055a8f44f7e4fa4cacb0d265c746474c506685a39f7ff34`) и Dex OIDC
(`39b2adbe048fbcbe2d2f531f33e0a2de867cbc0eb960eacc39297e5d64e63747`).

- `GetRedirectURI`: срезать один завершающий `/`, если нет суффикса `/oauth2` —
  дописать его, затем `/callback`. Иной callback контроллер не выдумывает.
  Нет флага `--callback`. Нет `server.auth.issuer` — `apply` блокируется.
- Типы коннектора `oidc` и `authentik` запрашивают только `openid`, `profile`,
  `email`. Scope `groups` не запрашивается (`okta`/`pocketid` — другое).
  `getUserInfo` и `userIDKey` не задаются, `insecureEnableGroups=true`, поэтому
  Dex читает claim `groups` из ID token, ключ по умолчанию `groups`, субъект — `sub`.
- Отдельный profile-mapping `homelab-netbird-profile` отдаёт `name`,
  `preferred_username`, `nickname` и allowlist групп. Stock profile и
  `homelab-groups` к провайдеру не крепятся. Email только из managed scope `email`.
  `sub_mode=user_uuid`: `sub` остаётся UUID Authentik, не email.

## Кого пускает

Только два уже существующих пользователя, UUID не меняются:

- `alchemmist` `9e33877a-3eaa-4541-98eb-8cdc10088ef6`, группа `homelab-owner`
- `tim` `0d2c194a-dee7-4226-b599-0a44ce2f2b76`, группа `homelab-observer`

Допуск в приложение `netbird-pilot` — одна binding на `netbird-pilot-login`.
В claim дополнительно только `netbird-pilot-grafana` и `netbird-pilot-ssh-socrat-2`.
Обе записи добавляются в эти три группы. Чужой участник, чужой объект без journal
PK и маркер, superuser-группа у Tim, наследование или RBAC-роль — блокер до записи.

Контроллер не делает PATCH `core/users/`. UUID, email, `is_superuser`, прежние
группы и факторы Authentik не переписываются. Провайдер не добавляется на
embedded outpost. Существующий Grafana-провайдер не трогается.

## Команды

По умолчанию `check`: только GET. `plan` тоже только GET и печатает digest.
`apply` требует `--approve-sha256` этого digest. Секрет клиента пишется лишь в
`netbird-oidc-runtime.json` (0600). `netbird-oidc-journal.json` хранит PK, UUID,
маркер и SHA256 секрета, не сам секрет и не bootstrap-токен. Symlink не
следуется. Повторный apply с тем же секретом не создаёт вторую группу.

На узле владельца, каталог 0700, внутри уже лежит `credentials.json` с
`AUTHENTIK_BOOTSTRAP_TOKEN`. Issuer брать из реального конфига management
(`server.auth.issuer` на `https://netbird.socrat.alchemmist.xyz`).

```sh
python3 netbird_oidc.py "$ROOT" check --netbird-config "$NETBIRD_CONFIG"
python3 netbird_oidc.py "$ROOT" plan --netbird-config "$NETBIRD_CONFIG"
python3 netbird_oidc.py "$ROOT" apply --approve-sha256 "$DIGEST" --netbird-config "$NETBIRD_CONFIG"
```

`--mappings` по умолчанию `deploy/identity/account-mappings.json`.
`--public-edge 109.173.40.247|176.98.185.59` только подменяет DNS существующего
Authentik на уже известный адрес. Этот коммит live API не вызывает.

## Что родитель делает после ревью

1. `check` и `plan` с живого узла, сверить callback и состав операций.
2. Явный `apply`, затем снова `check`.
3. Отдельным reviewed шагом указать существующему NetBird IdP issuer
   `https://auth.socrat.alchemmist.xyz/application/o/netbird-pilot/`, client id
   `socrat-netbird` и секрет из runtime-файла. Локальный парольный вход NetBird
   этот скрипт не выключает: обязательность Authentik на management появится
   только после этого шага, не из одного `apply`.
