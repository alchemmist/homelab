# RustFS foundation — private foundation live, public acceptance pending

Actual runtime continuation2026-11-05: read `docs/rustfs/live-foundation-20261105.md`
FIRST. RustFS+gateway ArgoSynced/Healthy at cde102777245b1a20fb79d1c00ebf499af9427a5;
explicit tracked values-foundation-live.yaml enable private storage/OIDC/reader,
NOT browserRoutes. RustFS1.0.4 nonroot10001, Retain20Gi PVC on socrat-0 works;
2Gi reservation/4Gi limit (parent-reviewed capacity adaptation), actual23–25Mi
working set. Not enforced20Gi quota, HA or independent backup. Gateway approved
sourcee3d379f built pinned Python base, actual published registry manifest
sha256:0af2fdaaedf74c4ddbd0dc06fe48965ef609b4e4c211fcb72db3fceb9b72a0c7.
Local OCI digest changed on registry push; use registry digest, NOT local41fd2a.

Actual private bucket/bootstrap/PUT/GET exact bytes/eight403IAM denials pass;
additional anonymous/other-bucket/list-all denials403. Restart retained fixture.
Native OIDC provider+authorize302 exact callback/PKCES256 verified; dedicated
owner/platform-only admission and additive outpost done. Identity tool fixed
managed built-in scope selection, explicit callback type and exact dedicated app
GET (launcher list is admission-filtered); twice-idempotent actual reconcile.
Root only RustFS, reader only gateway; writer offline, never SPI. Private consistent
SPI SQLite backup verified header/integrity/FK,17,879,040bytes, retained in
~/.config/homelab/rustfs-foundation/20261105T133000Z/spi-pre-foundation.sqlite.
No incident/queue repair/reset/lease bypass or original workload rollout.

Actual gateway401/HTMLfixed302/Hostspoof/path negative tests and16.15s slow-header
cutoff+recovery passed. CNI demonstrated reader->S3/AuthHTTPS allowed, arbitrary
egress and unrelatedSPIworker->RustFS blocked. Local27RustFS+33Authentik tests
separate from live acceptance. No human login/cookie/token/STS acceptance claim.

Pending REAL prerequisites (not another source-scaffold/reapproval loop): DNS two
records source-only pending secure existing sudo mechanism for Knot authorities;
edge watches main automatically but Recreate1hostNetwork would briefly drop VPS
entrance if namespace delta pushed. That delta NOT committed; exactdiff
/tmp/rustfs-edge-namespace-handoff.diff for parent cutover/maintenance review.
Browser routes absent until DNS, edge availability plan, TLS/SNI then real manual
MFA/nativeSSO/STS/unaffiliated rejection/authenticateddownload+slowpeer tests.
User asked foundationFIRST; SPI backend/publisher/source remain unchanged.

---
## Historical source-phase notes (superseded for actual activation status)

Read `docs/rustfs/foundation-review.md`, `activation-checklist.md` and
`docs/n8n/spi/rustfs-migration-plan.md`. Do NOT repeat release research or restart
completed source. Baseline scaffold was 5178ace; this continuation adds protected
reader, SigV4/security/integrity tests, private bucket/IAM bootstrap, additive
Authentik/Secret tooling, probes/network/optional TLS routing and runtime scripts.
Independent review and all actual deployment/security/browser gates remain.
No source-is-deployed claim. No push or runtime mutation occurred.

RustFS official 1.0.4 index digest remains
sha256:ed9210d6411d77ffceb70d94b964a3cb7d225983368bc25bebe01e995293dcc2.
Native OIDC really supports PKCE S256/client_secret_post; configure dedicated
rustfs_policy claim -> spi-console-reader only for existing homelab-owner or
homelab-platform-operator. No ROLE_POLICY or arbitrary group-policy mapping.
Root isolated from reader/writer, no broad Secret RBAC or SA-token mounts.

Console: Authentik full proxy all paths (including callbacks), then native OIDC.
Evidence: Authentik **forward_single**, because pinned Authentik 2026.8.5 registers
/auth/nginx only in forward modes. Reader directly validates bounded Cookie at
fixed HTTPS evidence origin auth endpoint and trusted pipe-separated groups;
ignores client identity headers. Fixed origin, exact paths, no query/encoding or
redirects/proxies, manifest/file SHA256 and lengths, attachment/nosniff/no-store,
no bodies/keys/cookies/request paths logged. Anonymous 401 includes fixed login
Link; real session/download still untested. Do not accidentally change evidence
to full proxy (would recurse its auth check).

Tools in scripts/rustfs are explicit/local plan by default; root/operator secrets
private0600 in owned0700 directory, never CLI arguments. bootstrap mc stdin keys,
exact policy compare, private bucket check, NEW journaled machine users only;
refuses unrelated existing users/key drift, no rotation. Actual mc/RustFS runtime
compatibility and negative IAM gates are unproven until explicitly executed.
Identity tool only dedicated apps/providers/mapping/bindings and additive outpost
assignment; no existing humans/memberships/roles modified. Secrets file generator
does not apply. Runtime fixture is clearly nonincident, separate from n8n.

Chart default enabled/oidc/gateway/browserRoutes false. Activation requires reader
image approved build/digest, exact TLS endpoint /32-/128s and verified CNI selectors,
valid SNI TLS, independent review + explicit runtime authorization. Manual Helm
script and Argo app are alternative owners; never use both concurrently. Rollback
removes browser routes and scales only these deployments; preserves PV/PVC/SC.
Standalone socrat-0 20Gi Retain local-path is NOT HA/backup/quota. README stress
hardware is not a vendor minimum. No publisher switch implemented: foundation must
be up/tested FIRST. Preserve all n8n identities/credentials/PVC/encryption key,
queues/leases/attempts, calendar/blog write-disabled policy and historical comments.

## 2026-11-05 private reader relocation actually executed

See `docs/rustfs/gateway-namespace-migration.md` actual execution section. Reviewed
source eba1d839ac2313d7694aa0d2e7be70269af9a01a; activation/observed Argo revision
586109ae1803be25f02d8ef23338c89125b647ed Synced/Healthy/Succeeded. Reader only now
in identity; actual registry image sha256:9253d36e923e216cd34714a5baf9b57d1bb5577bf52c4671a4f8d302a27fef57.
Private canonical DNS/SigV4 exact45-byte/hash read and Authentik HTTPS200 passed.
Old gateway Deployment/Service/policy removed only after ownership/function checks.
Storage spec+UID unchanged, PVC retained; only reader/pull credentials in identity.
No shared-edge change, browserRoutes=false, no SPI switch.

New public gate: actual VPS hostNetwork edge reaches reader via node route
src10.42.0.1;401 is NOT network isolation. Own unrelated identity pod on socrat-2
cannot reach reader but CAN GET RustFS Service /health200 (socket source10.42.0.9).
No speculative allowance/fix added. Parent review/CNI-NAT investigation needed;
post-NAT S3 source/root cause unknown. DNS still lacks sudo credential; TLS,
human browser/native OIDC/STS/logout/revocation, authenticated bounded/slow-peer
checks remain unperformed. Do not describe DNS as the only remaining gate.
