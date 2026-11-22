# Final handoff: prepared Loki retention repair blocked by GitHub

**Not deployed. Not full logging/retention acceptance.** [Coverage registry/report](coverage-final-2026-11-04.md) and [operator guide](operator-guide.md) are preserved in local commits.

## Confirmed live defect and bounded owner fix

Loki3.7.9 retention fails `failed to create marker writer: open /tmp/<numeric>: read-only file system`. Retention lane observed failure11, last-success timestamp0; historical failures must not be hidden. Loki remains ready and serving ingestion; readiness does not imply working retention.

Prepared fix: `charts/otel-backends/templates/backends.yaml`, **Loki only**, disk-backed `emptyDir` mount `/tmp`, sizeLimit1Gi. Preserves RO root, nonroot uid/gid10001, mTLS, persistent data/compactor paths, retention policy and Tempo unchanged. Pinned [upstream v3.7.9 marker.go](https://github.com/grafana/loki/blob/v3.7.9/pkg/compactor/retention/marker.go#L60-L109) creates scratch BoltDB under `os.TempDir`, closes it and uploads completed marker to the durable object client before removing scratch. No cross-filesystem rename dependency. Final markers/working state remain persistent; scratch is transient. No manual marker/data deletion is authorized. Enabling already-configured retention is intentional; durations are not changed.

Validation: Helm lint/render passed; one rendered-chart security/mount regression test passed;39 logging tests passed including three new aligned-reconciliation regressions. Live **pinned** Loki binary `-config.file=/etc/otel/loki.yaml -config.expand-env=true -verify-config=true` reported valid. Retention lane's disposable pinned test with writable scratch completed retention passes, but actual shipped-chunk expiration/deletion remained unproven; no claimed enforcement proof.

## Exact Git blocker / commits

- Local substantive commit `7f029efc4182435ae367630caba2293a837cd606`; formatting follow-up `1ba3f16`.
- SSH fetch failed `Permission denied(publickey)`. Explicit supervisor approval permitted existing authenticated HTTPS gh credential helper per command, without changing origin/global credentials or printing tokens.
- HTTPS fetch succeeded. Concurrent remote `8f1c597` and `1f20269` changed SPI chart/wiki only; reviewed and preserved via clean rebase.
- First normal HTTPS push rejected server **Internal Server Error**, request `E2B5:9370A:4ADF647:68DE1B3:6AEB058E`,2026-11-04 10:14:39Z.
- Supervisor authorized exactly one retry after fresh remote inspection/tests. Second push rejected **Internal Server Error**, request `E2F7:29F255:4C4A406:6A9B690:6AEB05C4`,10:15:33Z.
- Final read-only remote HEAD still **`1f20269c49e2b8c6cc0fdf3337060b23917fbcd1`**. No force push, API bypass, credential change, manual deployment drift or self-heal disable. Further pushes/deployments stopped per supervisor.
- Final Argo `otel-backends`: same remote revision, **Synced / Healthy**. Deployments Loki1/1 and Tempo1/1. The scratch fix is therefore **not live**; no post-fix retention success gate can be claimed.

## Resume gates, not completed actions

After normal upstream push works, refresh Argo and sync only Loki Deployment through its owning application; verify rendered Tempo unchanged. Observe readiness/ingestion and draining bounded log queues through expected Recreate downtime. Require fresh retention successful-run timestamp, positive success counter and clean new failure delta; preserve historical11 failures. Physical deletion/capacity enforcement requires longer independent acceptance and the configured2h delete delay; never manually delete to accelerate it.

LMS update was explicitly authorized only **after retention repair accepted**. Since that prerequisite is blocked, no LMS pin/deployment was performed. Requested build `b0bb95f85d3903357162079c0d12827a6e6976b8`, digest `sha256:fa4dba61583f116da5300594a334ba8f0d40141728a121777ee64f691ffd2b5c` remains pending fresh owner/current-image review to avoid downgrading newer work. Bot remains held by parent. No app/DB/auth/model changes were made in this lane.
