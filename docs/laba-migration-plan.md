# Laba -> Socrat migration plan

Source VPS: `laba` (`176.98.185.59`).
Target cluster: `socrat` (`socrat-0`, `socrat-1`) behind `109.173.40.247`.

## Decisions

- Keep on VPS for now:
  - `vpn.alchemmist.xyz` / 3x-ui
  - `sync.alchemmist.xyz` / Syncthing
- Do not migrate:
  - `amnezia-awg2`
  - `mtproto`
  - `mail.alchemmist.xyz` (remove DNS/route)
- Rename `personal-site` target app to `blog`.
- Use GHCR for custom application images.
- `soft.alchemmist.xyz` is retired; do not migrate it.
- Project landing pages `lazy-tmux.xyz`, `devsyringe.xyz`, `obscuravim.xyz`, and `quality-graph.xyz` are separate domains, not part of `soft`.

## Current services

| App | Current containers | Domains | State | Repo | Target |
| --- | --- | --- | --- | --- | --- |
| blog | `moss`, Caddy static `/srv` | `alchemmist.xyz`, `www.alchemmist.xyz` | mostly static | `github.com/alchemmist/personal-site` | `charts/blog` |
| cats | `cats` | `cats.alchemmist.xyz` | stateless | image `alchemmist/cats:latest` | `charts/cats` |
| img proxy | Caddy reverse proxy | `img.alchemmist.xyz` | stateless | none | `charts/img-proxy` |
| redirects | Caddy redirects/respond | `www`, maybe old CV redirects | stateless | none | part of `blog` or `charts/redirects` |
| remark42 | `remark42` | `remark42.alchemmist.xyz` | `/srv/var`, custom CSS, OAuth/Telegram secrets | upstream image | `charts/remark42` |
| umami | `umami`, `umami-db` | `umami.alchemmist.xyz` | Postgres | upstream image | `charts/umami` |
| format-quorum | `format-quorum` | `fq.alchemmist.xyz` | PVCs for versions/tests/config history; configs bind | `github.com/alchemmist/format-quorum` | `charts/format-quorum` |
| lms | `lms` | `lms.alchemmist.xyz` | `/data` volume | `github.com/alchemmist/lms` | `charts/lms` |
| monori | `monori`, `monori-back`, `monori-sync` | `monori.alchemmist.xyz` | SQLite/data + sync debug | `github.com/alchemmist/monori` | `charts/monori` |
| rooms | not currently running | `rooms.alchemmist.xyz` | Postgres if enabled | `github.com/alchemmist/rooms` | decide later |

## Migration waves

1. Stateless:
   - `cats`
   - `img-proxy`
   - redirects / simple static endpoints
2. Blog:
   - build/publish `blog` image to GHCR
   - migrate Caddy cache headers/redirects
3. Small state:
   - `lms`
   - `format-quorum`
4. Data services:
   - `remark42`
   - `umami` with `pg_dump`/restore
5. Complex:
   - `monori`
6. Optional:
   - `rooms`

## DNS cutover

Move migrated records from `176.98.185.59` to `109.173.40.247`.

Keep on VPS:
- `vpn.alchemmist.xyz`
- `sync.alchemmist.xyz`

Remove:
- `mail.alchemmist.xyz`
- `soft.alchemmist.xyz`
- `devsyringe.alchemmist.xyz` if the canonical domain is only `devsyringe.xyz`

Do not use wildcard blindly while `vpn` and `sync` remain on VPS.
