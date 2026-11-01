# Local application dashboard icons

Third-party product icons come from homarr-labs/dashboard-icons at the immutable revision in `sources.json`. Logos remain trademarks of their respective owners. Argo CD uses its official product mark from that pinned collection.

Wiki no longer uses BookStack artwork. Wiki and LiteLLM use the existing circular Socrat favicon from `deploy/litellm/branding/socrat-icon-v1.png` (2349×2349), downsampled to 512×512 PNG and embedded in a local SVG wrapper. The original artwork, circle and proportions are preserved; this is higher-resolution raster artwork, not a newly drawn vector logo. LiteLLM already uses this supplied artwork as its own favicon.

`icons.py` uploads versioned local files and patches **only** `meta_icon` for existing applications, including Argo CD even though its provider is managed outside the foundation catalog. It does not replace providers, launch URLs, policy bindings or group memberships. All nine current production application icons were fetched via Authentik's resolved media URL with trusted HTTPS and verified against their local SHA-256.
