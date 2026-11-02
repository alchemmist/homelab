# NetBird user-access pilot — BLOCKED / manual review only

[Русский runbook, blockers и acceptance](../../docs/netbird-user-access-pilot.md).

- `pilot.inputs.json` — намеренно неполные deployment inputs; default render завершается
  `BLOCKED` до создания файлов. Не заменять null выдуманными DNS/IP.
- `images.lock.json` — проверенные 2026-11-02 NetBird 0.82.0 / dashboard 2.96.0 digests.
- `upstream.lock.json` — URLs/SHA256 официального reference config/installer/OpenAPI,
  docs commit. Upstream installer не запускается.
- `../../scripts/netbird-pilot.py` — только локальная валидация/компиляция; никаких apply,
  cluster/API mutations или создания пользователей. Все CLI outputs только вне worktree.
- `../../scripts/netbird-pilot-probe.py` — read-only клиентские TCP/TLS probes; это не
  автоматический fault injector и не доказательство production acceptance.

Не добавлять этот каталог в Argo watched paths. Нет `Application`, auto-sync или
готового к apply manifest с placeholders. Для Community — один Management/Signal;
два routing peers дают data-plane failover, **не бесплатный active-active control plane HA**.
