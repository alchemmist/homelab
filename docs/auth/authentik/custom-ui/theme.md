# Theme ownership, CSS and form controls

## 1. What runs in production

**Quiet Mono v5**: full-screen nature photo, light semi-transparent matte panel,
the real Socrat mask, the exact Wiki favicon, CourierCyr UI and bold Computer
Modern for headings. No marketing panels/greetings. Production uses a fixed
agreed lake; the random owner photo collection is not implemented.

The browser keeps **native Authentik 2026.8.5**:

- `ak-flow-executor` executes server challenges;
- native identification/password, TOTP/validation, consent and redirect stages;
- `ak-flow-card` draws the card;
- `ak-flow-inspector-button` / `ak-flow-inspector` — the stock debug controls;
- `ak-drawer#flow-drawer` — the stock non-modal panel.

Our login JS does not replace the executor and does not check passwords. Do not
copy `quiet-mono.js` from the demo into production: it contains only synthetic
offline navigation/MFA. It is not an OIDC client or middleware and must never
receive real secrets.

## 2. File map and ownership

| Path | Purpose |
|---|---|
| `prototypes/authentik/01-frost.html` … `05-typewriter.html` | Historical visual variants; v5 chosen |
| `prototypes/authentik/05-consent.html`, shared CSS/JS | Offline demo, not backend auth |
| `deploy/authentik/quiet-mono/reference/` | Frozen approved reference; manifest sizes/SHA-256 |
| `deploy/authentik/quiet-mono/theme.css` | Production native Brand CSS |
| `deploy/authentik/quiet-mono/assets.json` | Reviewed asset names, paths, digests |
| `deploy/authentik/quiet-mono/static-image.json` | Digest-pinned nginx provenance |
| `deploy/authentik/quiet-mono/README.md`, `ACCEPTANCE.md` | Rollout/rollback, parity, measured checks |
| `ansible/roles/authentik/files/branding.py` | Brand/native presentation reconciliation + private backups |
| `ansible/roles/authentik/files/branding_static.py` | Deterministic isolated static Kubernetes resources |
| `ansible/roles/authentik/files/flow_titles.py` | Neutral authorization titles, separate guarded rollback |
| `ansible/playbooks/authentik-branding.yml` | Explicit prepare/apply/rollback, no IdP upgrade/restart |
| `scripts/identity-branding-controls-check.py` | Read-only real native component CSS probe |
| `scripts/identity-branding-smoke.py` | Real temporary observer MFA/OIDC roundtrip |
| `tests/test_authentik_branding.py`, `test_authentik_flow_titles.py` | Offline regression/security contracts |

Do not edit the frozen reference to disguise production limitations. A new
owner revision is produced separately with a description of the differences.
The old “no cluster changes” phrases in the prototypes refer to the historical
stage before rollout.

## 3. Where the actual theme config lives

A domain-specific Brand `auth.socrat.alchemmist.xyz`, not a blanket
replacement of the default Brand for all domains. `branding_custom_css`
contains the rendered `theme.css`. The Brand also sets logo/favicon/background
and light/en defaults. These fields live in the Authentik DB; the file in Git
is the reproducible source, but the commit itself does not change the DB.

Native presentation changes beyond CSS:

1. `default-authentication-flow` title — `Sign in`.
2. Identification uses the already existing default Password Stage: username
   and password in one native form, without a new authentication backend.
3. Native allow-show-password is enabled; the eye works via stock code.
4. Explicit/implicit authorization flow title — the literal `Redirecting`.
5. MFA/consent bindings and their permissions were not weakened for styling.

For the identification PATCH, this version requires `user_fields`; do not
assume an empty minimal payload is universally valid. DRF trims CSS
whitespace, so the reconciler normalizes with `.strip()` for real idempotency.

## 4. Shadow DOM: why plain CSS sometimes does not work

Lit components have separate shadow roots. A selector from the document does
not penetrate arbitrarily into `ak-stage-*`. Authentik's AKElement applies
Brand CSS to its own components; that is why `:host(ak-stage-consent)` works
inside the corresponding root, and `:host([part='challenge'])` — in the native
challenge stage.

Examples of working scopes:

```css
:host(ak-flow-executor) .pf-c-login__main { /* panel */ }
:host(ak-flow-card) h1 { /* native heading */ }
:host([part='challenge']) input.pf-c-form-control { /* fields */ }
:host([part='challenge']) :is(button,a.pf-c-button).pf-m-primary { /* primary */ }
:host(ak-flow-inspector-button) button.inspector-toggle { /* magnifier */ }
ak-drawer#flow-drawer::part(drawer-panel) { /* exported part */ }
```

`ak-drawer` is **a plain LitElement, not an AKElement**. Its private root does
not receive Brand CSS in the usual way. It uses the external exported parts:
`drawer-content`, `drawer-panel`, `drawer-main`, `drawer-body`. Do not add a
random deep selector and do not claim success without a computed
style/geometry check.

Some selectors are version-specific; after an upgrade, check the real
DOM/source, not just the saved screenshot. `!important` here deliberately
overrides native component rules, but new overrides should be limited to a
specific host/part, not the whole UI.

## 5. Field and primary-action contract

- Fields have a simple border; hover/focus/Tab add no outline/glow.
- Validation is preserved: invalid input gets an error border, not a permanent
  “clean” look.
- The eye button is a native control inside the input group, not a decorative
  picture.
- Primary: transparent background, dark text, thin border, Courier, arrow.
- Hover: ink tint **4.5%**, arrow **3px / 160ms**, no dark/light inversion.
- `prefers-reduced-motion` disables the motion. The browser may serialize the
  alpha with rounding to 8-bit; do not rewrite CSS `.045` because of a single
  computed RGB string.
- `Follow redirect` is an **anchor**, not a button; `:is(button,a.pf-c-button)`
  covers both. Previously, due to a button-only selector, this link stayed blue
  with poor contrast.
- Keyboard/ARIA/events were not replaced. The magnifier has a separate
  focus-visible indicator; the “no focus glow” requirement for text inputs
  does not forbid a visible focus on the button.

Do not style by English text match alone: translation/dynamic labels change
the text, while the component/class contract stays. Do not hide real
validation messages.
