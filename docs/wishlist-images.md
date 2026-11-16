# Wishlist images

Private Sharp/libvips binary POST adapter, shipped with the Wishlist image. Enable
`images.enabled` only after the checked image includes `/opt/image-optimizer`.
Do not reuse the public `img-proxy`: that service forwards to external weserv.
Master WebP is full-resolution/lossless; preview <=480×960 is a display derivative,
not the zoom original. JPEG conversion can increase size. ICC retained, EXIF
orientation applied and metadata removed; GIF/WebP animation/alpha tested.

Optimizer Deployment has no credentials/PVC, non-root/read-only rootfs + temporary
scratch, no service-account token and no egress. ClusterIP8081 accepts only exact
same-namespace Wishlist Pod labels. No ingress/NodePort; same checked image digest.
All photo uploads fan out immediately; native CPU/transport/cgroup limits remain.
Optimizer2GiB memory isolation protects the SQLite app; failures are retryable,
no silent unoptimized fallback. Web app memory budget should be512MiB while the
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
