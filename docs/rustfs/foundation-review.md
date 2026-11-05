# RustFS foundation source implementation / review evidence

Status: SOURCE IMPLEMENTED, ACTIVATION DISABLED, independent review pending.
No deployment, push, Authentik/Kubernetes mutation, image publication or SPI
publisher switch occurred. Actual runtime provisioning/SSO/IAM gates are not
claimed as passed. See `activation-checklist.md` for phased operator procedures,
private inputs, rollback and exact gates. Existing n8n/SPI source remains untouched.

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
  Chart mounts writable data, logs, tmp and uses that nonroot identity. A same-uid
  bounded init container creates `/data/.rustfs/events` and `audit` because a new
  PVC hides image-created directory targets; it never runs root/chown. Pinned
  entrypoint initializes data/log paths without requiring privileged writes to
  root filesystem. Actual local-path permissions/read-only operation remain untested.
  Image's wildcard console CORS default is explicitly overridden with the fixed
  console origin; S3 generic CORS stays empty and logging stays warn.
- Pinned `rustfs/src/server/prefix.rs` defines `/health/live` and `/health/ready`;
  `server/layer.rs:resolve_public_health_probe` maps GET/HEAD to liveness/readiness
  before S3 parsing. `server/health.rs` separates liveness from readiness. Chart
  now has startup/liveness/readiness probes with bounded failure windows. Actual
  live behavior and permissions remain runtime gates.
- Pinned README marks Single Node Mode available and explicitly supports SNSD as
  a standalone local path only (no in-place expansion/pool addition). README
  4GB/2-core table describes a stress-test environment, NOT a hardware minimum.
  Chart uses provisional 4Gi request/limit and 2-core limit; load and headroom
  verification remain mandatory. No vendor resource guarantee is inferred.

## Native OIDC exists; not a blocker in this release

Official pinned documentation:
https://github.com/rustfs/rustfs/blob/1.0.4/docs/operations/oidc-console-integration.md
and adjacent `oidc-provider-requirements.md`, backed by constants and IAM sources.
Native flow validates ID token signature, issuer, audience, expiry, nonce with
PKCE S256 and client_secret_post. State is node-local (standalone fits).

Implemented optional settings: `RUSTFS_IDENTITY_OPENID_ENABLE=on`, CONFIG_URL set to
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
silently extend it or mutate existing apps. The dedicated additive reconciler now admits only existing homelab-owner/platform
groups, maps only a dedicated read-only policy claim, and never edits memberships.
OIDC is browser console identity; S3 still uses SigV4 scoped machine keys.
A separate authorized Authentik browser session must protect artifact downloads;
trusting X-auth headers on an externally reachable reader is not acceptable.

## Delivered source and offline validation

- Auth-first read-only gateway: deterministic private paths, bounded exact-length
  responses, manifest-address SHA256 + per-file hash/length validation, ASCII,
  attachment/octet-stream/nosniff/CSP/no-store, no arbitrary URLs/query/encoding,
  redirects/proxies disabled, no request/body/secret logs. Cookie is checked at
  fixed trusted Authentik forward-auth endpoint; trusted response group must be
  owner/platform, no client-supplied identity headers. Negative and authenticated
  local server tests exercise exact bytes and errors. The serial implementation
  is intentionally bounded, not a throughput or HA claim.
- SigV4 request signing with exact URI/header/payload binding. Offline tests
  include a literal Unicode/space canonical request independently signed with
  OpenSSL HMAC, deterministic dates/scope/host/port and query/userinfo rejection.
- Private idempotent bucket/IAM bootstrap using a hash-verified operator mc binary;
  policy/bucket/user inventories must succeed, mismatches stop, journal pins NEW
  machine users, resumes policy attachment safely, no password overwrite/adoption.
  mc stdin key support and JSON policy/permission fields inspected in official mc
  sources. This is source compatibility evidence, not a live RustFS mc test.
- Dedicated additive Authentik provisioning, GET-only plan by default, private
  client journal before creation, strict existing-object drift stops, exact group
  bindings, no user/role/membership edits. Native confidential authorization-code
  OIDC uses per-provider issuer and dedicated scoped claim; console full proxy,
  evidence forward_single, no bypass regex/basic auth/header auth.
- Secrets are isolated private output files, never chart-generated/ConfigMaps or
  argv. Root only storage, reader only gateway, OIDC secret only storage. Writer
  remains offline/unmounted for future SPI phase. No secret RBAC or SA tokens.
- Disabled Helm components include retained storage, verified probes, ClusterIP,
  strict pod/namespace network boundaries, narrow endpoint egress guard, reader
  digest requirement, TLS browser ingress patterns and fail-closed dependencies.
- Explicit deploy/rollback scripts and real isolated runtime fixture/IAM checker.
  These were NOT executed against a cluster. Mocked provisioning tests verify
  normal rerun idempotency, policy scope, drift stops and additive identity writes.

## Authentik release semantics verified from official pinned sources

Existing chart appVersion is 2026.8.5. Inspected tag `version/2026.8.5`:

- `authentik/providers/oauth2/api/providers.py` exposes grant_types,
  client_type/client_secret, strict redirects, mappings, signing_key, issuer_mode.
- `models.py` defaults issuer_mode to per_provider; configured explicitly here.
- `views/provider.py` advertises client_secret_post and PKCE S256 discovery.
- `internal/outpost/proxyv2/application/application.go` configures forward auth
  endpoints ONLY in forward_single/forward_domain, not proxy mode. Hence console
  full proxy and evidence forward_single are intentionally different.
- `mode_forward.go` nginx auth returns HTTP200 with trusted claim headers;
  `mode_common.go` joins X-authentik-groups with `|`. Reader requires owner/platform
  in that trusted response; header spoofing by clients does not satisfy it.
- `mode_proxy.go` gates all console requests with checkAuth, no configured skip
  regex here. It overwrites identity headers from claims. Root API login is not
  disabled; no public route bypasses Authentik admission to reach it.
- Outpost contains trace-level header logging. Runtime must keep debug/trace off;
  no secret/body/header logging claim is made about a deployed IdP configuration.

Official source base links:
https://github.com/goauthentik/authentik/tree/version/2026.8.5
https://github.com/rustfs/rustfs/tree/1.0.4
https://github.com/minio/mc/tree/master/cmd (reviewed command behavior only;
operator must pin/review an actual binary before bootstrap).

## Required independent and runtime gates

Independent read-only review must still resolve source findings before rollout.
Runtime gates: actual PVC/node permissions and capacity, image startup/read-only
root filesystem, live readiness, mc/admin compatibility, least-privilege credential
positive/negative tests, IdP provisioning/discovery, actual native OIDC browser
sessions, certificate/SNI, exact group authorization, gateway positive/negative
session and hash tests, CNI selectors/DNAT, endpoint egress, and load/slow-client
behavior. A unit test/mock is not a human login or runtime proof.

Single node means no HA or independent backup. Retain PVC is not backup, requested
local-path size is not quota. No recurring backup deployed. Preserve existing
n8n identities, credentials, encryption key/PVC, queued work, calendar/blog policy
and historical evidence. Keep source switches false and do not implement/activate
SPI publishing until this foundation is independently reviewed, authorized up and
actually tested. No unresolved operator authorization choice is invented here;
the remaining deployment authorization is a deliberate phase boundary.

## Source corrections after independent review

The reader is a **bounded buffered verified download**, not progressive streaming,
constant-space processing, or constant-time processing. It buffers a manifest and
(up to 2 MiB) object before returning verified bytes; accepted artifacts are at
most 90,000 ASCII bytes. HTTP Content-Length framing is not proof that a peer did
not send trailing bytes; connections are not reused.

Gateway admission is capped at eight connection workers (excess connections are
closed). Absolute socket-shutdown watchdogs cover headers (15 seconds), the
accepted connection including response writes (45 seconds), and each upstream
connection including headers/body (10 seconds), in addition to inactivity limits.
OS name resolution is not interruptible by these socket watchdogs; cluster DNS
health remains an operational dependency. This is not a guarantee against all
resource exhaustion. Traefik parses external headers first: its buffering and
header/write timeout configuration and real slow-client/load tests remain
mandatory before public exposure. Local regressions exercise actual trickled
headers and upstream headers/bodies, not just mocked timeouts.

The Dockerfile pins the public Docker Hub `library/python:3.13-alpine` OCI index
at `sha256:7984cf56ceaddebe4fefeb75d64000b9f45d8b77b11a09b24524da6cdc3af0c8`.
The registry manifest was retrieved read-only and its bytes independently SHA256
checked against Docker-Content-Digest during correction. This verifies existence
and content identity, not vulnerability freedom or a built gateway image. Record
selected platform/base manifest, source commit, build inputs, scan and resulting
private gateway digest before activation; no gateway image was built/published.
Deployment anchors chart/repository paths to the script and refuses dirty tracked
source and a nonmatching approved revision. Private runtime values are a separate
reviewed input; this check does not itself grant deployment approval.
