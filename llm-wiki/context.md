# Socrat: текущий контекст

Актуальная навигация после принятых миграций16ноября2026. Git описывает intent;
время последней runtime-приёмки смотрите в handoff. Этот файл не разрешает новые
production-операции. Датированные результаты не являются непрерывным мониторингом.

## Источники и владельцы

- Applications: `deploy/argocd/apps/`; values — по ссылке в конкретном Application.
- Ansible inventory: `ansible/inventory/hosts.yml`; mesh registry:
  `ansible/inventory/group_vars/Socrat.yml` → `wg_socrat_nodes`.
- Общий issuer transport и его потребители:
  `deploy/contracts/infrastructure.json`; offline check/generation:
  `scripts/check_infrastructure_contracts.py` (default check, `--write` только Git).
- Argo CD: canonical `deploy/platform/argo-cd/values.yaml`. Старый путь
  `deploy/argocd/values.yaml` — compatibility symlink, не отдельная конфигурация.
  `ansible/playbooks/argocd.yml` — только явно разрешённая установка в пустое
  окружение; существующий release управляется Git Application.
- Карта тем: [README](README.md). Предыдущая длинная хронология сохранена в
  [архиве](context-history-20261116.md); архив НЕ справочник текущего размещения.

## Принятое размещение и данные

- `socrat-5`: Argo application-controller и Rancher; оба single-replica, не HA.
  [Management handoff](../docs/vm105-management-20261116.md): native SSO, UID/spec,
  users/roles проверены; промежуточный login incident явно сохранён.
- `socrat-0`: остальные компоненты Argo CD, RustFS, LiteLLM database, Umami
  database, vLLM/GPU; monitoring размещение сверять по отдельным Applications.
- `socrat-5`: Grafana и Grafana MCP, приняты после холодного переноса.
  [Grafana handoff](../docs/vm105-grafana-20261116.md): exact image digests,
  identity/ACL, native SSO и настоящий MCP→Grafana→Thanos запрос проверены.
  Grafana stateful, claim `grafana-socrat5`; старый claim на `socrat-1` stale.
- `socrat-1`: SPI GitHub broker; остальные компоненты сверять по своим Applications.
- `socrat-5`: n8n, PR Agent; WebUI, Terminal, SearXNG, Umami application;
  LMS, LiteLLM application, renderer; Monori frontend; blog/wiki workers,
  SPI queue UI. Blog/Home имеют распределённые реплики; не снимать anti-affinity.
- Stateful batch на `socrat-5`: Wishlist, Wiki runtime, Monori back/sync,
  SPI worker, format-quorum, LiteLLM branding. [Authoritative handoff](../docs/vm105-stateful-20261116.md).
  Новые записи на `socrat-5` авторитетны. Старые claims — stale recovery, не
  актуальная копия. Rollback после новых записей требует fresh reverse handoff.
- `socrat-5`: [SWE Mini](swe-mini.md), автономная очередь mini-swe-agent для Monori; приём новых задач приостановлен, PVC сохранён.
  Durable SQLite PVC, отдельные non-root Jobs, только `venice-deepseek` через LiteLLM.
  Реальный smoke и переход к Monori приняты17ноября; первый PR/review ещё не принят.
  Production Monori/PVC/банковские credentials не подключены, merge не автоматический.
- `socrat-5`: [OpenHands Canvas](openhands.md), готовый upstream UI + Agent Server. Короткий model/tool smoke прошёл; длинный пилот преждевременно остановился. Ingress выключен, DNS требует sudo, полный PR lifecycle не подключён/не принят.
- Wiki: `deploy/wiki-runtime/values.yaml`, claim `wiki-runtime-socrat5`;
  `/mnt/files/homelab/wiki-runtime/data`. Runtime volume авторитетен, Git sync
  может отставать. Нельзя править managed tree параллельно writer.

## Границы безопасности и незакрытые риски

- Сохранять accounts, roles, passwords/keys, sessions/history, native SSO/TLS/PKCE.
  Не выдавать вход за владельца за пользовательскую приёмку; не обходить MFA.
- Git-first; только адресный reconcile. Нет blanket sync/prune, force deletion,
  live image override, произвольного schema upgrade или сетевого рестарта.
- Не выполнять workflow replay, publication, paid inference, bank sync ради теста.
  Секреты и private receipts вне Git, dirs0700/files0600; не печатать payloads.
- VPN-нагрузки `socrat-2` не затрагивать. Не менять Mac VPN/DNS/routes, AllowedIPs,
  WG identities, operator keys или permanent sudo ради удобства.
- Relay на `socrat-0` для связи `socrat-1` ↔ `socrat-5` — non-HA mitigation;
  native root cause не доказана. Healthy приложений не доказывает VM DR/HA.
- Prometheus historical corruption остаётся отдельной проблемой; не чистить WAL.
  VM cold boot/full independent restore требуют отдельной maintenance-приёмки.
- Backup coverage: n8n daily job использует актуальный claim; последний paired
  архив на `socrat-3` SHA-verified и его SQLite независимо восстановлен/read-only
  integrity-checked. Один unpaired archive не принят. Остальные recurring datasets
  ещё не закрыты: [матрица](../docs/backup-coverage-20261116.md). Retain не backup.
- Исторические Wishlist OutOfSync, SPI failure и ограничения human callbacks /
  production telemetry-child не стирать и не объявлять исправленными без теста.

## Текущая работа

Владелец разрешил последовательное устранение выявленного технического долга и
отдельный перенос Grafana/Grafana MCP на `socrat-5`. Исходное исследование:
[refactoring audit](../docs/refactoring-audit-20261116.md). Не считать все пункты
закрытыми по наличию этого файла; состояние фиксируется в реализации/приёмке.

Первый пакет реализации опубликован: canonical Argo bootstrap guard, общий issuer
контракт/generator, mesh+fixed-relay drift checks (без рестарта сети), current/history
разделение, offline CI. Дополнительно исправлены два прежних CI-дефекта: stale SPI
expected codes (Publish-only STORAGE_TRANSIENT сохранён, workflow не менялся) и
устаревшие alert graphs. Append-only panel ID ledger сохраняет исторические ссылки.
[Владельцы и обслуживание](../docs/infrastructure-contracts.md). Регулярные backup
остальных datasets, полная Wiki publication-сверка и DR не объявлены завершёнными.

Поэтапный статус и открытые работы: [implementation checkpoint](../docs/infra-refactor-progress-20261116.md).
Публичная Wiki: устаревший текст подтверждён HTTP200; [проект правки](../docs/wiki-public-refactor-proposal-20261116.md),
публикация требует штатного native write-scoped подключения, которого в этой сессии нет.

Продолжение по запросу владельца: бэкапы пока не делать. Legacy Rancher installer
выведен в fail-closed refusal-only entrypoint; CI проверяет отсутствие последующих
plays/imports и согласованность Argo bootstrap version/values с Git Application.

Следующий source-only пакет: inventories трёх vendored trees (Git baseline,
не upstream trust), retirement legacy LiteLLM installer, единый stricter placement
checker для CLI/Ansible: current RS revision + Pod Ready gates. Read-only проверка
Rancher/Grafana/MCP на `socrat-5` пройдена; бэкапы по-прежнему отложены владельцем.

Legacy continuation: `llm-vision.yml` и combined `monitoring-llm.yml` теперь
refusal-only до GPU/Helm/identity действий. Gateway monitoring helper — read-only
проверка существующих owner/credentials/ACL, без install/repair fallback. Бэкапы,
inference и production maintenance не выполнялись.

Endpoint/source-pointer continuation: relay preflight использует mesh registry;
CI сверяет unit /32 allowlist и sandbox с canonical endpoints, без изменения unit
или рестарта. Новый offline checker сверяет Argo local sources/values/refs и
выбранные current-doc links/claims/default RBAC; исторические receipts исключены.

Operational continuation: Open Terminal/SearXNG/search bootstrap installers retired
before keys/Helm/imports. CI classifies literal Ansible Helm entrypoints without
certifying remaining review-required or VPN/GPU/backup-excluded paths. Vendor
baseline expanded to existing monitoring bundle and five dependency symlinks;
no chart/version/runtime changes or production/backup operations.

WebUI lifecycle/HTTPS/tool-guard and Terminal browser-cleanup entrypoints now
refuse before all remote tasks/imports; chart-owned protection remains unchanged.
Old-PVC backup/upgrade instructions are not a fallback. Within the literal Helm
gate only k3s/storage-nfs remain review-required; no maintenance was performed.

Quality Graph research/expansion: compatible0.2.0compiler/provider/runtime bootstrap
is published; minimal bootstrap55666f1b, main CI43937624526success. Semantic cost-layered redesign,
rule/tool matrix and initial failed-regression audit: [quality runbook](../docs/quality/README.md).
Fast gates run in parallel; tool integrations precede a disposable Kind lifecycle
job (hosted run43954132178:4passed/0skipped). Full-graph acceptance remains a
separate PR result, not a new required-check policy. No production/backup/GPU/VPN/identity operations authorized.

2026-11-16 LLM key activity short-range No data fixed (50de2fac): Requests by API
key used increase(counter[$__interval]); small pickers/pixel step made lookback5s,
insufficient counter samples. Live reproduction:5s empty,15s/1m populated. Replaced
ONLY panel1 lookback with fixed[1m], described rolling/extrapolated requests/minute,
not nonoverlapping buckets (do not sum adjacentpoints).30daytable unchanged; owner
live panels matchedGit before edit. Range queries5m/30m/1h/3h populated afterfix;
ArgoSyncedHealthy, GrafanaAPI serves exactfixedpanels. Regression test
 tests/test_llm_keys_window.py; no backend/collector mutation or missing→0 fallback.

17Nov owner architecture correction: `wg-socrat` is VPN-as-infrastructure only.
Application foreign egress must use a distinct native3x-ui service client and
its subscription with an official Pod VPN client, NOT a new SSH-to-NL tunnel.
[Reusable service-VPN runbook](service-vpn-egress.md). N8N corrected in5b722c5c;
[finite acceptance and cleanup](../docs/n8n/service-vpn-20261117.md). Venice's
pre-existing SSH-egress remains a separately recorded deviation, not a template.
