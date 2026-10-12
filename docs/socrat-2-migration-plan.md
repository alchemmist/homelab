# Socrat-2 migration plan

Source VPS, now `socrat-2` (`176.98.185.59`).
Target cluster: `Socrat` (`socrat-0`, `socrat-1`) behind `109.173.40.247`.

## Decisions

- Keep on VPS:
  - `vpn.alchemmist.xyz` / 3x-ui
- Migrated to Socrat/k3s:
  - `sync.alchemmist.xyz` / Syncthing
  - `remark42.alchemmist.xyz` / Remark42
  - `umami.alchemmist.xyz` / Umami
  - `monori.alchemmist.xyz` / Monori
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
| remark42 | stopped on `socrat-2`; `remark42` in k3s | `remark42.alchemmist.xyz` | `/srv/var`, custom CSS, OAuth/GitHub secrets in K8s Secret | upstream image | `charts/remark42` |
| umami | stopped on `socrat-2`; `umami`, `umami-db` in k3s | `umami.alchemmist.xyz` | Postgres restored from `pg_dump` | upstream image | `charts/umami` |
| format-quorum | `format-quorum` | `fq.alchemmist.xyz` | PVCs for versions/tests/config history; configs bind | `github.com/alchemmist/format-quorum` | `charts/format-quorum` |
| lms | `lms` | `lms.alchemmist.xyz` | `/data` volume | `github.com/alchemmist/lms` | `charts/lms` |
| monori | stopped on `socrat-2`; `monori`, `monori-back`, `monori-sync` in k3s | `monori.alchemmist.xyz` | SQLite/data + sync debug | `github.com/alchemmist/monori` | `charts/monori` |
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
   - `syncthing`
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

Remove:
- `mail.alchemmist.xyz`
- `soft.alchemmist.xyz`
- `devsyringe.alchemmist.xyz` if the canonical domain is only `devsyringe.xyz`

Do not use wildcard blindly while `vpn` and `sync` remain on VPS.

## 3x-ui / VPN Kubernetes migration status

- `socrat-2` has been joined to the k3s cluster over WireGuard (`wg-socrat`, node IP `10.250.0.2`).
- ServiceLB is explicitly enabled only on `socrat-0` and `socrat-1`; it is disabled on `socrat-2` so existing Caddy/VPN ports on the VPS are not taken by Traefik.
- Host administration on `socrat-2` is through `alchemmist`; legacy `www` user and `/home/www` were removed. The remaining Caddy container mounts `/srv/caddy/Caddyfile`.
- Offline backup before the attempted cutover:
  - `/root/backups/x-ui-20261012133959`
- A parallel containerized 3x-ui lab/prod-candidate is running as Helm release `x-ui-lab` in namespace `x-ui-lab`, pinned to `socrat-2`.
- Native `x-ui.service` still runs production traffic on the old ports for already-configured clients.
- Caddy now routes subscription paths to the containerized instance (`172.18.0.1:12096`), so refreshed clients receive the new container-backed ports:
  - VLESS: `32053`, `32083`, `32063`, `32084`
  - WireGuard: `32085/udp`
  - AmneziaWG: `32086/udp`
  - Trojan WS container port: `32087`, exposed to clients through Caddy on `vpn.alchemmist.xyz:443` path `/connect-4e15326936f20a7a4f2cac67`
- The initial lab issue was caused by `hosts` overrides in the 3x-ui DB forcing Trojan subscriptions back to production `443/tls` while Caddy still proxied that path to native x-ui. Fixed by routing Caddy's Trojan path to container port `32087` and keeping the subscription override as `443/tls` for clients that cannot use high ports.
- All enabled clients are also attached to the containerized Trojan inbound, so every refreshed subscription has at least one compatibility profile on `vpn.alchemmist.xyz:443`.
- Do not stop native `x-ui.service` until all important clients have refreshed their subscriptions and moved off old non-Trojan ports.
