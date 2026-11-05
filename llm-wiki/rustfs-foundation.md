# RustFS foundation — source implemented, all activation off

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
