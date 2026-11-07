# Native browser authentication and public artifact previews

## Approved contract — 7 November 2026

No external Authentik Proxy Provider/MFA wrapper before application login.

- Native OIDC: Grafana, Harbor, Rancher, Open WebUI, Wiki, LiteLLM, LMS, Argo CD,
  NetBird and RustFS console. Preserve exact providers/clients/subjects/native roles.
- Native service login: n8n, Uptime Kuma admin,3x-ui and Syncthing GUI. No automatic
  user, password reset or role synchronization from Authentik. Existing IdP-only
  account suspensions (including antropophag/Umami) are not silently reversed.
- Explicit public exceptions: SearXNG and published SPI evidence artifacts.
- Additional domains are direct routes to the same service, not extra IdP apps.
- No new NetBird/internal-only access requirement for public browser services.

Technical `public-web-*`, n8n/xui proxy and RustFS console/evidence proxy
applications/providers must be retired, not merely hidden or renamed. Remove
outpost assignments before deleting only the reviewed exact application/provider
identities. Native OIDC apps, user/groups, machine credentials and application data
are not deletion targets. The managed embedded outpost can remain with zero proxy
assignments; it is not a duplicate user service.

## What remains an HTTP proxy, and why

Routing/presentation components are not authentication gateways: the Kuma public
status-only filter, Syncthing `/sync/` path adapter and gateway-only410, Grafana TV
presentation/password restrictions, Rancher native-password restrictions and the
RustFS routing-only console bridge remain. None performs external SSO. The RustFS
bridge preserves the existing edge watch namespace and avoids restarting the VPS
edge process. The direct3x-ui backend firewall stays: native HTTPS routing does
not require exposing an extra plaintext panel port.

Syncthing GUI had no native password and its old BasicAuth Secret was empty.
Native GUI credentials were established through its own config API before removing
the public wrapper. Machine API key and device/data config are preserved. Bootstrap
credential is private; never print it, commit it or use it to impersonate a human.

## Public evidence reader

`services/rustfs_gateway` remains a small read-only HTTP reader. Anonymous GET/HEAD
requires no cookie, IdP or signed/expiring URL. PUT/POST/PATCH/DELETE are denied;
there is no bucket listing or arbitrary upstream/path access. The S3 bucket itself
stays private, with a dedicated prefix-limited GetObject identity; console/admin
and writer credentials remain protected. Public links imply the artifacts are
approved for publication: redact private data/secrets before publishing, not after.

The reader verifies the manifest's content-addressed hash, event identity, exact
file membership, byte length and file hash before serving. Old ASCII
`socrat-evidence-v2`/`stored_chars` manifests remain compatible. The new optional
`socrat-evidence-v3`/`stored_bytes` format permits binary/UTF-8 artifacts; this does
not migrate the existing SPI publisher or replay any incident.

Preview allowlist: JSON, plain text/log/CSV/YAML, PDF, PNG/JPEG/GIF/WebP/AVIF,
MP4/WebM/Ogg video, MP3/Ogg/WAV audio. These receive the correct Content-Type and
`Content-Disposition: inline`; the browser provides its own minimal viewer.
Single byte-range GET and HEAD are supported. Active/unknown types (including
HTML, SVG and JavaScript) remain attachment/octet-stream; `nosniff` and restrictive
CSP prevent arbitrary uploaded code from becoming a web application.

Bounds remain explicit: max2MiB per upstream object, v2 text max90000 characters,
max8 concurrent requests and existing absolute/socket deadlines. Large videos,
resumable upload, streaming beyond these limits, transcoding and a full viewer UI
are not implemented. Increasing caps needs reviewed memory/storage/rate budgets.
A server header cannot force a new browser tab: the link owner controls target;
on GitHub, browser open-in-new-tab/Ctrl/Cmd-click applies. It no longer forces
supported files to download.

## Safe deployment order

1. Private pre-change IdP/routing snapshots and native-auth preflights. Preserve
   owner recovery, native service users, Secrets/PVCs and workflow history.
2. Stage only required namespace-local TLS copies; retain existing valid certs.
3. Git-owned direct routes and immutable reader image. RustFS is manual-sync:
   sync only that app/revision, no global root sync/prune. Native storage/pod
   templates, edge process, VPNs and databases must not restart.
4. Verify new endpoints ready; delete only exact-UID obsolete ingress/gateway
   objects left by prune=false. Then detach/delete reviewed proxy IdP objects.
5. Verify anonymous public reads and native API denials, unchanged OIDC identities,
   data/workloads and both public TLS entrances. Remove transitional rules only
   after the old route is gone. Record completed receipts; uncertain write means
   inspect/read back before retry, never blanket cleanup.

## Runtime receipt and bounded acceptance

IdP cleanup:11 obsolete apps,10 proxy providers deleted; all10 native OIDC apps,
provider/client data and non-owned policy bindings byte-equivalent after API
normalization. Users/groups/native service databases were not deletion targets.
Outposts remain but no proxy is assigned. Private before/after/progress receipts:
`/var/lib/homelab-native-auth-cutover/` (never publish their credential fields).

Nine legacy ingresses removed with exact ownership/UID guards. The old xui Argo
Application is gone; its ConfigMap/Service are gone. Its Deployment/Pod are already
terminating on socrat-2, whose Node is Unknown; normal GC awaits node recovery.
No forced Pod deletion or foreground-finalizer bypass was used.

135 scoped tests plus36 subtests passed before final CSP tightening. Isolated
Chrome synthetic v3 fixtures open JSON, PNG, WebM and PDF without download;
image/video decoded and the PDF page was visually inspected. PDF needs explicit
`object-src 'self'` in CSP; default-src none alone blocks its native viewer.
These are local handler/browser tests, not an independently published production
binary incident. Existing production text/manifest reads are checked separately.

Public entrance acceptance: HOME41/41; VPS41/41 fail TLS before HTTP. socrat-2
Node Unknown since17:04:42UTC; host k3s inactive, clean exit17:03:56UTC, and
public443 answers Caddy TLS internal_error. Cause/ownership is unproven; neither
Caddy nor k3s nor VPN was restarted. This prevents full public/SSO acceptance,
and must not be described as a completed healthy cluster cutover.

LiteLLM automatic sync initially queued a migration hook that never scheduled or
started. It was cancelled only after proving no container/node/startTime existed;
the native route was created from the exact Git render, with original Argo owner,
without running migrations or changing its workload/database. LiteLLM is now
Synced/Healthy. ApplyOutOfSyncOnly reduces applies but is not sufficient to skip
all hooks; route-only operations require explicit resource selection/apply strategy.

## Recovered VPS: final acceptance

The earlier blocked receipt above is historical and is superseded by this
recheck after operator-reported recovery (issue#103):

- Public native-access probe: **82/82 passed**,41 on HOME and41 on VPS, forced
  public addresses with ordinary certificate/SNI validation.
- All4 nodes Ready; socrat-2 Ready since2026-11-07T17:55:34Z. All8 affected Argo
  applications Synced/Healthy, including traefik-edge.
- The old xui gateway Application, Deployment, Service, ConfigMap and Pods are
  absent. All9 retired proxy-backed ingresses remain absent. No force-delete,
  finalizer bypass or service/VPN restart was needed during this recheck.
-10 native OIDC apps/providers and non-owned bindings match the post-retirement
  snapshot. Proxy Providers0; retired provider assignments remain detached.
  The only reviewed difference was computed meta_icon_url; stored meta_icon and
  all other compared identity fields match. No identities were mutated.
- Existing published artifact verified independently through both public
  entrances: anonymous GET/HEAD/206, manifest SHA-256 and artifact SHA-256,
  inline disposition, no cookie/redirect, four write methods return405.
- Private final receipt: recovered-vps-closeout.json under the existing private
  cutover directory. Never publish the credential-bearing source snapshots.

The local Chrome JSON/PNG/WebM/PDF fixtures and136 tests/36 subtests retain their
original scope. This closes the outage-dependent protocol/runtime retirement
acceptance, not independent-ISP or per-human login/MFA acceptance. No human was
impersonated and no new published incident artifact was uploaded for this test.
