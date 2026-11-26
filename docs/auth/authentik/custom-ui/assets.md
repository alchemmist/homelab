# Static assets, icons and backgrounds

## 6. Static files without expiring URLs

The first signed media URLs of Authentik proved unusable for persistent CSS:
the JWT signature expires. A Brand must not store such a URL as a permanent
background/font. A same-origin endpoint is used instead:

```text
https://auth.socrat.alchemmist.xyz/-/quiet-mono/v1/<sha256-prefix>-<filename>
```

`branding.py` verifies each asset's local digest, builds content-hashed URLs,
checks the served bytes over HTTPS and replaces the `__ASSET_*__` placeholders.
If a hash does not match or a placeholder remains, apply must not continue.

`branding_static.py` creates the immutable ConfigMap, the sandboxed nginx
Deployment, the Service and the prefix-only Ingress. Only reviewed `.webp`,
`.svg`, `.woff2`; GET/HEAD, `nosniff`, a one-year immutable cache. No JS login
bundle, no arbitrary `/data` or private backup directory. API/token/login paths
keep being served by the IdP.

Nginx: the digest is pinned in `static-image.json`, non-root, read-only FS, no
SA token, no escalation/capabilities, a limited `/tmp`, requests 5m/16Mi, limits
100m/64Mi. The TLS Secret `authentik-tls` is shared for the domain;
ingress priority/prefix isolate the static files. This is not HA and not a
justification for accessing the Kubernetes API from the auth server.

Kubernetes apply specifics, already fixed:

- the client-side last-applied annotation for a binary ConfigMap exceeded
  256KiB: **server-side apply** with a dedicated field manager is used;
- `kind: List` led to an unavailable OpenAPI-v2 fallback: the CLI emits
  **separate JSON-as-YAML documents**, and strict OpenAPI-v3 validation is kept;
- do not add `--validate=false` as a workaround for these errors.

When replacing an asset the bytes, SHA and URL change; do not overwrite the old
immutable URL. Check the reasonable bundle size (renderer guard 900000 bytes)
and the mobile image. Clean up old ConfigMaps/resources separately after
acceptance, not during a rollback.

## 7. Application dashboard icons — a separate layer

The source is `assets/service-icons/`; the manifest `sources.json` holds
URL/revision, SHA/provenance/license; the README explains derivation. This is
not the favicon of all Authentik. `icons.py` uploads pinned assets and changes
only the `meta_icon` of existing apps; it does not touch
providers/policies/launch URLs, including Argo CD outside the foundation
registry.

Argo CD uses the official pinned `homarr-labs/dashboard-icons` icon. The wiki no
longer uses BookStack artwork: the original round Socrat from
`deploy/litellm/branding/socrat-icon-v1.png` (2349px) was downsized to 512px and
packed into an SVG with an embedded PNG, without redrawing. After the owner's
refinement, LiteLLM uses the official product monogram SVG from a pinned
BerriAI/litellm revision in the dashboard; the round Socrat stays with the wiki.
The login logo is a separate mask; Authentik's favicon is the exact wiki SVG.

All nine current app icons were verified through the permitted media URL:
HTTPS200 and matching byte digests. For media URLs request a fresh native
resolved URL; do not store its signed query in Git. Do not “clean” checksum-
sensitive line endings with a global formatter: `.gitattributes` preserves the
needed asset bytes.

> **Current login backgrounds:** see the [wallpaper gallery and RustFS runbook](../../../applications/authentik-wallpapers/README.md). The Nature picker and its acceptance receipts below are historical, not the live selection path.

## 14. Random backgrounds from the Nature dotfiles

As of 2026-11-01 the owner provided `~/code/dotfiles/wallpapers/nature/images`:
30 JPEGs (~40MiB, width up to 5120px). The source repository is not changed;
the actual SHA256 of every original, the Git revision and the Pillow version are
recorded in `deploy/authentik/quiet-mono/nature.json`. This is provenance, not a
transfer of copyright on the original photos. Production uses only the derived
WebPs.

```sh
python3 scripts/build-authentik-nature.py --source ~/code/dotfiles
```

Pillow with WebP support is required. EXIF/ICC metadata is not carried over.
Desktop long edge <=1920, mobile <=960; quality usually 80, lowered to 68 when
the file budget is exceeded. A local build does not deploy. `assets.json` holds
the digests of all 67 assets: 7 original reference assets and 60 Nature
derivatives. `reference/` remains frozen.

Nginx `split_clients "$request_id"` picks one of 30 IDs with almost equal
probability. `/-/quiet-mono/v1/nature/desktop` and `/mobile` return **the WebP
itself, HTTP200**: GET/HEAD only, `Content-Type: image/webp`,
`Cache-Control: no-store`, `nosniff`. `X-Quiet-Mono-Scene` is the photo's public
ID for verification, not a user/session identifier. These are exact locations
with an alias from a closed manifest map: no arbitrary path, JS, external CDN,
user cookie, IP-based tracking or auth logic. The ordinary hash URLs remain
immutable. CSS switches to the mobile endpoint at width <=700px.

During a single SPA flow there is no timer/change of the visible background. A
new document load selects anew (repeats are possible). Crossing the
desktop/mobile breakpoint can also select a different photo. The native initial
background and drawer can issue separate image requests; this is not a promise
of a single HTTP request for the whole document.

The static files are laid out into content-hashed immutable ConfigMaps, each
<950KB serialized; the Pod sees one read-only projected volume. The overall
reviewed budget is 16MB. The playbook transfers the source as a single temporary
tar (owner-only unpack) instead of dozens of SSH/stat operations, and renders
the separate resource documents into a protected remote file, not a huge Ansible
stdout/stdin variable. Server-side apply and strict validation are preserved.
Only the static Deployment restarts on a new content digest; Authentik and the
shared ingress do not restart.

Application is the standard `authentik-branding.yml` with an explicit `apply`.
The protected pre-Nature snapshot `nature-before-20261101.json` was kept; the
routine Brand journal contains an applicable guarded pre-change backup. Return
to the previous lake CSS goes through that backup, not through the initial
pre-branding baseline (that would cancel the whole theme). Do not print the
snapshot/journal and do not delete old ConfigMaps during a rollback.

Checks: 30 original/60 derivative hashes, bounded objects, nginx syntax, the
full playbook apply; live desktop1440/mobile390 on both edges, reviewed response
bytes, no-store, stability after loading, zero JS errors. In 12 samples from
each edge, 11 distinct scenes appeared — that is evidence, not a guarantee of no
repeats. `python3 scripts/identity-nature-smoke.py --run` repeats the anonymous
live checks without password/MFA/fixtures, screenshots or saved session data.
No actual owner MFA roundtrip was performed in this change. The API comparison
showed only a Brand CSS/background change; OAuth providers, policy/flow
bindings and MFA validate settings stayed as they were. Argo refresh/VPS rollout
is not affected by this playbook.




## 15. Nature optimization: preview → sharp photo (2026-11-02)

The previous §14 describes the **historical first implementation**. The scheme
as of this stage removes two separate full background requests and caches
everything except the scene choice, not the big photos themselves.

- An early `@import /-/quiet-mono/v1/nature/scene.css`, `no-store`, picks one
  of the 30 reviewed IDs via the nginx request_id (historically; the selection
  was fixed in §16). No IP tracking and no authentication JS were added.
- The response of <=2481B contains an inline WebP preview of 124–300B **of the
  same photo** and links to SHA-pinned AVIF/WebP. A CSS layered background draws
  the preview under the HQ. No separate thumbnail download, foreign random frame
  or waiting for HQ before the native login. After loading, the background is
  static; the breakpoint changes the size, not the photo ID.
- AVIF <=1920/960: median 78,370B desktop / 22,289B mobile instead of
  WebP159,250B / 49,560B. All 30 originals and 60 WebP fallbacks preserved; 60
  AVIFs and 30 checksum-pinned scene CSS files added. The old source/derivative
  hashes are preserved.
- Big photos get `public,max-age=31536000,immutable`; a re-selected picture is
  served from the browser cache (verified transferSize=0). A new document
  selects a scene again; a repeat is acceptable. The compatibility
  `/nature/desktop|mobile` are now no-store 302s to an immutable asset,
  Accept/AVIF negotiation and a GET/HEAD403 guard.
- The single background is the native `body::before`; the drawer is
  transparent. The native default background-prefetch points to a transparent
  62B immutable SVG, not a second photo. This is a presentation field, not a
  replacement of flow/authentication code.

On both public edges, desktop1440/mobile390 were verified: exactly one scene
stylesheet and one HQ image, correct sizes, same-photo preview, caching,
hashes, random sampling, POST403, WebP fallback, native login and the absence
of JS errors/slideshow. HQ was delayed in a separate browser-only test by 5
seconds: the preview is visible and the native login fields usable. The photos
and metadata were prepared offline; the Pillow/libavif versions are in
`nature.json`.

Test: `python3 scripts/identity-nature-smoke.py --run`. No real owner
login/recovery was emulated. The protected API comparison confirmed changes
**only in Brand CSS/background**, not providers/policies/MFA. Only the static
Deployment restarted, several times while verifying the approach; Authentik/
ingress/DNS/WireGuard were not changed. No promise of zero delay until the first
network response; a neutral fallback remains for network errors. Rollback — the
guarded immediately pre-performance Brand backup, not the initial baseline. Do
not delete old immutable CMs on rollback.


## 16. Plan History without nested scrolling

At the owner's request, the 22rem/18rem limits of the native progress-stepper
were removed. `max-block-size:none;max-height:none;overflow:visible`: the list
takes its natural height on desktop/mobile; scrolling stays with the inspector,
not inside Plan History. This cancels the earlier presentation decision about
bounded history scrolling but does not change the data, order, repetitions or
access rights. Both public edges were verified at 1440/390px via a local empty
layout box inside the native component; the owner's real history was not
substituted or extracted. Only the Brand CSS changed, without restarts.


## 16. A stable background for the whole OIDC journey (2026-11-03)

The cause of rare jumps: `split_clients "$request_id"` picked a new photo on
every import of `scene.css`. Inside the SPA everything looked stable, but a
full redirect/reload created a new document and a new random selection. Two
identical anonymous flow URLs with an unchanged `next` reproduced the photo
change.

Now the selection is not per-document:

- Only a same-origin Referer `/if/flow/.../?next=...` with the OIDC `state`
  gives the seed. While the encoded `next` stays unchanged, `split_clients`
  returns the same ID regardless of request_id, stage/flow slug, native auth
  session changes, cookies and reloads. A new OIDC state selects anew from all
  30 photos; independent selections can coincide. We do not change the OIDC
  state: this is only a read-only presentation selection.
- On server errors and transitions without `next`, the previous ID is taken
  from the separate host-only `__Secure-qm_nature`. Only 30 allowlisted IDs, no
  arbitrary path. Secure/HttpOnly/SameSite=Lax; Path=/-/quiet-mono/v1/;
  Max-Age=1800. The cookie is updated only by the selector endpoints'
  responses, not by the immutable pictures. Its content is the photo's public
  ID, not a user UUID, callback, bearer or session token.
- For direct/native login without a unique OIDC context, or with the Referer
  removed, the static-only endpoint **cannot see the exact login/logout
  boundary**. The honest fallback here is 30 minutes since the last selector
  request, not a promise of a new photo per Login click. The priority is not
  changing the background within the current journey. Different tabs with
  different OIDC next have an independent stable seed; the fallback without next
  shares the browser's cosmetic cookie. The cookie is not an auth mechanism.
- No custom authentication JS, HTML injection, IP/UA fingerprinting, changes to
  Authentik cookies, policies, token lifetimes or MFA. Raw next/state are not
  stored in new cookies/headers/journals; the static files' access_log is off.
- Still one same-photo inline preview + one cacheable HQ, no slideshow.
  `scene.css` is no-store; Vary: Cookie, Referer. The legacy selectors also
  preserve the ID.

Application is limited to a new immutable nginx ConfigMap and a guarded
replacement of only
`Deployment/socrat-authentik-theme.spec.template.spec.volumes[config].configMap.name`.
The old ConfigMap is preserved; a private 0600 backup contains the previous
Deployment/config. UID/resourceVersion/old config were checked before the PATCH.
The other identity Deployment specs and Authentik pods' UIDs matched
before/after. Authentik API writes:0. Rollback is a guarded return of **this
config volume** to the previous ConfigMap from the private backup; not a general
Authentik/Traefik rollback and not the old pre-Nature Brand rollback. For a
reproducible reconcile use the branding playbook with action=prepare: only the
public static bundle is updated, without Brand/flow/provider/MFA API writes.

`identity-nature-smoke.py --run` on both entrances, desktop1440/mobile390:
native login reload×3 → native server error400 → return to the same flow; a
neighboring OIDC tab does not change the first; repeated CSS requests and a
flow slug change are stable; new synthetic OIDC journeys give variety. These
are anonymous layout/network checks, not an impersonation of the owner and not
a personal end-to-end MFA acceptance. Also verified: the scoped cookie, GET/HEAD,
POST403, WebP fallback, hashes, image-cache transferSize=0; the preview-only
login is usable while holding the HQ back for 5 seconds. An isolated unexposed
canary in front of production checked the nginx syntax, absent/foreign referer
and the absence of rotation across ten identical requests; the canary was
removed.


## User avatars — November 7, 2026

The owner and antropophag get stock Gravatar URLs by email hash, without
custom avatar attributes. This is not a Google login import and not a
restoration of a deleted identity. The same email gives the same avatar.
External browser requests and the local-initials option:
[current identity status](../operations/identity-current-state.md#avatars).
Initials were not enabled in production by this update.

## Icons for all existing applications — November 7, 2026

Authentik has 21 applications: the 11 missing icons were added, including
NetBird, LMS, RustFS, search, Syncthing and service aliases. 20 entries use
local checksum-pinned SVGs; 3x-ui kept its own branded PNG. The manifest
`assets/service-icons/sources.json` ties one asset to several exact slugs via
`applications`. The SPI evidence uses the existing Socrat icon.

All 21 resolved URLs were verified: HTTPS200 and the expected SHA256. The PATCH
changed only `meta_icon`; UUIDs, providers, URLs, visibility and other non-icon
application fields were preserved. Hidden gateway entries were not exposed, no
roles/groups granted, no applications created, no restarts. This is an API/media
verification, not a visual acceptance of all cards in a real human session.

To reapply — only `ansible/roles/authentik/files/icons.py`, not a full
Authentik/IAM rollout. The helper uses a lock, a private backup, SVG/media
checksum verification and exact before/after checks; with an uncertain marker,
reconcile first. The order of provider property-mapping M2M IDs is normalized;
the memberships themselves are compared in full.
[Assets/receipt contract](../../../../assets/service-icons/README.md).
