# Harbor: registry кластера Socrat

Срез на **30 октября 2026**. Harbor уже развёрнут; распределённая HA-схема пока
не развёрнута из-за ресурсов. Это контекст и инструкция, не замена live-проверке.

## Вход и состояние

- Публичный UI и registry: **https://harbor.socrat.alchemmist.xyz**.
- Harbor **2.15.4**, официальный chart **1.19.4**, SHA-256 архива закреплён.
- Обычный human web login — **native Authentik OIDC/MFA** с отдельно reviewed
  project permissions. Локальный **admin** сохранён как emergency recovery,
  не общий повседневный логин. Старое описание «только admin, личных users нет»
  относится к первоначальному bootstrap, а не текущему режиму.
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
- Credentials не включать в открытые Helm values или Git. Argo CD читает Git; отдельных Fleet GitRepo в репозитории нет.
- Insecure registry/TLS skip verify не нужны: HTTPS доверенный.

**Миграция в Harbor уже выполнена для блога, Cats, Format Quorum, Monori и Socrat Home; LMS намеренно остаётся на GHCR.** Fleet image automation не подключать: GitOps-манифесты Fleet сняты, выкладка через Argo CD. Проверенные CI-прогоны и digest приведены в последующих датированных разделах.

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

### Final verified checkpoint — 2026-11-04

Monori CI **41831902224** completed successfully after the home-ingress timeout fix, including all three build/publish/record steps. Current Harbor indexes and all child manifests verified with the pull robot and matched to live Deployment images:

- Cats: `sha256:ffef7edb39d622190b6ba88642bc35f7a8b159943532517889a3ff8d795ed179` (2 Ready).
- Format Quorum: `sha256:2c7127c13aa1ea1efd1ab6e59d4f0a043d19a46ec70462d2ddf876dc351eb153` (1 Ready).
- Monori front: `sha256:ef7def1d4eafdfa28cf4bd72f26fda1bceeb5c335510e26a56029a9f9b1b03c6`; back: `sha256:4543c95fe7f26b342878cee4cee0648918c6ed55f1f62584227661c3efe11ff6`; sync: `sha256:762c3b18504541e195b99ee2999fe723a466ff0bccb06211c87c75a038d33dbd` (each Ready; sync rollout completed).
- Socrat Home: `sha256:41e26b089357b32fc7caefc21dc2bc1dfcb12c7e8f90373fb11dfefb152c734f` (2 Ready; source was already this exact live GHCR index). No separate upstream repository or CI invented.

The only running own-service GHCR image is LMS, intentionally retained there. All temporary image-copy Pods and their credential Secret are removed. Remaining gate is administrative access for scan-on-push and GC: request a working existing admin credential/session through a private local channel; never paste credentials into issue/chat/Git. Until then neither GC dry-run/schedule nor scan-on-push is claimed enabled. No tag/artifact retention deletion performed.

### Administrative gate resolved — 2026-11-04

Working existing break-glass admin access was supplied privately; no password/OIDC/robot-rights reset performed. Scan-on-push enabled and read back for homelab and library. Trivy v0.75.0 default scanner verified with Cats manual scan Success (53 vulnerabilities, 1 Critical/5 High) and actual Socrat Home push-triggered automatic scan Success (216 vulnerabilities, 3 Critical/60 High). The latter re-published identical bytes at an existing tag; no image or tag target changed. Pull blocking was not enabled.

GC dry-run execution 13 succeeded with delete_untagged=false, delete_tag=false, workers=1, server safety window 2h: 0 purged blobs/manifests, 0 bytes freed; all 60 artifacts and 62 tags unchanged. Weekly schedule 3 configured for Sunday 03:00 UTC (cron `0 0 3 * * 0`, next 2026-11-08). No retention/deletion policy enabled. Conservative no-op GC when there are no unreferenced artifacts is expected. API-applied policy intent recorded in deploy/platform/harbor/maintenance-policy.json; Helm does not apply this JSON. Job log download API returns 500 because existing jobLoggers is stdout-only; job parameters/success were verified in stdout and GC history. No broader logging/storage change made.
