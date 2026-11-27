# Authentik login wallpapers: gallery, RustFS and responsive delivery

**To change the login background set**, open [the gallery](https://auth.socrat.alchemmist.xyz/wallpapers/), sign in as an owner or wallpaper manager, and toggle a tile. There is no theme release or ConfigMap update. Turning a picture off removes it from future selections; it does not repaint an already-open login page or revoke a downloaded image. Only upload photos suitable for public display.

## Who owns what

| Component | Responsibility |
| --- | --- |
| Authentik Brand / quiet-mono | Imports `/wallpapers/scene.css`. The Brand neither picks a photo nor limits its resolution. |
| `identity/authwall` | Same-origin gallery, owner API, public scene selection and media streaming. [Application and UI](../../../services/authwall/) live in homelab. |
| `pg-common` / `authentik_wallpapers` | One row per photo: ID, filename, active flag, processing state, dimensions, error and n8n execution link. Not an image store. |
| RustFS / `authentik-wallpapers` (persistent bucket) | Original bytes, rendered WebPs and per-photo variant index. Private S3 access; no browser bucket credentials or listing. Not the SPI evidence gateway or RustFS admin console. |
| `automation/n8n` | One [workflow](../../../services/authwall/n8n/derivatives-v2.json) per upload. The execution link is for tracing; acceptance of the webhook is **not** proof that files exist. |

**Access boundary.** The owner UI/API checks the Authentik session via `/api/v3/core/users/me/` (`homelab-owner`, `homelab-owners` or `app-authwall-manager`); the group lookup is cached for 60 seconds. Anonymous gallery navigation starts SSO with `next=/wallpapers/`. The login page cannot require SSO to paint itself: `scene.css` and derivative media URLs are intentionally public. Inactive is a selection flag, not an access control. Originals have no public source route. Internal processing uses `X-Wallpaper-Token`, not a browser session.

**Delegate gallery management:** in Authentik Admin → Directory → Groups, open `app-authwall-manager`, then add or remove the user under Users. This grants upload, activation and permanent deletion of any gallery photo, not Authentik administration. Membership changes can take up to 60 seconds to reach the gallery. Do not add users to `homelab-owner` for this purpose.

## From upload to ready

1. Upload or paste a file. The app stores the unchanged source and records processing state. The gallery shows a local object URL immediately rather than waiting for a network round trip.
2. The app calls `authwall-derivatives` with an ID and 300-second signed URLs (one original GET, two derivative PUTs). n8n returns its execution link immediately. Do not log or paste signed URLs or tokens into tickets.
3. The preview branch uses n8n Edit Image / GraphicsMagick on the original. The full branch calls the app’s token-protected `/authwall/internal/lossless`: Pillow reads the original, writes sharp responsive variants and their index to RustFS, and returns the full WebP. n8n stores the full and preview outputs via the signed PUTs. These branches **do not** derive one image from another compressed output. No extra image-processing deployment is needed. The [network policy](../../../services/authwall/n8n/rustfs-access.yaml) admits n8n to RustFS S3 port 9000, not console port 9001.
4. The app records the execution URL, polls the two output keys (type/size), and marks the row `ready` only after both exist; failures/timeouts are not eligible for login. Without a webhook the app can process locally; local development uses SQLite/directory storage, not the production DB/bucket.

| Bucket key | Contents and reason |
| --- | --- |
| `sources/{id}` | Exact uploaded bytes; use these for rebuilds. An imported 1920 px source has no recoverable higher resolution. |
| `optimized/{id}.webp` | Full native resolution. Existing WebP passes through unchanged; other supported still images are encoded losslessly after decoding/orientation handling. This preserves decoded detail, not lost JPEG detail or every source metadata field. |
| `thumbs/{id}.webp` | Fast first paint: at most 640 px on the long side, slight blur (`sigma=0.4`), quality 62. Never use the thumbnail as input for a sharp render. |
| `responsive/{id}/w{width}.webp` | Sharp proportional resizes from the original using Lanczos, lossless WebP encoding. Candidate widths 480, 768, 1280, 1920, 2560; skip widths at or above source width. Resizing reduces detail; encoding adds no further lossy compression. |
| `responsive/{id}/s{width}.webp` | For landscape sources, centered square crops for portrait screens: avoid transferring side pixels that `cover` would hide. Also keep a native-size square. |
| `responsive/{id}/index.json` | Actual variant tags and pixel dimensions, written after the variants. The scene uses this list, not assumed URLs. |

## What a browser downloads

`scene.css` selects **one active, ready ID per request** (neutral background if none). The stylesheet is `no-store`; it includes the thumb inline beneath the sharp background, so there is no second request for the initial placeholder. CSS media queries choose a sharp URL using viewport **width, height and device pixel ratio**. A narrow high-density screen does not necessarily get the smallest file. `background-size: cover` preserves proportions. The native frame is the fallback; a screen served a smaller sharp variant does **not** download the full file afterwards.

The owner grid selects for the **tile**, not the viewport. A new item starts with its local preview, existing items with their blur. Sharp downloads start only when ready, with bounded concurrency, timeouts and retries. A separate sharp layer appears after decoding; the blur stays behind it. Tiles toggle on click; only inactive images darken. Desktop and mobile share the English UI; mobile uses two columns and a bottom upload queue. Permanent deletion is a separate two-click action; leaving the control cancels confirmation. Deletion is intended to remove the row and associated objects; do not treat it as instant eviction from browser caches.

`/wallpapers/media/` streams RustFS responses in 64 KiB chunks and permits public caching for one day. Streaming improves **time to first byte**, not the number of bytes to download or decode. Scene choices stay fresh independently of file caching. Replacing bytes under an existing ID can leave cached old media until expiry.

## How we got here

- The original Nature theme packaged dotfiles derivatives in ConfigMaps and selected images at the legacy nginx `/-/quiet-mono/v1/nature/scene.css`. The 30 Nature photos were seeded into the gallery. Merely setting active flags did nothing while the live Brand still imported the old picker. Both the live Brand and [branding source](../../../ansible/roles/authentik/files/branding.py) were switched to the gallery stylesheet. Historical Nature assets/checks are not the current picker.
- The first n8n workflow only acknowledged uploads while the app did the work. Its live webhook was retired after real n8n executions were verified: 35 photos were rebuilt into staging keys, decoded and checked before replacing the previous derivatives. Originals and active flags were preserved. Do not restore the retired placeholder workflow.
- A 48 px thumbnail was too vague, and removing it before sharp decode caused gray flashes. A recognizable 640 px preview and separate decoded layer fixed those two different problems. The old full-image limit (1920 px, quality 80) was ours, not Authentik’s. We removed it and compared decoded pixels against all 31 then-current sources. Counts here describe different inventory snapshots, not an expected gallery size.
- Full-size lossless alone made some downloads much heavier. Precomputing 202 responsive variants for those 31 photos moved resizing off the request path. On `les-priroda-derevia-8.jpg`, the 1920 px file still weighed 3.36 MB and the native file 7.02 MB. Streaming instead of buffering the whole object reduced measured first byte for the 1920 px file from about 7 s to 0.76 s; total transfer was still about 4 s. These are individual measurements, not latency guarantees.

## Operator checks and recovery

- **Wrong photo:** inspect the live Brand import and the anonymous login response. Check DB `active` **and** `ready`; loading public media directly does not prove the picker selected it. With one eligible photo, repeated CSS requests should reference only that ID across all size variants.
- **Stuck upload:** follow its n8n execution; check original GET, internal lossless call, both PUTs, S3 connectivity and signed URL expiry. Inspect content type, size and decoded dimensions. A successful initial webhook response is insufficient.
- **Slow/shallow image:** inspect the *actual URL* requested in browser Network, viewport/DPR, cache state, bytes, TTFB and transfer time. Compare a tile with the login background separately. A quick first byte is not a decoded sharp image. For a public probe (no cookies required):

  ```sh
  base=https://auth.socrat.alchemmist.xyz
  curl -fsS -D /tmp/scene.headers "$base/wallpapers/scene.css" -o /tmp/scene.css
  # Use the exact media path seen in Network, not the inline thumbnail:
  curl -fsS -o /dev/null -w 'status=%{http_code} first=%{time_starttransfer} total=%{time_total} bytes=%{size_download}\n' "$base/wallpapers/media/<id>-w1920.webp"
  ```

- **Rebuild/restore:** preserve DB IDs, flags and originals together. Render from `sources/`, verify staged type/dimensions and bytes before replacement, record execution links, then remove staging objects. Never publish the bucket or grant console access to fix a media error. Keep credentials out of Git; verify bucket-scoped credentials rather than assuming historical bootstrap credentials were scoped.
- **Redeployment caveat:** the initial deployment and Brand cutover included live changes. The checked-in chart is not sufficient evidence of production parity. Compare live image, ingress, secrets by reference, policies, workflow and Brand before reinstalling. Do not reapply the retired workflow or legacy Nature import as a routine recovery step.
