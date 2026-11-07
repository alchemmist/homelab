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
