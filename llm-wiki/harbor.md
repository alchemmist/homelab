# Harbor: registry кластера Socrat

Срез на **30 октября 2026**. Harbor уже развёрнут; распределённая HA-схема пока
не развёрнута из-за ресурсов. Это контекст и инструкция, не замена live-проверке.

## Вход и состояние

- Публичный UI и registry: **https://harbor.socrat.alchemmist.xyz**.
- Harbor **2.15.4**, официальный chart **1.19.4**, SHA-256 архива закреплён.
- Web-пользователь **admin** существует. Отдельного персонального пользователя
  пока не создавали; саморегистрация отключена, новых пользователей создаёт admin.
- Начальный пароль admin на socrat-0:
  `~/.cache/homelab-harbor/private-values.json`, поле `harborAdminPassword`.
  После смены пароля в UI файл не гарантирует актуальность пароля.
- Пароли, robot secrets и содержимое private-values никогда не выводить в чат,
  логи или Git. На Mac пароль можно передать сразу в `pbcopy` через SSH,
  не печатая в терминал. Логин robot accounts не использовать для web UI.

## Образы и автоматизация

Приватный проект **homelab**, начальная квота 80 GiB. Стандартный проект `library`
тоже переведён в private. Только admin создаёт проекты.

Формат image reference:

```text
harbor.socrat.alchemmist.xyz/homelab/<application>:<git-sha>
```

Для production желательно фиксировать digest. Не полагаться на mutable `latest`.

Созданы **проектные**, а не глобальные robot accounts:

| Назначение | Имя в credential-файле | Права |
|---|---|---|
| CI | поле `name` из `ci-push.json` | repository pull/push только в homelab |
| Kubernetes | поле `name` из `cluster-pull.json` | repository pull только в homelab |

Использовать точное имя из файла: Harbor добавляет robot/project prefix.
У обоих срок действия **90 дней с момента создания**, нужна своевременная ротация.
При пропаже локального credential-файла initializer не пересоздаёт существующего
робота молча: нужно явно согласовать ротацию.

Credentials на socrat-0, каталог 0700, файлы 0600:

```text
~/.cache/homelab-harbor/private-values.json
~/.cache/homelab-harbor/ci-push.json
~/.cache/homelab-harbor/cluster-pull.json
```

На Mac robot credentials скопированы вне репозитория:

```text
~/.config/homelab/harbor/ci-push.json
~/.config/homelab/harbor/cluster-pull.json
```

### Push с Mac

Команда ниже передаёт пароль через stdin, а не аргумент командной строки.
Использует отдельный Docker config, не меняя основной login Docker:

```sh
python3 - <<'PY'
import json
from pathlib import Path
import subprocess
root = Path.home() / '.config/homelab/harbor'
r = json.loads((root / 'ci-push.json').read_text())
config = root / 'docker'
config.mkdir(mode=0o700, exist_ok=True)
subprocess.run(['docker', '--config', str(config), 'login',
                'harbor.socrat.alchemmist.xyz', '--username', r['name'],
                '--password-stdin'], input=r['secret'], text=True, check=True)
(config / 'config.json').chmod(0o600)
PY

docker tag my-app:build harbor.socrat.alchemmist.xyz/homelab/my-app:<git-sha>
docker --config "$HOME/.config/homelab/harbor/docker" push \
  harbor.socrat.alchemmist.xyz/homelab/my-app:<git-sha>
```

Заменить `<git-sha>` реальным SHA. Docker config содержит секрет в обратимо
закодированном виде: защищать как пароль. В CI использовать secret store и
эфемерный Docker config, не копировать admin password.

### Pull из Kubernetes

- Сформировать `kubernetes.io/dockerconfigjson` Secret с **pull-only** robot.
- Secret нужен **в каждом namespace**, где приложение скачивает приватные образы.
- Ссылаться на него через Pod `imagePullSecrets` или специально выбранный
  ServiceAccount. Не менять глобально все ServiceAccount без необходимости.
- Credentials не включать в открытые Helm values, Fleet GitRepo или Git.
- Insecure registry/TLS skip verify не нужны: HTTPS доверенный.

**Существующие деплои с GHCR ещё не мигрировали.** Fleet image automation и CI push
тоже нужно подключать отдельно; наличие Harbor само по себе их не переключает.

## Как развёрнуто сейчас

Все компоненты на **socrat-0**, 6 Pod / 7 контейнеров. PVC `local-path`:
registry 100 GiB, PostgreSQL 5 GiB, Redis 1 GiB. PVC keep и PV reclaim **Retain**.
Это защита от удаления ресурсов, **не бэкап** и не HA. Local-path capacity не
является жёсткой файловой квотой.

Два публичных ingress (дом и VPS) используют один ingress/TLS Secret.
Namespace `harbor` включён в `charts/traefik-edge/values.yaml`.

При потере socrat-0 новые push/pull недоступны; запущенные контейнеры продолжают
работать. Плановые независимые бэкапы и restore пока **не настроены**. Не делать
Harbor единственной копией критичных образов до их настройки.
Trivy, автоматические GC и retention deletion пока отключены.

Источники и применение:

- `deploy/harbor/values.yaml`;
- `ansible/roles/harbor/`, `ansible/playbooks/harbor.yml`;
- `docs/harbor.md` — эксплуатация и восстановление;
- из `ansible/`: `ansible-playbook playbooks/harbor.yml`.

SSH dual-address hostname может попасть на неправильный публичный вход. Для
socrat-0 проверен home override `Hostname=109.173.40.247` с прежним
`HostKeyAlias=[socrat.alchemmist.xyz]:2222`. Не отключать host key checking.
Не применять playbook автоматически только ради чтения состояния.

Проверено: health 200 и trusted TLS через оба публичных IP; anonymous `/v2/` 401;
push BusyBox push-роботом, pull Pod на socrat-1 pull-роботом с `Always`, лог
`harbor-pull-ok`. Тестовый Pod и временный Secret удалены; smoke image оставлен.
Это не проверка отказа ноды или восстановления.

## Согласованное направление HA

Пользователь выбрал полноценный распределённый Harbor, но принял текущую
нехватку ресурсов. План в `docs/harbor-ha.md`:

1. По две реплики core/portal/jobservice/registry на socrat-0/1.
2. Трёхузловое S3-хранилище на socrat-0/1/3, кандидат Garage с RF=3;
   совместимость и quorum/rejoin ещё нужно проверить.
3. CloudNativePG, 3 PostgreSQL instance с синхронной репликацией.
4. Redis/Valkey + Sentinel на трёх нодах; **не Redis Cluster**.
5. Сохранить URL, encryption/token signing keys и пользователей/роботов.

Цель — переживать потерю одной ноды, включая socrat-0. **Не обещать переживание
потери квартиры:** две из трёх нод схемы находятся дома, quorum исчезнет вместе с ними.

HA-зависимости и миграция **не применены**. Реализован read-only preflight:

```sh
python3 scripts/harbor-ha-preflight.py collect --output /tmp/harbor-ha-inventory-UNIQUE.json
python3 scripts/harbor-ha-preflight.py check \
  --inventory /tmp/harbor-ha-inventory-UNIQUE.json \
  --output /tmp/harbor-ha-capacity-UNIQUE.json
```

Новые уникальные имена; файлы 0600, без перезаписи. Данные старше 15 минут
отклоняются. Exit 1 — ресурсный blocker, 2 — ошибка инспекции. Даже успешный gate
не разрешает cutover: ещё нужны бэкап/restore, совместимость и failover-тесты.

Policy `deploy/harbor/ha-policy.json` хранит резерв OTel независимо от его
незавершённых файлов. Если локальный OTel policy присутствует, берётся больший
резерв; отсутствие файла не обнуляет уже согласованную потребность в памяти.

Первый gate: socrat-1/3 не хватает RAM и scheduler headroom, socrat-0 не проходит
запас диска при предварительном staging budget. Исторический отчёт в
`deploy/harbor/migration-evidence/capacity-initial.json`, не принимать его за live.
Не уменьшать бюджеты ради зелёного результата, не отбирать ресурсы OTel и не
удалять данные без согласования. Следующий шаг — решение по RAM/ёмкости, затем
независимый проверенный бэкап и изолированное развёртывание HA foundation.


## Дополнение 1 ноября 2026: Authentik

**Harbor теперь использует native OIDC / Authentik**: provider grant_types исправлены,
`systeminfo.auth_mode=oidc_auth`, owner group → system admin. Старый local admin
остаётся аварийным входом. Initial admin password оказался stale; его не сбрасывали.
Применён поддерживаемый CONFIG_OVERWRITE_JSON из Secret, отдельный Helm overlay.
Private project и scoped robots сохранены: pull-only robot после миграции получил
BusyBox manifest 200 с прежним digest. Browser owner login ещё требует проверки.

Перед переключением encrypted DB+registry+credentials backup на Mac; PG18 dump
восстановлен в isolated PG18, три blob проверены SHA-256. Это не full Harbor DR.
Не применять legacy bootstrap API с устаревшим initial password после активации OIDC.
Другие детали/границы SSO: `llm-wiki/identity.md`.

## Runtime repair — 2026-11-04

- Argo rendering upstream `lookup`/random Secret defaults rotated internal core/jobservice tokens. A running core retained its original environment, causing jobservice internalconfig HTTP 401. Restored runtime token/password values privately, retained the original signing keypair from the private Helm release, and disabled rendering existing runtime Secrets with `externallyManagedRuntimeSecrets: true`. Existing Secrets remain in the cluster; their Argo tracking annotations were removed explicitly, without pruning or credential publication.
- Core CONFIG_OVERWRITE_JSON now references `socrat-authentik-harbor/config-json`, preserving the deployed Authentik configuration rather than applying db_auth defaults.
- Verified Harbor health API healthy; core/jobservice/database/registry Ready. Trivy enabled with CPU/memory limits and verified Ready. Scan-on-push and GC are NOT yet verified: bootstrap admin credential cannot authenticate to administrative GC API; do not reset OIDC/admin credentials or schedule destructive retention to bypass this.
- Removed unused switcher monitoring objects and unused syncthing-private-nginx ConfigMap after confirming no pod references. No global prune enabled. Cert-manager selector drift and remark42 credential preservation corrected in Git.
- Release action now pins GitHub host keys, uses an explicit private key without ssh-agent, bounds network calls/retries, uses SSH-over-443, and rebases the same commit on concurrent main updates including remote ref lock races. Static/unit checks pass; main and v1 published through 56037a9. LMS end-to-end verification remains pending.
- GitHub status reports an active Git Operations incident (intermittent Git errors); observed SSH auth failures and HTTPS Internal Server Error. No proof of deploy-key expiration. Do not rotate all keys as an incident workaround.
- Remaining: LMS HA ownership drift, scan-on-push/GC administrative access, exact-digest registry/CI migration. Backups/NFS remain outside this task.

### Migration and upload-path verification — 2026-11-04

- All 42 Applications reached Synced/Healthy after LMS HA ownership restoration (`849e078`); CNPG 3/3, existing backup PVC and schedule preserved. No backup redesign or NFS work performed.
- Copied the exact missing Format Quorum and Monori sync OCI indexes. Verified digest plus both amd64/attestation child manifests through the public Harbor endpoint with the existing pull robot. Copied/pinned Cats, Format Quorum, Monori front/back/sync and Socrat Home to Harbor; namespace pull Secrets provisioned before activation. GHCR originals retained, LMS remains GHCR by agreement, deleted Yandex Voice application not recreated.
- Monori sync's large layers needed a bounded internal-registry upload with existing registry credentials, followed by public authenticated manifest publication and digest verification. Temporary copier pods and their credential Secret were deleted.
- Corrected earlier timeout diagnosis: traefik-edge had no request-body deadline, but the separate k3s home Traefik still used its default 60s read timeout. This caused public Harbor large-layer PUT/PATCH HTTP 499. Updated the existing HelmChartConfig and Ansible home_ingress_ha role to preserve tracing/HA arguments and disable web/websecure body-read deadlines. Kept the bundled Rancher/k3s chart and verified deployed flags and 2/2 rollout.
- Source CI commits: Cats `84cf901`, Format Quorum `74b7e85`, Monori `71cac39` publish to both Harbor and GHCR in the same build, then invoke the existing single-step deploy action. Removed the active legacy SSH deploy workflows in Format Quorum and Monori. Cats run `41831884179` succeeded; Format Quorum run `41831893923` succeeded after the home-ingress fix. Monori run `41831902224` is still being verified; front/back publish+record steps have succeeded.
- Scan-on-push and GC remain blocked on working administrative Harbor access. Both the provisioned bootstrap password and original private Helm-release admin password return 401. Robot credentials support image push/pull, not global administration. No password/OIDC reset, DB credential changes, retention deletion or GC scheduling performed to bypass this. Trivy is Ready, but that alone does not prove a successful vulnerability scan.
