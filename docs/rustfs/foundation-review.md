# RustFS foundation research / incomplete review scaffold

Status: BLOCKED / not deployment-ready. No SPI integration, gateway, Authentik
configuration, bucket provisioning or cluster changes were performed. All activation
switches remain off. Do not enable the chart as a substitute for completing the gates.

## Official release evidence

Fetched directly from official GitHub and Docker Hub during this source review:

- https://api.github.com/repos/rustfs/rustfs/releases/latest returned `1.0.4`.
  Release notes describe trust-store/certificate fixes and dependency refresh.
- https://registry-1.docker.io/v2/rustfs/rustfs/manifests/1.0.4 returned OCI index
  `sha256:ed9210d6411d77ffceb70d94b964a3cb7d225983368bc25bebe01e995293dcc2`.
  Linux amd64 manifest is
  `sha256:e287e99762a4a3e7b706526e01f2ff755f67db165e9be9f6b907adc6fb6d6ee1`.
  This is registry digest verification, not independent signature verification.
- https://api.github.com/repos/rustfs/rustfs/security-advisories returned 30
  published advisories. Returned affected ranges stop before 1.0.4; this is not
  a claim of absence of undisclosed vulnerabilities. Particularly relevant: writer
  version overwrite GHSA-gjph-xcgw-4p7w, alternate-protocol IAM bypass
  GHSA-rhg6-jrf2-29c4, header identity spoof GHSA-6r96-hmgc-726c and service-account
  privilege escalation GHSA-5354-r3w2-34m8. Disable alternate listeners and retest IAM.
- Official `1.0.4/Dockerfile` creates uid/gid 10001, writes `/data` and `/logs`,
  with events/audit symlinks under `/opt/rustfs` into `/data/.rustfs`.
  Chart mounts writable data, logs, tmp and uses that nonroot identity. Actual
  local-path filesystem permissions and read-only root operation remain untested.
- `1.0.4/rustfs/src/server/health.rs` distinguishes liveness from readiness and
  mentions `/health/ready`. Exact route wiring and runtime health behavior must
  be verified before probes are added; scaffold intentionally has no probes.

## Native OIDC exists; not a blocker in this release

Official pinned documentation:
https://github.com/rustfs/rustfs/blob/1.0.4/docs/operations/oidc-console-integration.md
and adjacent `oidc-provider-requirements.md`, backed by constants and IAM sources.
Native flow validates ID token signature, issuer, audience, expiry, nonce with
PKCE S256 and client_secret_post. State is node-local (standalone fits).

Required future settings: `RUSTFS_IDENTITY_OPENID_ENABLE=on`, CONFIG_URL set to
the exact Authentik issuer, CLIENT_ID and CLIENT_SECRET from a dedicated Secret,
SCOPES including openid, fixed REDIRECT_URI
`https://rustfs.socrat.alchemmist.xyz/rustfs/admin/v3/oidc/callback/default`,
REDIRECT_URI_DYNAMIC=off, and RUSTFS_BROWSER_REDIRECT_URL set to the console
origin. Use a dedicated policy claim, not arbitrary existing groups as policy
names. Never set ROLE_POLICY=consoleAdmin for all authenticated users.

Existing policy sources inspected: `deploy/identity/access-policy.yaml`,
`services.json`, `n8n-gateway.yaml`, and
`ansible/roles/authentik/files/prepare_app_iam.py`. Existing owner is protected;
existing IAM tool has a strict service allowlist not including RustFS. Do not
silently extend it or mutate existing apps. A reviewed additive application and
claim mapping must admit only justified existing homelab-owner/platform groups.
OIDC is browser console identity; S3 still uses SigV4 scoped machine keys.
A separate authorized Authentik browser session must protect artifact downloads;
trusting X-auth headers on an externally reachable reader is not acceptable.

## Remaining implementation / review gates

This commit deliberately contains only a disabled foundation scaffold. It does
not satisfy the full requested foundation phase. Before independent readiness:

1. Verify official standalone support and resource guidance (2Gi request / 4Gi
   limit are provisional, not vendor requirements). Verify exact readiness routes.
2. Implement authenticated bounded read-only gateway, signing and security tests,
   including auth before *all* errors, encoded traversal/query rejection,
   no redirects, bounded bytes, attachment/nosniff, and verified SHA256. Stable
   origin is https://spi-evidence.socrat.alchemmist.xyz; no public S3 endpoint.
3. Implement idempotent private bucket / IAM reconciliation with mismatch stops:
   bucket spi-evidence, resource arn:aws:s3:::spi-evidence/spi/v1/*; reader GetObject
   only, writer PutObject/GetObject only; no list/delete/admin or root-parent
   service accounts. Do not execute unverified mc compatibility assumptions.
4. Add authorized Authentik native OIDC mapping, gateway auth, valid TLS, network
   isolation and spoof/bypass tests. Root Secret only RustFS/bootstrap. Console
   must not expose public root login. Current isolation denies all networking.
5. Recheck actual socrat-0 disk/memory before any later authorized deployment.
   20Gi local-path request is not an enforced disk quota. Validate retained PV,
   permissions, live auth-positive/negative and IAM-negative fixture checks.

Single node means no HA, and local Retain storage is not an independent backup.
No human login, cluster readiness, independent backup, IAM success or gateway
success is claimed. Preserve n8n IDs, key, PVC, queues/leases and historical
comments. Calendar unchanged; blog writes disabled. No GitHub publication in this
phase. No cluster mutation or push authorized here.
