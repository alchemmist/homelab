# Public foundation live — 2026-11-06; human acceptance pending

SPI remains OFF/unchanged. This is not full foundation acceptance.

External network fix 1591b02757e69f9822755271b2e0adae853b51e4 preserved all
user NetBird/Mac/VPN changes. Parent rechecked 24/24 unrelated-pod connections
blocked across four nodes, Service/Pod ports9000/9001, health and fixture paths;
its probe pods removed. Parent independently verified deployed Reader S3 exact
45-byte fixture/hash. These parent results are distinct from this phase's tests.

Reviewed Root App drift: unrelated Rancher Application only; did NOT sync Root.
Own manual prune=false sync at1591b02 then activation62f48606f590e2b896b2979dfcc5f7b621b8a91a.
Only tracked activation change browserRoutes=true. Authentik dedicated reconciler
ran idempotently, validating existing exact owner/platform app bindings, callbacks,
provider settings and additive outpost assignment. No human/group/role edits.
Private verified preactivation resource snapshot retained under operator home
.config/homelab/rustfs-foundation/public-20261106/resources-before.json
SHA256 8d29faee9c08638d2952c20c3f8f32b3ff04876e0a24b76c6d54cde2482dddc4;
previous private credentials, journals and consistent SQLite backup retained.
No credentials copied into Git. Storage rollout unchanged, retained PVC/PV.

Observed Argo Synced/Healthy/Succeeded at activation revision; manual sync, prune
false. identity/rustfs-browser-tls cert-manager Ready true at10:31:11Z.
Both real entrances109.173.40.247 and109.120.141.97 verified HTTPS with correct
SNI and trusted certificate (curl ssl_verify_result0), no insecure bypass.
Console anonymous302 fixed same-host outpost start, evidence anonymous401 fixed
HTTPS authenticate Link. Both entrances forged owner/group headers, encoded dot
path, doubled slash, query and direct admin path all401; no identity bypass.
Reader pod DNS Authentik resolves exactly both addresses; real discovery HTTPS200;
arbitrary1.1.1.1:443 connect_ex111 denied. Source/live authEgressCIDRs exact two/32.
Actual Authentik server pod reaches console9001: /rustfs/console/ HTML200;
root / is RustFS AccessDenied403, not a useful console landing page.
Raw S3 stays private ClusterIP; browser routes only protected identity namespace.

## Required human acceptance (parent browser profile busy)

Use ordinary authorized browser, existing owner/platform identity and MFA:
1. Open https://rustfs.socrat.alchemmist.xyz/rustfs/console/ ; complete outer
   Authentik gate, then choose native OIDC login. Verify callback, native signed
   identity/session or STS and actual permitted read-only behavior. Proxy login
   alone does not prove native login. GetOnly policy does not promise listing.
2. Open evidence login:
   https://spi-evidence.socrat.alchemmist.xyz/outpost.goauthentik.io/start?rd=https%3A%2F%2Fspi-evidence.socrat.alchemmist.xyz%2F
   Then download:
   https://spi-evidence.socrat.alchemmist.xyz/spi/v1/fd215d418e9e00b4cbabe0cb1cb54f6eeb4a93c148e3bc46b15c43992861b998/001dc076d5ac5decb3e908ec4e9e746c56f7b0efa582be42a60f4a639ce1da01/E001-fixture.json
   Expected45bytes, SHA256
   973952a7d502a67bc652d5b67f104d0d6c1756bb4edb713e682e40f1b68e34f0.
   Independently hash downloaded file; do not send cookies/tokens to operator.
3. Verify logout/session behavior and existing unaffiliated-user rejection if
   such an authorized identity is available. Do not create/grant broad test users.

No real human MFA, native callback/signed-token/STS, authenticated browser download,
outsider-user or logout/revocation proof obtained. Prior native discovery and
PKCE/strict callback authorize302 machine evidence remains in live-foundation-
20261105.md; not equivalent to completed human flow. Parent MCP profile busy;
no profile hijack, alternate browser CLI, borrowed cookies or synthetic token.

## Rollback / durability

Commit browserRoutes=false and manually sync only RustFS prune=false; this removes
public activation intent but prune-OFF leaves ingress resources, so explicitly
remove only rustfs-authentik-browser and rustfs-evidence-browser ingresses if
withdrawing routes. Reconcile source before another sync. Do not delete PVC/PV/
StorageClass or private journals/keys. Existing rollback runbook can scale only
own deployments after coordinating GitOps. No shared edge/CNI/DNS/user changes.
Standalone socrat-0, Retain20Gi request is not quota/HA/independent backup. No SPI
switch until actual foundation acceptance; preserve all original n8n state.
