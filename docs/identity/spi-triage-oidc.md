# SPI Triage: standalone native OIDC (prepared, not live)

Read `llm-wiki/identity-integrations.md`, `identity-architecture.md`,
`identity-current-state.md`, `cluster-deploy.md`, published wiki `/platform/deploy/`
and `/start/access/` first. Historical proxy receipts are not a native OIDC recipe.

## Ownership and protocol

The existing `spi-triage` Application owns UI/BFF, worker, broker, ingress/TLS and
policy. No new frontend-only Application or release publisher is added. Application
code lives only in `alchemmist/spi-triage/frontend`, not frozen chart ConfigMaps.

`deploy/identity/spi-triage-oidc.json` is the dedicated native identity catalog,
owned by `scripts/spi-queue-oidc.py`. As with the separately managed Argo native
provider, it is intentionally outside foundation replay: do not duplicate the
provider in `services.json`, run the full foundation installer or adopt existing
clients without a private journal. This controller modifies only the new SPI
provider/application, its three admission bindings and empty app operator group.
It does not mutate users, memberships, MFA, outposts, shared scopes/signing keys,
other app roles or machine credentials. App-role assignment requires separate
review; no person is assigned automatically by this change.

Native confidential client, exact HTTPS callback and issuer, PKCE S256/state/nonce,
RS256 verification and signed groups. Canonical host `spi.socrat.alchemmist.xyz`,
callback `/oauth/callback`, launch `/queue/`. Owner/platform legacy access retained;
new `app-spi-triage-operator` maps to queue operator only. No observer grant. Email
is not a subject. See application `docs/queue-oidc.md` for full session/role rules.

Existing image dependencies already contain pinned PyJWT/cryptography; no proxy
or client secret in browser JS. Only frontend mounts `spi-queue-oidc`, credentials
file `0440` with fsGroup `10001`. No values in Git. Opaque local sessions expire within
five minutes and on logout/restart. This intentionally does not implement silent
refresh/global logout/instant IdP revocation and does not promise them.

## Controlled activation (not performed yet)

1. Restore verified operator Kubernetes/SSH access; do not erase known_hosts,
   bypass host/TLS checks, change workstation VPN/routes or expose the API.
2. Make the normal fresh encrypted IdP backup and private JSON receipt (including
   `encryptedBackup`, `sha256`, `observedAt`). Use native GET-only plan:
   `python3 scripts/spi-queue-oidc.py --credentials <PRIVATE_AUTOMATION_JSON>
   --state-dir <PRIVATE_SPI_STATE_DIRECTORY>`. Never display credential contents.
3. Review plan hash; apply only with `--apply --approve-plan-hash <EXACT_HASH>
   --backup-receipt <PRIVATE_RECEIPT>`. It creates only absent owned objects and
   keeps a private uncertain marker after any ambiguous/partial write. STOP for
   GET/review, not blind retry or automatic secret rotation. Existing drift is a
   blocker. The successful plan at preparation time reported six new objects.
4. Provision `automation/spi-queue-oidc` with key `credentials.json` from the private
   journal via the established Kubernetes Secret path, without echoing it or
   putting secret literals on argv. Verify the client ID and private credential
   match the native provider; do not share queue/worker/Harbor credentials.
5. The production `queueUI.oidc.enabled` remains `false` in this preparation PR.
   Enable it only alongside the native frontend digest and provisioned runtime
   Secret in a controlled frontend cutover window. The chart native
   override removes the RustFS queue route from the same Ingress and requests an
   app-owned HTTP01 certificate for SPI. DNS is operator-owned existing wildcard;
   this change does not edit DNS. Confirm actual DNS/TLS before calling it live.
6. The release uses the existing same-job `deploy-to-socrat@v1`, not manual image
   pins. Before protected publication approval, pause only new SPI claims through
   the original workflow, let its current owners/paid/processing work drain
   naturally and verify zero from live state. Restore the same workflow after
   exact-digest readiness and preservation checks. No reset/replay/forced stop.
7. Verify real native MFA/callback and authorized queue read, anonymous API401,
   forged/outsider rejection and local logout; never cancel a real job as a probe.
   Old unused proxy middleware can be retired only after checking no consumers,
   saving preimages and targeting exact resources, never blanket pruning.

Network egress admits the existing public TLS endpoints and actual internal VIP
/32 plus namespace/pod-selected K3s Traefik ServiceLB `443` and Traefik `8443` post-DNAT
hops. No broad Internet/cluster CIDR, direct storage access, DNS override or TLS
bypass. Backend/PVC/jobs/RBAC/limits are unchanged by the native frontend toggle.

## Preparation receipt

Built native amd64 image: 341 tests/zero skips, offline/read-only, 1 CPU / 384 MiB.
Homelab tests cover native host/TLS, no forward-auth, frontend-only credential
mount, exact network selectors, nonprivileged group shape and unchanged backend
resources. Actual Authentik read-only plan verified existing default MFA/explicit
consent flows, signing key and reviewed groups scope; no apply performed.

Runtime access is currently unavailable: default kubeconfig reaches obsolete/
unreachable `192.168.0.23:6443`; SSH stops at missing trusted host key. No runtime
provider/Secret/ingress or image was changed and no production gate approved.
This receipt does not claim a live migration or human-login acceptance.
