# Wishlist: five interactive design studies

Preview: `python3 -m http.server 18765 --bind 127.0.0.1 --directory prototypes/wishlist`
Open http://127.0.0.1:18765/. No dependencies, no external fonts or analytics.
These files are not connected to the deployed Helm chart. No production deployment yet.

## Directions
1. Folio: narrow reading column, monochrome, serif prose and monospace titles; closest to the blog.
2. Queue: dark monospace, compact tabular rows; technical tool aesthetic.
3. Blueprint: cobalt on coordinate grid, two-column illustrated technical cards.
4. Cabinet: warm paper, italic serif, staggered three-column collection.
5. Orbit: oversized sans-serif, asymmetric two-column list, circular sketches and orange accent.

All share demo data and browser-local storage so the same gifts can be compared. Guest filters, reservation with a public text mark, owner add/edit form and owner release are implemented. Demo owner mode is NOT authentication. Guest release is available for reservations created in the current page session only. No real cross-device reservations. Photos are not implemented: illustrations are placeholders. Reset is destructive only to local demo data.

## Next phase: backend design contract (proposed, not implemented)
- Public catalog and public reservation marks. Explicit notice not to enter personal information or passwords.
- Text mark is an attribution label, never authentication. Global uniqueness of marks is not needed; the gift is what must have at most one active reservation.
- Reservation transaction in SQLite with unique gift_id; simultaneous claims return 409 and UI displays 'Someone just reserved this gift; choose another'. Never silently overwrite.
- Server issues random cancellation capability; only hash stored in DB. Browser receives secure token / link separately from public mark. Losing token requires owner assistance. Owner can release any reservation.
- Owner-only authenticated /admin; server authorization on every mutation. Add/edit/archive, manual ordering, title, description, price label, category, shop URL, photo upload + preview. No code/Git/agent required for content updates.
- Confirm destructive actions, show submitting/success/error states, preserve form on errors. Disable duplicate submission. Fetch fresh reservation state before showing success; refresh public list periodically.
- Server validates lengths, URL protocols and uploads; render public marks as text. Rate limit anonymous reservation attempts; CSRF protections for cookie-authenticated operations. No arbitrary remote URL fetching for product previews.
- SQLite on one writer instance with persistent storage and tested backups (do not use two independent SQLite copies behind current two nginx replicas).
- Suggested entities: gifts(id, title, description, price_label, category, link, image_key, rank, archived_at); reservations(gift_id UNIQUE, public_mark, cancellation_token_hash, created_at).

## Verification performed
- `node --check prototypes/wishlist/app.js`.
- Viewed all five desktop variants in Playwright.
- All five at 390px: document width equals viewport, four sample gifts rendered.
- Browser form smoke test: reserve gift, see mark, enter owner mode, add gift, see five cards, both dialogs close on success. Removed test browser storage afterwards.

## 06 / Pixel (additional reference study)
Reference: https://ru.pinterest.com/pin/1079104760730137038/ (Dgrees.studio).
Uses the pin's still image as composition reference: off-white field, fine divider, small technical labels, large sans-serif text and central pixel artwork. Original SVG gift replaces the reference cherries; subtle CSS glitch is an interpretation, not a reconstruction of the original animation. Motion disabled with prefers-reduced-motion.
Link: `concept.html?theme=pixel`. Existing shared forms and local demo storage retained. Desktop (1440px) and mobile (390px) inspected; mobile document width 390px, four gifts rendered. JS syntax check passed. No production deployment.

## 07 / Atlas
User-provided Sequel reference: deep blue, cream serif text, subtle grain and engraved landscape. Adapted to a wishlist rather than copying the shop footer. Original procedural SVG landscape in `landscape.svg`, with a small wayfarer silhouette. All UI in English; gift content unchanged. Shared reservation and owner forms retained. Desktop 1440px and mobile 390px visually inspected; JavaScript syntax check passed. Local prototype only.
