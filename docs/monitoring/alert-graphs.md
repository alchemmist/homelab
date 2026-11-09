# Alert graph mapping and release gate

`python3 scripts/alert_graphs.py --check` verifies the generated inventory,
annotation values, reviewed gateway panel policy and diagnostic dashboards.
The current source set is196 rules:189 Prometheus rules and7 Grafana-managed
rules,184 distinct mappings,28 dashboards. Array order is priority: Telegram
uses the first panel; SPI collects every declared panel. Diagnostic primary
panels remove root numeric filters so healthy/near-threshold samples are visible;
a second panel retains the exact triggering expression. Logical operands and
full series labels remain visible. Rule expressions, labels, routing and current
thresholds are unchanged. These are rule-scoped panels, not a false promise that
aggregation can reconstruct a lost per-instance label.

Prometheus owners consume generated override values through the existing Argo
Applications. Grafana-managed rule JSON still requires the existing authenticated
provisioning procedure; checked-in JSON does not assert a live API update.
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

## Live reconciliation receipt

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
