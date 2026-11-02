# Quiet Mono v5 — approved design and production acceptance

## Immutable reference

The owner approved the fifth prototype, including its final non-modal inspector and magnifier toggle. The preserved reference is `reference/05-typewriter.html` and `reference/05-consent.html`. `reference/manifest.json` records every reference file's SHA-256 and size. Do not silently update that directory to match implementation limitations. Evolve production CSS separately and record gaps below.

## Design contract

- Full-viewport natural photograph, `cover`, no marketing panels or greetings. Light theme.
- One off-white translucent matte pane: `rgba(255,254,250,.86)`, 18px blur, 3px radius, quiet shadow. Reference widths: sign-in 354px, consent 388px. Responsive margins; no horizontal overflow.
- Existing Socrat mask, without distorted proportions. Exact existing Wiki square SVG favicon.
- CourierCyr for UI; only principal headings use Computer Modern Bold, 31px/1.12. JSON uses the Wiki's Computer Modern Typewriter and light code treatment.
- Neutral `Sign in` heading. Username/password, native error messages and MFA must remain clear. Do not introduce welcome/back-again copy.
- No extra focus outline/glow on input; keep the existing border and caret. Validation errors remain distinguishable.
- Main action remains outlined. Fine-pointer hover: 4.5% ink wash and 3px arrow movement, 160ms, no inversion. Other controls stay quiet.
- Password reveal works and its eye changes. Language selection works; default English, Russian available (native additional languages may remain).
- Inspector is non-modal: no dark overlay, no inert login, no Tab trap or scroll lock. Form and MFA remain usable. Magnifier toggles open/closed; close and Escape remain available through native behavior.
- Wide-screen drawer: 600px, synchronized 180ms crisp slide/content shift; no spring or opacity/blur animation. Reduced motion disables movement. Narrow layouts must not cover the login form.
- Inspector preserves actual native plan history, including repeated/replanned stages: green completed steps, visible current step and pending steps; expandable stage object and current context. Do not substitute a fabricated checklist for real production data.
- Sensitive inspection remains subject to Authentik permissions. Never make it publicly accessible merely to reproduce the anonymous prototype's toolbar.
- No authentication frontend rewrite, email-based account linking, password reset, MFA weakening, new human privilege grants or browser redirects on machine endpoints.

## Production status (2026-11-01)

Implemented through a domain-specific Brand, native presentation settings and a separate static-only asset route:

- [x] Native sign-in and consent styled with the approved fonts, mask, favicon, matte panel and optimized same-origin nature photo.
- [x] Desktop/mobile layout, field focus, subtle action hover, native eye and locale selection checked on both trusted public edges.
- [x] Native combined identification/password form uses the existing default Password Stage and its unchanged authentication backends. Existing MFA validation remains mandatory and was exercised.
- [x] Password + real temporary TOTP enrollment + consent + Grafana OIDC completed in a real browser; observer not server admin; fixtures removed.
- [x] Native drawer geometry locally exercised without changing permissions: 600px panel, 300px card shift on 1440px, no inert form; no fake server-side inspection data.
- [x] Immutable asset URLs have no expiring media tokens; checksums checked after public HTTPS fetch; static server is non-root, read-only, digest-pinned, without service-account token.
- [x] Original display configuration saved privately; replay reports no changes when reconciled. IdP pods were not restarted.
- [ ] Owner's authenticated visual acceptance of native inspector/history and application-specific consent screens. Do not mark complete using a temporary elevated/owner account.
- [ ] Native JSON syntax highlighting and Copy equivalent to Wiki. Current native JSON gets the Wiki code font/surface, but remains plain JSON; CSS cannot tokenize text or add functioning Copy controls. Needs separately reviewed component work if still desired.
- [ ] Exact wording/glyph parity: native `Log in`, `Email or Username`, password placeholder, native locale/eye glyphs and recovery controls are retained rather than hidden/replaced with inaccessible CSS text.
- [ ] Native inspector toggle/close/Escape and responsive history acceptance by the real owner; no access-control bypass was added to test it anonymously.
- [x] Owner Nature collection: all 30 dotfiles photos, desktop/mobile WebP, server-side random selection without new JS/cookies; both-edge 1440/390 checks and stable loaded page passed. Frozen reference retained.

## Scope and rollout boundaries

This does not complete the wider cluster human-auth migration, owner-only legacy fallback enforcement, HA, DR or historical kubeconfig rotation. Those remain separate work.

The local WireGuard/private gateway route currently presents an untrusted certificate for this hostname. Tests used process-local resolution to the two trusted public edges with TLS/SNI verification intact. No DNS, WireGuard, private gateway or certificate settings were changed as part of branding.

## Owner revision: language picker (2026-11-01)

The owner requested English-only UI and no language picker. Production CSS now hides the flow locale selector, including keyboard access; Brand default remains `en`. The approved reference is unchanged. This supersedes the visible language-selector requirement above.

Important native limitation: a previously selected locale in `sessionStorage["authentik:locale"]` or an explicit `?locale=` can override the Brand default. Hiding the picker does not clear client storage or force existing sessions to English. Strict enforcement for those cases is not implemented by this CSS change; no user attributes, browser storage, authentication frontend or permission checks were changed.

## Owner revision: transition title

Both native provider authorization flows now use the literal title **Redirecting** instead of `Redirecting to %(app)s`. The observed transient screen exposed this raw Python-style placeholder. This is fixed in native flow metadata, not by hiding the heading or substituting CSS text. Consent, spinner, executor, stage bindings and authorization remain unchanged. `flow_titles.py` saves the original titles privately and supports rollback; the branding playbook applies it explicitly.

## Native owner-saved pages: inspector history and Follow redirect

The two owner-saved pages remain private in Downloads and are not publication
assets. Structural inspection found 28 rendered progress items: in the consent
page, 26 completed entries (13 consent/final-stage pairs), one current consent
and one pending final stage; in the redirect page all 28 are completed. These are
native stage snapshots, not synthetic prototype records or 28 distinct checks
for one LiteLLM login. Individual prior authorizations/apps cannot be identified
from the repeated labels alone.

Pinned upstream 2026.8.5 evidence:
- `authentik/flows/views/executor.py`: `stage_ok` appends a deep copy of the plan
  to session history; cancellation intentionally preserves history.
- `authentik/flows/planner.py`: provider authorization can install a new plan
  before the executor runs, bypassing its no-plan history reset.
- `authentik/flows/views/inspector.py`: reads session snapshots filtered by shared
  flow UUID, not by application or a particular authorization attempt.
- `web/src/flow/inspector/FlowInspector.ts`: maps the received plans directly;
  inspector refresh replaces state rather than concatenating generated entries.
- `web/src/flow/stages/RedirectStage.ts`: opening the native inspector deliberately
  pauses automatic navigation and renders an **anchor** labeled Follow redirect.
  That prompt is a debug aid, not an additional normal SSO consent requirement.

Presentation corrections: shared primary-action rules now cover native button
and anchor actions, including arrow/hover/reduced motion. The native magnifier
has a 39px square target, centered 18px CSS SVG mask, and fixed viewport offsets
24px desktop / 17px mobile. Real ARIA labels, events and authorization are retained.
History remains chronological and complete, within a 22rem (mobile 18rem) scroll
region; no deduplication, truncation or hiding of entries. No document scroll lock.

Saved DOMs were inspected in a network-restricted, script-disabled local browser;
private context/callback text was removed from the transient visual preview only.
Saved HTML does not preserve all adopted shadow stylesheets, so it is not treated
as a production-rendering acceptance test. Actual native controls are separately
checked by `scripts/identity-branding-controls-check.py --run` (Playwright required).
That probe uses a fresh anonymous browser, requires inspector API denial, and uses
a clearly local-only redirect challenge with a blocked benign `.invalid` target.
It does not simulate owner authorization or substitute native production history.


Production control checks passed on both trusted public edges at desktop 1440px
and mobile 390px: exact corner offsets / centered icon; real native anchor
transparent background, dark readable text, 43px height, Courier and arrow;
4.5% configured hover tint and 3px arrow motion; reduced-motion handling;
keyboard focus and native click handler with blocked probe navigation. Inspector
API remains denied to the anonymous probe. Actual magnifier visual inspection
found no distortion or CSP image-policy violation. No owner session was acquired
or permissions granted for those checks. Owner separately confirmed real LiteLLM
SSO success; this does not assert an owner recovery-password test.


## Nature performance revision — 2026-11-02

Both public edges (109.173.40.247 and 176.98.185.59), desktop1440/mobile390:
exactly one reviewed no-store scene stylesheet and one HQ AVIF; inline same-photo
preview; no desktop image on mobile; pinned response hashes; immutable HQ and
browser-cache reuse with transferSize=0; native login visible, zero JS errors,
no timed photo changes. Sampling returned 12/12 and 10/12 distinct scenes;
POST403 and pinned WebP compatibility fallback passed. Full collection has
30 photos, 120 HQ derivatives and 30 scene stylesheets; original reference untouched.

Median AVIF sizes: desktop 78,403B, mobile 22,623B. Preview124–300B; scene CSS
max2,481B. In a deliberately delayed HQ test (5 seconds), native login was usable
with the correct preview before HQ completion; actual anonymous screenshots were
visually reviewed. This is not a global network latency/SLA or owner MFA claim.

One cold probe: scene CSS completed at659ms, first paint712ms, HQ completed918ms;
other both-edge samples took119–287ms for HQ transfer after request start. Timings
are samples, not a claim every original/optimized random photo is comparable.

API before/after comparison: only Brand CSS/default background changed, not
providers, policy bindings or authenticator validation. IdP and shared ingress
were not restarted. Several static-only rollouts were used while refining the
single-background approach. Empty native background was rejected by the API
(and safely rolled back); a checksum-pinned transparent SVG is used instead.
Read-only native control tests also passed. No new authentication JavaScript.
