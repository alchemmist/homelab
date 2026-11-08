# Private SPI queue UI

URL: `https://rustfs.socrat.alchemmist.xyz/queue/`.

Minimal HTML/CSS/JavaScript, native monospace, no CDN/framework. The default view
shows active and pending backend jobs, not n8n execution history. Filters include
retry, dead, complete and cancelled; pages contain 25 rows. Read-only refresh is
15 seconds and pauses in hidden tabs. The table shows the alert, saved stage,
owner/Wait state, availability/deadline, claims vs independent failures, review
checkpoints, last error and a link to n8n. Last error is historical metadata and
must not alone be treated as a current failure.

## Cancellation

Only unowned `queued`/`retry` jobs without a publication intent, primary receipt
or issue reference can be cancelled. Active processing/Wait, terminal jobs and
ambiguous/in-progress publication cannot be cancelled. The client confirms the
operation; a SQLite immediate transaction rechecks eligibility and the displayed
`updated` version against concurrent claims. Changed items return HTTP409.

Cancellation sets `state=cancelled`, not SQL DELETE. It retains event, stage,
checkpoints, paid-work receipts, failure budgets and published/evidence history.
`queue_operator_actions` records time and previous state/error/version with source
`private-sso-queue-ui`. Repeating the same cancellation is idempotent. A duplicate
alert delivery does not resurrect a cancelled event. No bulk cancel, forced
retry, active abort, GitHub closure or evidence deletion is exposed.

## Security and deployment

Existing RustFS SSO remains authoritative. Like the private evidence Reader, the
frontend verifies the opaque session cookie only against the fixed TLS
`/outpost.goauthentik.io/auth/nginx` endpoint. Caller identity headers never grant
access. Only trusted response groups `homelab-owner`/`homelab-platform-operator`
are accepted. Anonymous page requests use an exact `/queue/` SSO return target;
expired API sessions return401. Authentication outages fail closed.
The frontend NetworkPolicy accepts only Traefik and permits only backend/DNS and
the same two fixed auth-edge /32 addresses on TCP443 as the evidence Reader.
Host, same-origin Origin and a custom JSON-request header are checked.
No CORS. All pages/API responses are private/no-store with nosniff and a strict
self-only CSP; incident text is rendered with textContent, never innerHTML.

A separate immutable Secret `automation/spi-queue-control` (key `token`) is mounted
read-only by backend and UI; it is not passed in argv/environment, sent to the
browser, logged or committed. The UI has no worker/model/GitHub/S3 credentials or
service-account token and only proxies two fixed operator endpoints. Existing
worker-token credentials do not authorize queue-management endpoints.

`queueUI.enabled` defaults false; live overlay enables it with the existing pinned
runtime image. UI resources:10m/16Mi requests,200m/64Mi limits, separate deployment,
no PVC. Worker image/resources/quotas/PVC and existing workflow graph are unchanged.
Backend changes require a natural-idle rollout and fresh verified HOST SQLite
backup. Production mutation tests/synthetic jobs are not used: cancellation and
race/rollback cases are tested only on temporary local SQLite fixtures.
