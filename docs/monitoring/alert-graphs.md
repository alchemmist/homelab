# Alert graph mapping and release gate

`python3 scripts/alert_graphs.py --check` verifies the generated inventory,
annotation values, reviewed gateway panel policy and diagnostic dashboards.
The current source set is200 rules:193 Prometheus rules and7 Grafana-managed
rules,188 distinct mappings,29 dashboards. Array order is priority: Telegram
uses the first panel; SPI collects every declared panel. Diagnostic primary
panels remove root numeric filters so healthy/near-threshold samples are visible;
a second panel retains the exact triggering expression. Logical operands and
full series labels remain visible. Rule expressions, labels, routing and current
thresholds are unchanged. These are rule-scoped panels, not a false promise that
aggregation can reconstruct a lost per-instance label.

Prometheus owners consume generated override values through the existing Argo
Applications. Grafana-managed rule JSON uses the existing authenticated provisioning
procedure; live annotations were applied in place (see activation receipt).
Dashboards are loaded through the existing Grafana dashboard sidecar. The gateway
policy is generated from those same panels, not a second manual mapping table.

Gateway resources and consumer mounts are opt-in and disabled by default. A full
release also needs immutable service and remote-renderer digests, a scoped
Grafana Viewer machine identity, separate Telegram/SPI tokens mounted only into
those roles, observed hostNetwork source admission, renderer authentication and
actual CNI-path acceptance. No credential material belongs in Git.

The companion SPI service source implements persistent private PNG spooling,
content-addressed v3 binary evidence and protected S3/Authentik links. The bot
source implements one native photo message with the complete caption/buttons,
photo edits, safe complete-text fallback and additive migration0017. Existing
text messages are not deleted or converted. Source presence is not live PNG
acceptance. Before enabling SPI graph capture, update the original n8n workflow's
validation allowlist with `GRAPH_CAPTURE_DEFERRED` in place and preserve all other
workflow settings, credentials and state.

Pre-push private SQLite integrity/FK/hash and PostgreSQL custom-format/list/hash
backups were verified off-cluster. All historical work remains untouched. Host
SPI suite329 tests(3optional skips); offline native amd64 suite329/329,zero skips
under1CPU/384MiB/64MiBtmpfs; bot PostgreSQL suite202passed/17backend-specific skips;
Helm graph/inventory suites9passed. Renderer, authenticated evidence download and
natural one-message Telegram delivery remain explicit live acceptance gates.

## Historical pre-activation reconciliation receipt

Homelab `a1a3fa3` reconciled: all189 live Prometheus rules carry `spi_graphs`,
28 generated dashboard ConfigMaps exist, all13 checked Applications are
Synced/Healthy and all4 nodes are Ready. The7 managed Grafana annotations are
source-only until the authenticated update phase. The deployed independent
`identity/rustfs-gateway` was read-only verified to support v3/stored_bytes/PNG.

Production image release is blocked at hosted-runner Harbor TLS authentication,
not unit tests: SPI run42610770650 and bot run42610352796 (including one bounded
failed-job retry). The SPI publication gate was restored to false. Both consumer
flags and graph gateway stay disabled; neither bot migration0017 nor the image
backend was activated. DNS, routes, TLS verification and existing permissions
were not changed to get around the failure. Native workflow validator changes,
renderer/credential/CNI acceptance and natural end-to-end observation remain
pending. See the application `docs/alert-graphs.md` for exact source commits and
CI links; do not interpret mapping reconciliation as delivered screenshots.

### Recovery safety extension (2026-11-09)

Four additional source rules cover voter external-power loss, battery<20%, one
missing fresh voter and unproven quorum health. Generated current inventory now
has200 entries/188 mappings/29 dashboards. This does not rewrite the historical
196-rule live acceptance above. New rules have native promtool coverage including
no-data/stale-voter cases; their runtime/source acceptance belongs to the cluster
recovery receipt. Existing alert conditions, labels and routes remain unchanged.

## Production activation receipt — 2026-11-09 14:01 UTC

This supersedes the earlier blocked/disabled release receipt below/above; it is
not a claim that historical queue backlog or unrelated incidents were repaired.

- Current live coverage: **193/193 Prometheus + 7/7 Grafana-managed rules** have
  ordered `spi_graphs`; source inventory200 rules/188 mappings/29 dashboards.
  Managed annotations were changed in place with condition/data/routing/labels,
  pause state and other annotations verified unchanged.
- Canonical Harbor CI works again. Existing robot grant `pull,push` is verified
  using Python HTTPS; an ephemeral private Docker config and an isolated BuildKit
  with `GODEBUG=tlsmlkem=0` avoid the observed hosted-runner Go TLS key-share
  compatibility failure. Certificate verification, DNS, routes, robot permissions
  and cluster pull identity are unchanged. The server TLSOption experiment was
  fully reverted, including its leftover custom resource. No new release token
  or user action is required.
- SPI publication run42622862630 succeeded. Full-service worker/frontend/broker
  and gateway use immutable SPI digest
  `sha256:eb830c98ccd6d19ef8535fcb5be003d783cb4aeb98d18fe64e66c1f51a37f64a`
  (source `b70462d`). Bot run42629684670 passed **207 PostgreSQL tests/17
  backend-specific skips** and deployed source `6e7f6d7`, digest
  `sha256:2bec0997b93f0c91bd0dfc561886a1e497058c4b39c5e37ae7842637c99a8635`.
- Renderer v5.12.10 uses actual verified Docker Hub digest
  `sha256:a7970b826f6e477461e02bf5463d92634e9ad27d525e4e50296978a2e592d2d7`;
  the chart's `image.sha` field requires raw64 characters, not a `sha256:` prefix.
  Renderer request logging is silenced and log level is error: never retain its
  ephemeral Grafana renderKey in normal URL access logs.
- Scoped native Grafana Viewer account `socrat-alert-graphs`, authenticated
  renderer, separate SPI/Telegram keys and private pull Secrets are deployed.
  Credentials are not in Git. Viewer token expires **2027-02-07T13:00:52Z**:
  renew it before that date using the native service-account token API, update
  only the existing gateway's `grafana` key and roll the isolated gateway through
  normal GitOps; no human SSO/CI identity or worker migration needs changing.
- Observed hostNetwork admission is the exact post-DNAT flannel source
  `10.42.0.0/32`, not the socket's pre-DNAT node IP. Other gateway ingress is
  namespace/pod-selected SPI only; no general CIDR admission was added.
- The original n8n workflow `J9akzlydrf9XZiID` was paused in place; current
  execution14787 finished naturally. Its validator gained only
  `GRAPH_CAPTURE_DEFERRED`. After zero logical owners/processing/active paid
  reservations, an idle off-cluster SQLite checkpoint was verified:
  236974080bytes, SHA256
  `c719d28370ab1e4c7ee8b6ea3f2840aa3992a23443b07fac226f75159438995e`.
  All766 prior job IDs/creation times and491 terminal state/stage/result/intent
  hashes survived exact-image activation. Same PVCs/state/credentials/leases,
  deadlines/budgets and historical Jobs were retained; no reset/replay occurred.
- Homelab activation `1321b97` set `bundleEnabled=true` and SPI graphs enabled.
  All three runtime roles no longer mount frozen code ConfigMaps. Only the three
  unused old code ConfigMaps were retired after proving no active pod mounts,
  saving preimages and applying UID/resourceVersion delete preconditions. No
  broad prune or Job/PVC/Secret/RBAC deletion was performed. Frozen Git snapshots
  remain rollback-only, never a second source for app development.
- The same workflow is active again; ordinary `dispatch_sent` and
  `publication_ok` resumed naturally. The native broker's next scheduled Job
  completed with the full-service image; no synthetic broker Job was launched.
- Real gateway PNG1200×600 passed strict validation and exact SHA256. Actual
  bot5-second capture + durable PostgreSQL snapshot completed in4.443s. Native
  Telegram receipts show **9 photo cards** with message IDs and persisted graph
  references from natural alerts: no real test notification was sent. Complete
  captions/inline buttons and photo edits share the native delivery path; old
  text cards remain text and conservative UTF-16 overflow preserves full text.
- A separately labelled synthetic storage-only check (no SPI job, model call,
  GitHub publication or notification) captured **both declared panels**, stored
  all4 immutable v3 objects using the actual SPI writer role, then read both
  PNGs through the deployed Reader's read-only IAM/manifest/hash-validation
  domain path. Model context was byte-equivalent before/after graph attachment.
  GitHub markdown uses protected Reader links; anonymous public PNG access401.
  This is **not** an owner-browser SSO login test: that positive browser check
  could not be repeated because the shared browser profile was already in use.
  Existing Authentik group/cookie authorization was not changed or bypassed.
- Harbor, Grafana, SPI and bot are **Synced/Healthy**; all4 nodes Ready. Gateway
  and both consumer flags are enabled in deployment overrides (chart defaults
  remain off). Private backup/credential/acceptance artifacts remain outside Git.

## Gateway-only maintenance release and renderer headroom

The canonical stateless gateway image is now `deploy/grafana/values.yaml`, loaded
last by the existing Grafana Argo Application. Its chart mirror has the same
`gateway.{tag,digest}` contract. The full SPI image publisher's explicit
`deploy_target=alert-graphs` uses `deploy-to-socrat@v1`, `app=grafana`,
`component=gateway`: only those image fields change. Stateful SPI worker
images/PVCs/native ownership are not part of this target; their ordinary release
still needs a real natural drain. No image override or source ConfigMap is used.

The shared isolated renderer retains its fixed node, scoped credentials and at
most two renders. Its CPU request/limit are 500m/4 and memory request/limit are
512Mi/2Gi, with a matching bounded memory-admission ceiling and 256Mi headroom.
This provides headroom for the two reserved gateway slots rather than repeatedly
throttling Chromium behind a 1-CPU cap during an alert burst. Capacity was checked
on the existing socrat-1 owner; no placement, network, TLS or human auth changes.
The gateway's Telegram deadline must independently allow 15 seconds; extra CPU
or more bot retries alone is not a reliable substitute for fixing its old 4s cap.

The release component is deliberately lowercase `gateway`: the native v1 deploy
action rejects camelCase component names. The existing alertGraphs enable/policy/
credential controls remain unchanged; only the canonical image block is renamed.
