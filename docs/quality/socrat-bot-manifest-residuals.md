# Socrat Bot manifest findings: residual decisions

This is a source/render review, not an acceptance of the historical quality-debt
receipt and not permission to weaken service behavior. The PR #494 inventory lists
19 findings for this owner: `env-value-from` ×5, `read-secret-from-env-var` ×5,
`host-network`, `no-liveness-probe` ×2, `no-readiness-probe` ×2,
`no-read-only-root-fs`, `non-isolated-pod` ×2, and `run-as-non-root`.

The current app render has a bot Deployment and, with the production values, a
Telegram-path-control Deployment. The bot's main container has HTTP readiness and
liveness probes; these do not transfer to the two long-running Telegram-path
probe containers. The probe containers already run non-root with read-only root
filesystems; their writable sample data is an explicit memory-backed volume.

## Preserve existing service contracts

- Keep the bot on `socrat-2` with `hostNetwork` for Telegram API egress. The
  service runbook records that pod egress from `socrat-3` cannot reach
  `api.telegram.org`; removing host networking or moving the node is not a safe
  lint-only change. A replacement requires a representative disposable routing,
  restart and Telegram-delivery/retry acceptance before any production cutover.
- Keep all five SecretKeyRef environment inputs (database URL, Telegram bot token,
  webhook secret, owner ID and internal token) until the bot application and its
  DB/Telegram secret owners demonstrate supported file delivery, refresh/rotation,
  restart and rollback behavior. No secret values belong in this repository.
- Do not add a default-deny policy by guessing peers. A reviewed policy needs the
  actual webhook/ingress and internal API clients, Postgres, Alertmanager, DNS,
  Telegram HTTPS egress, and the path diagnostic's DNS/TLS targets, plus negative
  tests proving denied unrelated traffic without breaking delivery. Host-network
  policy enforcement must be demonstrated for the actual CNI before relying on it.
- Do not assert a non-root UID or read-only root filesystem for the bot image
  without authoritative image/runtime UID and writable-path evidence. A valid
  change also needs application behavior tests for startup, temporary files,
  graph rendering, DB CA access and Telegram delivery; no writable-path mount is
  added speculatively.
- The path diagnostic containers lack process health endpoints. A meaningful
  readiness/liveness contract needs an explicit definition of diagnostic
  freshness and failure semantics, and tests distinguishing a dead sampler from
  temporary external DNS/TLS failures and sample-volume write failures. Probes
  must not make transient Telegram/network failures restart the bot or claim
  successful Telegram delivery.

## Required approval/evidence to close

No manifest change is made here because the remaining restrictions affect active
service behavior and their prerequisites are not evidenced by the local chart or
bot source. Before changing them, the owner must approve (1) any alternative
Telegram route and cutover acceptance, (2) supported credential-file and rotation
contracts across the bot and secret owners, (3) the exact network peer matrix and
CNI enforcement test, (4) verified bot image UID/writable paths, and (5) probe
failure semantics for the diagnostic containers. Until then, these remain real
findings, not suppressions, waivers or evidence of a strict-green result.
