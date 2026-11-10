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
   Use the Git-owned reconciliation hold below: image, flag and Secret must be
   ready **before** releasing it. The chart native override removes the RustFS
   queue route from the same Ingress and requests an app-owned HTTP01 certificate
   for SPI. DNS is operator-owned existing wildcard; this change does not edit
   DNS. Confirm actual DNS/TLS before calling it live.
6. Publish only through the existing same-job `deploy-to-socrat@v1`; it updates
   image fields, **not** the OIDC flag. The hold/release procedure below coordinates
   the separate commits without changing this deployment contract.
7. Verify real native MFA/callback and authorized queue read, anonymous API401,
   forged/outsider rejection and local logout; never cancel a real job as a probe.
   Old unused proxy middleware can be retired only after checking no consumers,
   saving preimages and targeting exact resources, never blanket pruning.

### Git-owned hold and release (required; no live overrides)

The current `spi-triage` child Application auto-syncs `main`; its parent `root`
self-heals the Application from `deploy/argocd/apps/spi-triage.yaml`. A live-only
pause would be reverted by root, so it is **not** an adequate maintenance hold.
Do not assume two quick commits are atomic or manually sync either half.

1. Establish one release owner and prevent overlapping same-app publications.
   Before merging/publishing the native source or enabling the flag, merge a
   **hold-only** Git commit adding `enabled: false` under this child's existing
   `spec.syncPolicy.automated` (retain `prune: false`, `selfHeal: true`, finalizer,
   destination, source and PVCs). Do not disable/delete root or another app.
   Wait for root reconciliation, then read back the actual child Application:
   `automated.enabled` must be false, no sync operation may be running, and the
   old image/route must still be serving. If not confirmed, STOP; do not publish.
2. Pause only new SPI claims through the original workflow; keep intake durable
   and other workflows active. Before protected publication approval, confirm
   that the current execution and any logical Wait have finished naturally.
   Capture a fresh, complete live drain readback: owners (including logical Wait
   owners), processing, inflight and active paid reservations must all be zero;
   inspect n8n pending executions for this SPI workflow and confirm that none
   remains active, waiting, or queued to resume/dispatch work. If any count or
   execution is non-idle, or readback is unavailable, STOP and wait naturally;
   reviewer approval alone is not drain evidence.
   Keep the established SQLite integrity/history preservation receipt and retain
   existing verified idle backups. The authoritative SPI release contract
   explicitly waives a new SPI backup prerequisite: do not reinstate it as a
   blocker here (the separate fresh IdP backup in step 2 of Controlled activation
   still applies to identity provisioning). Preserve every job, deadline and
   credential. No reset/replay/forced stop. Keep claims paused through release
   verification. See the [authoritative SPI activation gate](../../llm-wiki/spi-incident-triage.md#remaining-activation-gate)
   and [shared-image release contract](../../llm-wiki/cluster-deploy.md#spi-full-service-extraction--9-november-2026).
3. With the hold confirmed and runtime Secret/provider already provisioned,
   merge the native source and approve its protected standard publication gate.
   Let `deploy-to-socrat@v1` make its normal robot image-digest commit to homelab.
   Separately merge the reviewed Git change setting `queueUI.oidc.enabled: true`.
   Either commit order is safe **only while the confirmed hold remains active**.
   No manual sync or automated same-app deployment may bypass that hold.
4. Inspect a single combined homelab revision containing the robot-produced
   native image repository/tag/digest **and** enabled flag. Render that revision,
   verify frontend Secret reference/mount, exact callback/host/TLS and runtime
   Secret presence/matching client privately. Confirm desired image is the
   successful native CI artifact, the hold is still active and no intervening
   operation has rolled workloads. Missing any prerequisite means STOP.
5. Merge a **release-only** Git commit removing `automated.enabled: false` from
   this child (restore its original auto-sync policy; leave pruning disabled).
   Root restores auto-sync and SPI reconciles the now-complete desired revision.
   Read back the actual synced revision, exact running digests, rollout/readiness,
   unchanged PVC/history/terminal records and zero unexpected owners, then perform
   step 7 native human/TLS/authorization acceptance. Healthy alone is insufficient.
   Only after preservation and acceptance restore the same original workflow.
6. On failure, keep claims paused, re-establish and verify the same Git-owned
   hold, then coordinate the previous immutable image **and** `oidc.enabled:
   false` in one desired rollback revision before releasing the hold again.
   Retain the new provider/Secret and all state for review; do not rotate/delete
   credentials, restore an old DB over new history, prune or replay jobs.

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


## Runtime checkpoint — 10 November 2026, cutover held

- DNS was applied only to the three existing authoritative nodes; Google and
  Cloudflare independently resolve the exact SPI name. There is no wildcard.
- A fresh encrypted IdP backup was authenticated and its PG dump/archive structure
  checked off-cluster (not a full restore test). Native SPI provider/application,
  empty app operator group and admission bindings were created and read back;
  exact discovery issuer/RS256/S256 and frontend-only Secret/journal match verified.
- Git commits `793e053` and `a7def56` hold this child Application auto-sync and stage
  the native flag/mount/route. The live child hold was confirmed. Do not manually
  sync this incomplete desired state: the native image is not yet committed.
- The bounded drain attempt found logical owner/execution `15619` still active.
  n8n filtered lists can be transiently empty during Wait/resume; they are NOT
  idle evidence without direct SQLite owner/inflight/processing/paid readback.
- Operator error: a shell sequence submitted protected publication approval after
  the preceding drain assertion failed. Run `42716258046` was immediately cancelled;
  publish-and-deploy is cancelled, no robot image update occurred, hold remains
  active, and worker/frontend still run the original `eb830c98...` digest. Future
  approval must be inside the same fail-closed control flow as all verified gates,
  never a following unguarded shell command.
- The bounded maintenance attempt was closed by reactivating the same original
  workflow in place; its current execution/Wait was not cancelled, reset or replayed.
  Normal durable intake/new scheduling resumes. No model budgets/leases were reset.
- Next: obtain a stable complete natural drain, keep the Git-owned hold, capture
  private idle integrity/history readback, rerun standard CI publication with fresh
  guarded approval, verify the combined digest+flag+Secret revision, then release
  only the child hold and perform exact-digest/history/TLS/native-login acceptance.
  Until then HTTPS/native UI is NOT accepted as working.
