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
- [ ] Random photo collection/selection. Production uses the approved sample lake photo; the owner's final collection is not yet supplied.

## Scope and rollout boundaries

This does not complete the wider cluster human-auth migration, owner-only legacy fallback enforcement, HA, DR or historical kubeconfig rotation. Those remain separate work.

The local WireGuard/private gateway route currently presents an untrusted certificate for this hostname. Tests used process-local resolution to the two trusted public edges with TLS/SNI verification intact. No DNS, WireGuard, private gateway or certificate settings were changed as part of branding.

## Owner revision: language picker (2026-11-01)

The owner requested English-only UI and no language picker. Production CSS now hides the flow locale selector, including keyboard access; Brand default remains `en`. The approved reference is unchanged. This supersedes the visible language-selector requirement above.

Important native limitation: a previously selected locale in `sessionStorage["authentik:locale"]` or an explicit `?locale=` can override the Brand default. Hiding the picker does not clear client storage or force existing sessions to English. Strict enforcement for those cases is not implemented by this CSS change; no user attributes, browser storage, authentication frontend or permission checks were changed.

## Owner revision: transition title

Both native provider authorization flows now use the literal title **Redirecting** instead of `Redirecting to %(app)s`. The observed transient screen exposed this raw Python-style placeholder. This is fixed in native flow metadata, not by hiding the heading or substituting CSS text. Consent, spinner, executor, stage bindings and authorization remain unchanged. `flow_titles.py` saves the original titles privately and supports rollback; the branding playbook applies it explicitly.
