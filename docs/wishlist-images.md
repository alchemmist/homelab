# Wishlist images

Private Sharp/libvips binary POST adapter, shipped with the Wishlist image. Enable
`images.enabled` only after the checked image includes `/opt/image-optimizer`.
Do not reuse the public `img-proxy`: that service forwards to external weserv.
Master WebP is full-resolution/lossless; preview <=480×960 is a display derivative,
not the zoom original. Preview is WebP q90/alpha100; master remains pixel-lossless.
Preview URLs/S3 keys use a version so old lossless previews cannot pin oversized
bytes in immutable browser caches. Optimizer resources use sync-wave-1: same-node
image pull/readiness completes before Recreate of the SQLite app (wave0). JPEG conversion can increase size. ICC retained, EXIF
orientation applied and metadata removed; GIF/WebP animation/alpha tested.

Optimizer Deployment has no credentials/PVC, non-root/read-only rootfs + temporary
scratch, no service-account token and no egress. ClusterIP8081 accepts only exact
same-namespace Wishlist Pod labels. No ingress/NodePort; same checked image digest.
All photo uploads fan out immediately; native CPU/transport/cgroup limits remain.
Optimizer2GiB memory/4GiB scratch isolation protects the SQLite app; failures are retryable,
no silent unoptimized fallback. A prefix-scoped postStart hook removes only
its own interrupted scratch jobs after container restarts; no PVC/account data. Web app memory budget should be512MiB while the
pipeline is enabled. Existing data claim and client certificate stay untouched.

On upload, master+preview persist in S3. On reads, atomic disk cache (toward1GiB,
oversized active entry/concurrent writes can exceed it temporarily) serves immutable
Content-Length/ETag/ranges. Existing originals/DB are never rewritten/deleted:
legacy preview is generated on demand, cache-only. Cache mounts `/data/media-cache` on a separate2GiB emptyDir, NOT the1GiB
SQLite PVC; cache pressure must not fill the authoritative DB volume. Cache is
disposable, NOT backup
or authoritative user data; never delete the database/WAL to clear media cache.

Spans: image.optimize.master/preview, numeric in/out bytes and engine milliseconds,
storage.open, s3.download + bytes, media.cache + hit, media.prepare. Browser
image.load/decode and upload receive timing. Shared sampler/privacy are unchanged.
Research evidence (16photo Save17.076s; per-file S3put0.287–3.570s; media slow
streaming) is in Wishlist AUDIT.md; not a claim all delay is storage or a throughput
benchmark. Live delivery and rendering acceptance must be recorded after enabling.

## Live acceptance — 2026-11-16

Application1e5e35b, Quality43935991777 and release43936660784(attempt2) successful:
77pytest +160browser checks; native codec contracts and audit clean. Transient
Harbor TLS handshake timeout required rerun; no TLS bypass/credential changes.
Both checked-digest Deployments Ready. Actual private RPC→lossless master/q90
preview→S3 write/read→cleanup tested with synthetic pixels (1200×1800 master,
480×720 preview, exact decoded master pixels); retained14-span Tempo trace
`f8ce472228afc6e7a4bd2f3d921322c7`. Deliberate2.1s retention delay in probe is NOT
a latency benchmark. Grafana MCP confirms Collector up1; browser image spans
previously retained in123-span trace with exact Loki correlation.

Additive one-time backfill persisted **53 v2 preview objects** in S3; original
objects/DB keys untouched. Source bytes46,193,502 vs previews2,025,542 (~22.8×
less for browsing all53); no authenticated session or real gift mutation. New
anonymous Chromium client:53/53 HTTP200,53/53 slides decoded/selected, zero master
network requests, all media network responseEnd~1.80s, first three covers~0.54s.
Earlier forced empty server cache: first three~1.94s, all53 successful using
durable S3 previews. Times are local measurements, not a network-independent SLA.

Cache is disposable, derivatives now durable: a later app restart need not
re-read/re-encode those legacy originals. Normal read-time legacy generation
remains cache-only if a missing derivative is encountered. Original format
snapshot:36PNG/10WebP/7JPEG. The user’s real16-photo Save was researched but NOT
replayed under the owner’s identity; new receive/engine/bytes/cache spans expose
future bottlenecks. Original upload bandwidth is not reduced by server conversion.

Initial rollout exposed Recreate image-pull downtime; fixed via optimizer wave-1
(image on same node before web wave0). Do not claim zero-downtime SQLite HA.
Historical extraneous ConfigMap/wishlist remains OutOfSync/not pruned. Both actual
Deployments, private service/policy, resource limits, isolated scratch/cache and
end-to-end payload/telemetry delivery independently checked. Structured evidence:
`deploy/monitoring/migration-evidence/wishlist-images-20261116.json`.
