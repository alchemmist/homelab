# Local application dashboard icons

Most third-party product icons come from homarr-labs/dashboard-icons at the immutable revision in `sources.json`. Logos remain trademarks of their respective owners. Argo CD uses its official product mark from that pinned collection.

Wiki no longer uses BookStack artwork. Wiki uses the existing circular Socrat favicon from `deploy/litellm/branding/socrat-icon-v1.png` (2349×2349), downsampled to 512×512 PNG and embedded in a local SVG wrapper. The original artwork, circle and proportions are preserved; this is higher-resolution raster artwork, not a newly drawn vector logo. LiteLLM’s Authentik dashboard tile instead uses the **official LiteLLM monogram SVG**, copied unmodified from a pinned BerriAI/litellm revision recorded in `sources.json`. This is independent of the custom Socrat branding inside the LiteLLM application.

`icons.py` uploads versioned local files and patches **only** `meta_icon` for existing applications, including Argo CD even though its provider is managed outside the foundation catalog. It does not replace providers, launch URLs, policy bindings or group memberships. All nine current production application icons were fetched via Authentik's resolved media URL with trusted HTTPS and verified against their local SHA-256.

## Complete portal coverage — 7 November 2026

The reviewed Authentik inventory has21 applications. Twenty use these local,
checksum-pinned SVGs;3x-ui retains its independently managed branded PNG URL.
`applications` in each manifest entry maps one asset to existing application
slugs, including gateway aliases. Missing applications are skipped, never created.
NetBird, SearXNG, Syncthing and RustFS marks use the same immutable upstream
collection revision as the older service logos. The SPI evidence reader uses the
existing Socrat project icon. Hidden gateway entries remain hidden.

The icon-only helper takes a nonblocking local lock, validates all SVGs before
writes, saves a fresh private inventory, verifies served media bytes and checks
that all non-icon application fields remain unchanged. `--expected-inventory`
can pin a reviewed API inventory (including exact application UUIDs) for a live
change. A failed write/verification leaves `portal-icons-uncertain.json`; inspect
receipts and live state before any retry. Never clear that marker blindly.

Do not run the full Authentik deployment or provider/IAM reconciler just to change
icons. These metadata changes need no restart and grant no access. Re-running the
helper after current applications exist preserves the same alias icon mappings.
The earlier nine-icon verification above is historical, not the total inventory.

Live acceptance:11 missing icons assigned;21/21 existing applications now have
icons. Every application-resolved icon URL returned HTTPS200 and exact expected
SHA-256 (20 local SVG mappings plus unchanged3x-ui PNG). Application UUIDs,
providers, launch URLs, descriptions, visibility, group/policy metadata and other
non-icon API fields matched the private pre-change inventory. No restart,
provider reconciliation, new application, role or membership change was required.

Authentik serializes provider `property_mappings` M2M IDs in different orders on
list/detail reads. The helper normalizes ordering while comparing every member;
a changed member still blocks the operation. The first attempt stopped before
any application update on that ordering mismatch; full unchanged-state review
preceded marker archival and the successful metadata-only run. A separately
missing cached LMS asset was also caught during staging, before helper/API writes.
