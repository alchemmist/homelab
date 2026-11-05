# RustFS foundation — operator activation and rollback

**SOURCE ONLY. Not deployed, no runtime gate passed in this source phase.**
All committed activation defaults remain false. No SPI publisher switch exists
in this change. Independent review must resolve security findings before any
operator follows the mutating instructions below. Do not run the broad existing
`configure.py`: it also changes existing identity state.

## Source and preparation (read only / local)

- Review the foundation commit, `foundation-review.md`, migration contract, chart,
  gateway and `scripts/rustfs/`. Run all `test_rustfs*.py`, Helm lint and renders.
- Record independently approved commit. Recheck socrat-0 free disk/memory and
  current workload reservations. 4Gi requested/limited memory is a starting bound,
  not a demonstrated capacity guarantee; investigate OOM/readiness before raising
  limits. Release README's 4GB row is a **stress-test environment**, not a vendor
  minimum. SNSD supports standalone local path only; no expansion-in-place claim.
- Confirm local-path provisioner honors Retain and fsGroup 10001. Check actual
  node/pod placement and directory permissions after first start; do not add a
  privileged chown init container or run as root to hide a failure.
- Build `services/rustfs_gateway/Dockerfile` in approved CI/operator environment;
  review/pin its base image for that build and record resulting reader image
  digest. Chart refuses mutable reader tags. This phase did not build/push it.
- Identify exact public TLS endpoint IPs used by Authentik and evidence domains,
  and actual CNI destination after DNAT. `authEgressCIDRs` allows only /32 or /128
  TCP443; no 0/0. Verify kube-dns, Traefik and Authentik server selectors against
  the installed cluster. Narrow policy failure must stay failure, not widen to
  arbitrary egress. Reader needs evidence endpoint; RustFS needs Authentik endpoint.
- Create private owned mode0700 directory outside repo. All JSON inputs must be
  owned mode0600 regular files (no symlinks); never shell tracing, shell history
  credentials, logs, command-line secrets, Git or a Kubernetes ConfigMap.

### Private input formats

`storage.json` (bootstrap root is operator-only, not given to SPI/reader):

```json
{"endpoint":"http://127.0.0.1:19000","root":{"access":"<existing-root-access>","secret":"<existing-root-secret>"},"reader":{"access":"<new-random-reader-access>","secret":"<new-random-reader-secret>"},"writer":{"access":"<new-random-writer-access>","secret":"<new-random-writer-secret>"}}
```

Generate three **different** random identities, never reuse root. Bootstrap
accepts 16–128 alphanumeric/underscore/hyphen characters. Existing root Secret
is precreated privately, with `access-key`/`secret-key`. The operator can prepare
it independently before identity configuration if needed; no Secrets or secret
reader Role/RoleBinding are rendered by the chart.

`credentials.json`: `{"AUTHENTIK_API_TOKEN":"<operator-token>"}`. Kept only in the
private directory; never mounted into Kubernetes. Use existing owner-authorized
operator access. Do not create new humans, alter memberships, MFA, flows or roles.
The exact existing admission groups are `homelab-owner` and
`homelab-platform-operator`; missing groups or prerequisites stop provisioning.

## Foundation first (separate explicitly authorized runtime phase)

1. Create the rustfs namespace and dedicated root Secret using private file input.
   Operator must not grant workloads general Kubernetes Secret read/list rights.
2. Prepare private nonsecret runtime values: `enabled: true`, OIDC/gateway/browser
   still false. Validate chart renders; deploy only after explicit authorization:
   `scripts/rustfs/deploy.sh --apply <approved-HEAD> <runtime-values.yaml>`.
   The script uses manual Helm. **Do not have Helm and Argo manage the same
   resources concurrently.** For GitOps ownership instead, commit reviewed
   foundation-only values in a separately authorized change and manually sync
   the supplied Argo Application; it has no automated sync.
3. Check startup `/health/live`, readiness `/health/ready`, storage ownership,
   retained PV/PVC, actual 20Gi request/StorageClass/node affinity and socrat-0
   placement. Check bounded logs/tmp and restarts. Requested local-path capacity
   is not an enforced disk quota. No HA or independent backup exists.
4. Open operator-only port-forward `kubectl -n rustfs port-forward svc/rustfs
   19000:9000 --address 127.0.0.1`. Never ingress/NodePort the admin/S3 API.
5. Obtain a reviewed official `mc` binary; record its SHA256. Run local plan then
   explicit bootstrap:
   `python3 scripts/rustfs/bootstrap.py --credentials <private>/storage.json
   --mc <absolute-mc-path> --mc-sha256 <reviewed-digest> [--apply]`.
   `mc admin user add` reads both keys from stdin (official source inspected),
   captures/discards JSON output including its echoed secret. Config is mode0600
   in a private temporary directory. Check compatibility against 1.0.4 here;
   mocked unit tests are not a claim of live mc/RustFS interoperability.
6. Bootstrap creates private `spi-evidence`, three exact prefix policies and NEW
   reader/writer users (not root-parent service accounts). Reader GetObject only;
   writer GetObject/PutObject only; neither list/delete/admin. Policy mismatch,
   non-private bucket, unrelated existing user, changed journaled key, group or
   unexpected grant stops. Preserve private `bootstrap-journal.json` for retries;
   it pins ownership/secret hash and permits safe policy-attach resumption.
   Never delete the journal to adopt an existing user. No implicit key rotation.
7. Create a separate private `machine.json` containing **only** reader and writer
   entries from storage.json. Explicitly run
   `python3 scripts/rustfs/verify_runtime.py --machine-credentials <private>/machine.json
   --apply-fixture`. This writes deterministic clearly-labelled non-incident S3
   files only, verifies exact bytes and eight explicit access-denial gates. It
   never calls n8n/GitHub/Telegram. It refuses to overwrite differing fixture data
   and leaves files retained (machine Delete is intentionally denied). A 404 or
   network failure is not an acceptable IAM denial. If absent-object GET returns
   403, stop and investigate release semantics; do not bypass absence checks.

## Identity, protected TLS console and downloads (still no SPI activation)

1. Run `python3 scripts/rustfs/provision_identity.py --private-dir <private>` for
   GET-only inventory/plan, then explicitly `--apply` only after review. It
   persists private `rustfs-client.json` before provider creation, never rotates
   it silently, and fails on existing dedicated object drift. Existing identities
   and roles are not edited. Only the embedded outpost provider assignment is
   additively extended, preserving current provider IDs/config.
2. Native confidential OIDC client uses authorization_code only, strict callback
   `https://rustfs.socrat.alchemmist.xyz/rustfs/admin/v3/oidc/callback/default`,
   per-provider issuer, signed ID token, user_uuid, and dedicated `rustfs_policy`
   scope/claim. Claim emits `spi-console-reader` only for the two exact groups;
   it never maps arbitrary group names or gives everyone consoleAdmin. RustFS
   pins claim/groups/roles names to that claim, disables dynamic redirect and
   never sets ROLE_POLICY. This read-only policy does not promise console admin
   or unrestricted bucket enumeration. Check real console UX before publication.
3. Separate whole-console proxy admits only those existing groups; every browser
   console path/callback goes through Authentik, with no raw console/S3 ingress.
   Thus public root-login **bypass** of SSO is absent; root API authentication
   remains available for private administrative recovery. Do not use/distribute
   root keys in browser login or machine calls. Native RustFS OIDC is still the
   storage identity; the outer proxy is admission, not a replacement for it.
4. Evidence provider is **forward_single**, not full proxy: pinned Authentik
   configures `/auth/nginx` only in forward mode. Reader authenticates a bounded
   Cookie directly against fixed trusted HTTPS evidence-origin `/outpost.goauthentik.io/auth/nginx`;
   requires 200/204 plus exact trusted response owner/platform group. Client
   X-authentik/X-forwarded identity headers are ignored. Do not change this to
   full-proxy mode: that would route auth checks back into the reader.
5. `python3 scripts/rustfs/secrets.py --private-dir <private>` writes dedicated
   mode0600 Secret JSON files locally only. Apply root, reader and OIDC Secrets
   privately by file, never argv. Keep writer Secret file offline/unmounted until
   the separate SPI phase. Chart mounts root only into RustFS, reader only into
   reader, OIDC secret only into RustFS; no Kubernetes token automount or RBAC.
6. Enable OIDC, gateway and browser routes in separately reviewed runtime values
   with reader digest and exact /32-/128 endpoint addresses. Ingress routes full
   console to Authentik; only evidence `/outpost.goauthentik.io/` goes to Authentik,
   other evidence paths go to independently authenticating reader. No raw S3 route.
   Valid cert-manager TLS certificate must cover both fixed hosts; evidence app
   router uses the certificate loaded by the identity-namespace TLS ingress (same
   existing n8n cross-namespace pattern). Verify this with real SNI, not assumption.
7. Check actual discovery issuer/audience, S256 and client_secret_post; official
   1.0.4 RustFS flow automatically sends PKCE verifier and secret in token POST.
   Authentik 2026.8.5 discovery advertises both. Perform **real browser** Authentik
   owner/platform logins and native callback; verify signed ID claims/policy,
   expiry/logout/revocation and reject unaffiliated users. A decoded JWT alone is
   not proof of validated authentication. Do not edit existing memberships to test.
8. For evidence, first establish session at
   `https://spi-evidence.socrat.alchemmist.xyz/outpost.goauthentik.io/start?rd=https%3A%2F%2Fspi-evidence.socrat.alchemmist.xyz%2F`.
   Reader's unauthenticated response is 401 with this fixed authenticate Link,
   not an attacker-selected redirect. Reopen the deterministic fixture path
   printed by verify_runtime. Compare downloaded SHA256 and bytes independently.
9. Test anonymous GET/HEAD/errors, disallowed user, forged/duplicate auth headers,
   encoded/double-encoded traversal/slashes, doubled leading slash, queries,
   absolute URLs, redirects, upstream failures, metadata/length/hash corruption,
   reader PUT/delete, other prefixes/buckets and root/console bypass paths. Inspect
   trusted outpost/Traefik log configuration: **no debug/trace header/body/cookie
   logs**. Authentik pinned code has trace-level request-header logging; do not
   enable it. Reader itself never logs request paths, bodies, cookies or keys.
10. Only after all real gates pass record actual revision/runtime test evidence
    and backup limitations. **SPI remains unchanged/off**. Consistent n8n SQLite
    backup verification and a separately reviewed publisher implementation are
    prerequisites to any later SPI switch; this source phase does not implement it.

## Rollback / monitoring

On auth/hash/IAM uncertainty: do not publish links or widen policies. Explicit
`scripts/rustfs/rollback.sh --apply` removes both browser ingresses, scales only
RustFS/gateway deployments to zero, never deletes retained storage or alters
Auth identities/SPI state. If Argo owns resources, first prevent manual resync
from undoing rollback and commit disabled values via approved GitOps procedure.
Never uninstall/delete PV/PVC/StorageClass as rollback. Keep private credentials
and journals for controlled recovery; revoke/rotate only these NEW keys/apps via
an explicit reviewed incident procedure, not a broad existing identity script.

Monitor pod readiness/restarts/OOM, real disk usage and inode pressure, local-path
PV health, gateway 401/502 counters without labels containing secrets/paths, IdP
availability and certificate expiry. The current reader is a bounded serial
standard-library server, not a high-throughput/HA service; load/slow-client tests
are mandatory for public exposure. No independent backup or recurring backup is
claimed. Preserve n8n IDs/credentials/PVC/encryption key, queues/leases/attempts,
calendar behavior, blog write-disabled state and all historical evidence comments.
