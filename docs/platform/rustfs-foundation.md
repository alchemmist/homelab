---
title: RustFS foundation (source only)
---

Current runtime: RustFS foundation is deployed through `charts/rustfs` and
`values-foundation-live.yaml`; source defaults alone are not its live state.
The7 November browser cutover removes Authentik proxy gates: console keeps native
OIDC; published evidence is anonymous GET/HEAD with safe inline preview and
manifest/hash verification. S3 itself stays private. See
[the current browser contract](../identity/native-browser-auth.md).

The historical source-only notes below describe the original staging phase,
not a claim that production is inactive. Where they mention an external proxy
or authenticated reader, the current contract above supersedes that admission.
Read `docs/rustfs/activation-checklist.md` for real provisioning, private input
formats, phase order, IAM/SSO/TLS/download tests and rollback; official release
and Authentik semantics are recorded in `docs/rustfs/foundation-review.md`.

The source pins official RustFS 1.0.4 by digest, retained socrat-0 standalone
20Gi storage, nonroot runtime/probes/resource bounds/network isolation. Root keys
are only for storage/private operator bootstrap. Separate writer/reader SigV4
users have exact private spi/v1 prefix policies, never root. Writer is not mounted
into SPI or enabled in this phase.

Humans use existing Authentik owner/platform authorization. Whole-console proxy
admission plus native confidential RustFS OIDC (PKCE S256/client_secret_post,
fixed callback, explicit read-only policy claim) is configured separately from
machine keys. No public raw S3 or ungated console/root-login route exists.

The authenticated read-only artifact reader serves
`https://spi-evidence.socrat.alchemmist.xyz/spi/v1/<event64hex>/<manifest64hex>/...`
as bounded exact-byte attachments, checks manifest and artifact SHA256, rejects
unsafe keys/queries/encodings/redirects and never trusts browser identity headers.
Evidence uses Authentik forward_single, not the console's full-proxy mode.
Anonymous requests return 401 with a fixed authenticate Link; establish an
Authentik evidence session first, then reopen the deterministic file link.

Private idempotent provisioning tools do not modify existing users/roles or
memberships. No secret RBAC/ConfigMaps, image push, IdP/cluster mutation or browser
login was performed by this source change. Offline tests are not runtime proof.
The reader image still needs an approved build/digest and the full activation
checklist, actual session and IAM tests must pass before any SPI switch.

Single-node Retain local storage is **not HA or independent backup**. Requested
local-path capacity is **not an enforced filesystem quota**. Existing n8n IDs,
credentials/PVC/encryption key, calendar, blog write-disabled state, historical
comments and queued jobs remain untouched. No fake incidents or publication tests.

## Public continuation 2026-11-06

Protected public entrances are now deployed with valid cert-manager TLS on both
public IPs. Network isolation recheck passed after external NetBird fix. Native
console URL is https://rustfs.socrat.alchemmist.xyz/rustfs/console/ (not root).
**Foundation acceptance still requires real owner/MFA/native OIDC and evidence
file download/hash, outsider and logout tests; SPI remains off.** Full evidence,
fixture URL and exact hash/manual steps: `docs/rustfs/public-foundation-20261106.md`.
Single-node Retain storage is neither HA nor independent backup. Rollback must
preserve PVC/PV and account for manual prune-OFF ingress removal.

## SPI S3 activation — 6 November 2026 (natural publication pending)

Supersedes earlier OFF/not-deployed statements for SPI only. Approved source
`7e1cd0a9ccccdb8322815a1d8b20bdd9060f502b` passed rereview; OFF/live readiness
at `e7a23613ce3e5c62ed1635f27068109991724f2e` passed. Authorized minimal ON
activation is `af9cbcdac8bd03a2ce2b0155b23193e8bad33938`, changing only
`charts/spi-triage/values-off-live.yaml` enabled=true and explanatory comments.
Both SPI and RustFS were Synced/Healthy there; actual worker loaded backend=s3,
S3Evidence, with client SHA256
`97604f85646d55ba1f36c384be4034becc786608a3ee39663a42d8e6b2d72c5c`.
No image rebuild; ConfigMap source is unchanged from accepted OFF deployment.
Fresh SQLite backup API checkpoint before activation: 23,404,544 bytes, SHA256
`fa338ee2369fd5b021f8cc5de0d2f40c2109ed743f69a5862e236c97e0a65acb`;
independent integrity/FK checks passed. A subsequent consistent snapshot passed
those checks too (SHA256
`81a4741781b58c38d81e5a51e505c20d85d35daf7cdc0b15c2fbabd398608a27`).
Private checkpoints remain under ~/.config/homelab/spi-final-acceptance/.

Bounded natural observation 12:39:14–12:42:15Z found **no S3-selected job**.
Queue remained 100 queued, 11 retry, 1 processing, 170 complete, 5 dead,
2 dry_run. No real S3 GitHub narrative/manifest/artifact link can yet be cited;
Reader byte/hash/truncation/missing proof for a real publication is **pending**.
Do not interpret ON/Healthy or prior benign storage fixtures as end-to-end proof.
No forced claim/reselection, lease/budget reset, dead revival, synthetic alert,
model call, GitHub test write or Telegram replay was used.

289/289 original IDs/creation timestamps survive. All 177 original terminal
states/results/intents are unchanged; one complete row naturally gained a
redelivery timestamp/count. All 145 original effective legacy locks retain their
results/intents (144 rows wholly unchanged). Legacy-only original continuation
markers must remain as-is; they are not migrated by ON. Independent Telegram
outbox remains 73 rows: 66 applied, 7 pending; URL/event/revision/state and
acknowledgement unchanged, two pending rows advanced ordinary retry timing/count.
393 Telegram receipts and 212 receipt events are byte-for-byte row-equivalent;
no replay or outage injection. Exact-primary semantics are independent of S3.

Tests: prior source rereview 151 SPI + 5 chart/helper + 29 RustFS passed;
activation reran 5 chart/helper tests and both chart lints successfully. Prior
OFF actual conditional 412/race/ambiguity/IAM denial gates remain accepted.
Existing nativeOIDC human/download45B hash evidence remains accepted, not
re-enacted; console GetOnly unchanged. No new human logout/outsider claim.
A real-publication anonymous/forged-auth read and scoped Reader verification
must still be recorded when a natural eligible job actually publishes.

Backend-preserving rollback: set only enabled=false in the same live overlay;
retain retainCredentials=true, dedicated writer Secret/mount and exact network
grants while any S3-locked continuation exists. Fetch/rebase before scoped HTTPS
push; never erase historical comments/files or reset job state. Standalone Retain
storage is not HA, enforced quota or independent backup. Four Ready nodes were
observed in the existing context, not seven; no topology change or seven-node
verification is claimed. No n8n identities/workflows/credentials/PVC/encryption,
calendar/Yandex/blog WRITE_ENABLED, NetBird/Mac/VPN/DNS/shared edge, human IAM or
RBAC changes were made by activation. Final acceptance report:
`/tmp/spi-s3-final-live-acceptance.md` (PENDING until real publication proof).
