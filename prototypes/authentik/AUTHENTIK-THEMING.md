# Prototype versus real Authentik theming

> **Production update — 2026-11-01:** approved Quiet Mono v5 is frozen in
> [`deploy/authentik/quiet-mono/reference/`](../../deploy/authentik/quiet-mono/reference/).
> Native production branding has now been applied; rollout/recovery are documented in
> [the production README](../../deploy/authentik/quiet-mono/README.md), with explicit
> [parity gaps and pending owner acceptance](../../deploy/authentik/quiet-mono/ACCEPTANCE.md).
> The “no cluster changes” statements below describe earlier prototype iterations only.


## Decision

Keep Authentik's own flow executor, stage components, locale selector and flow inspector. Theme them; do not replace authentication with these static HTML files or ship `quiet-mono.js` as an Authentik login implementation.

The HTML is a visual/interaction prototype. Its fabricated flow state is not an implementation of Authentik inspection or authorization.

## Verified implementation: 2026.8.5

Reviewed version-pinned upstream sources, rather than assuming the current `main` documentation applies:

- [Custom CSS documentation](https://github.com/goauthentik/authentik/blob/version/2026.8.5/website/docs/customize/branding/custom-css.mdx)
- [AKElement base component](https://github.com/goauthentik/authentik/blob/version/2026.8.5/web/src/elements/Base.ts)
- [Native FlowInspector](https://github.com/goauthentik/authentik/blob/version/2026.8.5/web/src/flow/inspector/FlowInspector.ts)
- [Brand settings overview](https://docs.goauthentik.io/brands/)

Authentik uses Lit web components and shadow DOM. Ordinary page CSS does not automatically pierce shadow DOM. The documented starting points are CSS variables and exposed/exported `::part` elements.

In this version, AKElement also constructs a stylesheet from `brand.brandingCustomCss` and applies it to its style root. This permits version-dependent internal-selector overrides. The source explicitly marks injected custom stylesheets as deprecated in favor of CSS parts/custom properties. This is not a reason to discard Brands CSS, but a warning against relying on arbitrary internal component markup across upgrades.

Native FlowInspector already:

- uses PatternFly's vertical ProgressStepper;
- renders successful history entries with `pf-m-success` and check-circle icons;
- distinguishes `pf-m-current pf-m-info` from `pf-m-pending`;
- shows next-stage metadata, expandable stage JSON and current plan context;
- loads data through Authentik's own inspection API and handles authorization/errors.

Therefore the green pipeline should be retained from native Authentik, not recreated as a separate production state machine. The sample stage sequence in the HTML is only a demonstrator; the real history can contain repeated stages and replanning and must not be reduced to a hard-coded five-step checklist.

## Feasibility boundary

| Element | Intended production approach |
| --- | --- |
| Logo, favicon, static photo | Native Brand settings. |
| Fonts, colors, glass surface, borders, spacing | Brand CSS with variables/parts first; test exact 2026.8.5 DOM and mobile layouts. |
| Native green/current/pending pipeline | Preserve native inspector; theme spacing, typography and surfaces. |
| Eye visibility toggle, language, stage transitions, consent | Preserve native component behavior. |
| Expanded node layout and snapshots in this mockup | Visual reference, not a promise of identical CSS-only reproduction. Prefer native stage/history data and controls. |
| JSON font, background, padding and scroll | CSS styling of native pre/code is feasible, subject to actual selectors. |
| JSON syntax tokens and Copy control | Native inspected source prints plain JSON text via JSON.stringify. CSS cannot tokenize it or add functioning buttons. Exact reproduction requires a component enhancement/patch or supported extension; not part of a CSS-only rollout. |
| Random photo selection | Separate asset-selection/cache design, not a new authentication frontend. |

Do not hide inspector API permission checks or expose real session context through a new public endpoint. Do not inject arbitrary browser scripts to imitate the prototype without an explicit implementation/security decision.

## Wiki code reuse in the prototype

- `assets/wiki-syntax.css`: exact copy of the Wiki's vendored hugo-content Chroma palette.
- `assets/fonts/cmu.typewriter-text-regular.woff2`: exact copy of the Wiki font.
- Background, radius, shadow and padding based on hugo-content `content.css` pre/code treatment; font sized to 14px desktop / 13px mobile, line-height 1.5 for inspection.
- JSON is tokenized locally into safe DOM text/span nodes using Chroma token classes. No JSON text is injected as HTML.
- Long lines scroll inside the code block rather than widening the drawer. Copy reports failure instead of falsely claiming success if browser clipboard access is unavailable.

No live Authentik changes, new API routes, component forks or frontend deployment were made for this prototype iteration.
