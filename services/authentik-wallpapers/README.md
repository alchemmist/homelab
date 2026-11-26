# Authentik wallpapers

Gallery at `https://auth.socrat.alchemmist.xyz/wallpapers`. Active pictures are the login background set. Sources live in RustFS, rows live in `pg-common`, and each upload asks n8n to build the WebP pair.

## Objects

Bucket `authentik-wallpapers`:

- `sources/{id}` — original, only for processing
- `optimized/{id}.webp` — resized to 1920, WebP quality 80, no EXIF
- `thumbs/{id}.webp` — 48px blurred preview

`GET /wallpapers/scene.css` picks one active ready picture. The response is `no-store`. It stacks the optimized URL over an inline copy of the thumb, which is the same first-paint idea as the old Nature CSS. Point Authentik's `__ASSET_NATURE_SCENE__` at `https://auth.socrat.alchemmist.xyz/wallpapers/scene.css`.

## UI

Same page type as Wishlist: Georgia on white, Files and Paste, Ctrl/⌘V on the picker. The left card lists each file while n8n is still processing and slides away after every item is ready. The gallery is a grid. Click a tile to mark it active or off. Only active ready pictures enter the random login choice.

## Runtime

| Env | Role |
| --- | --- |
| `DATABASE_URL` | `pg-common` database `authentik_wallpapers`, verify-full |
| `RUSTFS_ENDPOINT`, `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`, `WALLPAPER_BUCKET` | bucket writes |
| `N8N_WEBHOOK_URL` | `https://n8n.socrat.alchemmist.xyz/webhook/authentik-wallpaper` |
| `WALLPAPER_JOB_TOKEN` | shared by the webhook caller and `POST /wallpapers/internal/optimize` |
| `WALLPAPER_AUTH` | `on` by default. The gallery, its script and `/api` ask Authentik. Only `homelab-owner` (and the same people if the group is spelled `homelab-owners`) may enter. Login `scene.css` and `/media` stay public so the sign-in page can paint a background before anyone is signed in. |

Without `N8N_WEBHOOK_URL` the process optimizes in a background thread. That is the local path. Import `n8n/workflow.json` and set the webhook before production uploads.

Postgres network policy on `pg-common` must allow this workload, the same way Wishlist and Monori are allowed. Create the database and login role before the first boot. The app creates its table.

```sh
cd services/authentik-wallpapers && PYTHONPATH=src python3 -m unittest discover -s tests -v
```
