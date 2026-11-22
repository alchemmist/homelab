# NetBird stage4 — management readiness and scoped TLS entry

## Bounded milestone 1 (2026-11-02)

Investigated the pinned upstream v0.82.0 combined implementation before changing
readiness. `combined/cmd/root.go:startServers` (381–410) starts metrics, the relay
health checker and STUN but **never calls relay `Server.Listen`**. Its relay WS
handler instead invokes `RelayAccept` on the management multiplexer.
`relay/server/server.go:Listen` alone populates `listeners`; `ListenerProtocols`
reads that slice. `relay/healthcheck/healthcheck.go:validateListeners` requires a
nonempty slice, so this generic checker is permanently unhealthy in combined
mode, independently of certificates. It also dials the public relay address and
sets `certificate_valid=false` on *any* connection failure. That flag is not proof
of a certificate defect. This is a pinned upstream combined-health integration
defect, not fixed by adding a certificate or treating management 200 as relay OK.

Readiness now checks the actual embedded OIDC discovery endpoint on management
port 80. This checks management/IdP HTTP availability, **not relay/STUN readiness**.
The relay checker remains available on port 9000 and is not rewritten or forced
healthy. Liveness is unchanged. Separate authenticated relay/STUN end-to-end
acceptance is required before claiming usable VPN. No peers, setup keys or policy
grants were created.

Before the exact readiness JSON patch, the live deployment, runtime secret,
configmaps, services, ingresses, NetworkPolicy and PVC JSON were saved privately
with exclusive creation and mode 0600 to remote journal
`stage4-readiness-baseline.json`. Patch tested the current resourceVersion and
retained deployment UID `5acdd79c-9e12-48cd-86cb-9fa924212509` in namespace UID
`0933b181-1409-4394-a2c6-87d90cb97949`. Rollback scope is only the readiness
httpGet field from that baseline (with fresh precondition), never broad restore.

Actual readback at 17:57 UTC: server Ready=true; discovery 200 with exact approved
issuer; technical PAT GET accounts/users/identity-providers/peers/setup-keys/
policies/instance all 200. Exact Authentik connector unchanged. Peers/setup keys/
policies remain zero. Relay `/health` still 503 with listeners=null; **relay not
accepted**. Readback private: `stage4-readiness-readback-api.json`.

Publication/local-auth change and actual personal owner OIDC login are separate
subsequent acceptance gates; this milestone did not perform them.

## Bounded milestone 2 — private auth-off and prepared TLS

- After private connector readback, changed only runtime
  `server.auth.localAuthDisabled: true`, preserving all secret fields. Secret
  baseline `stage4-authoff-secret-before.json` and original local config are
  private; no secret was printed. Restarted only NetBird server. Actual post-
  restart account settings confirm local auth disabled, server Ready, and the
  existing technical one-day PAT still gets all seven native API collections
  with 200. This proof precedes any public application Ingress.
- Added a uniquely named `netbird-edge-forwarder` Deployment/ConfigMap/Service
  in **identity**, already watched by both home and public-edge controllers.
  Runtime secret stays in unwatched **netbird-pilot**. No watch, RBAC, Traefik
  global restart, CRD, Argo namespace or label transport changes.
- Exact old NetworkPolicy spec was checked against private baseline before a
  resourceVersion-guarded replacement of that single spec. HTTP allows only
  combined identity-namespace + forwarder-pod selectors and existing kubelet/
  loopback source CIDRs. Port 9000 was narrowed to those probe sources. No
  arbitrary pod HTTP, NodePort or UDP/STUN publication.
- The first server-side apply stopped on old `kubectl-create` ownership of
  `.spec.ingress`; no force-conflicts used. A subsequent new forwarder failed
  startup with a concrete Traefik validation error: `http2 cannot be a standalone
  element`. Removed unsupported empty `http2: {}` from static config; retained
  native h2c backend transport. Restarted only this new forwarder; now Ready.
- Explicitly deny public setup/invites and local-password/signup prefixes.
  Through the pod's non-loopback address, actual GET setup and local/login are
  403. Loopback port-forward is deliberately allowlisted by this preexisting
  middleware; its claimed setup returns native 404, not evidence of middleware
  denial. PAT accounts through loopback forwarder 200, local-auth flag true,
  grants remain empty. This distinction was investigated rather than hidden.
- Dedicated Certificate `identity/netbird-pilot-tls`, ClusterIssuer
  `letsencrypt-http01`, is now **Ready**. cert-manager's standard HTTP01 solver
  Ingress was permitted before application Ingress; no staged application route
  was published for issuance. TLS private key stays in identity.
- DNS required all **three** authoritative host renderers, not just socrat-0.
  Read-only discovery found identical initial hash
  `bac6858f7c232a293cb5b55f26fc15c2cf0319abfe1b9fad275e864750e0e6c6`
  including concurrent `bot.socrat` absent from this worktree. Captured private
  per-host originals. Three bounded owner-admin Jobs used a pinned existing
  installer image, exact hash guard and atomic own-file rename; no host PID,
  chroot, elevated capabilities, systemd edits or SSH/sudo changes. Only
  `netbird.socrat` was inserted. All final hashes
  `aebdbbb112f589e1c92fb8e15c4b7bb8d3648b976d9263f2a0c651c01e79999d`.
  Existing refresh timers rendered/reloaded normally. Both public authoritative
  addresses now return both approved home/VPS A records. Do not apply this older
  worktree's whole renderer over the concurrent bot change.
- Private identity baseline was captured before writes in
  `stage4-identity-before.json`; no broad restore. Rollback removes only new
  named entry objects and own DNS line under fresh hash guard, and restores only
  changed runtime/probe/NetworkPolicy fields under fresh resourceVersion tests.
- Added a one-shot, default-read-only native owner handover script. It requires
  exact canonical base64 protobuf raw owner UUID + exact connector, independently
  checks exact email, recent real login and account state, and refuses email or
  alternate UUID selection. It has **not** been applied: actual owner login is
  still a human acceptance gate. No watcher, owner password/MFA access, user
  creation, DB edits, setup key or native human role grants.

Tests before application publication: `/tmp/homelab-iam-tests/bin/python -m
pytest -q tests/test_netbird*.py`: **63 passed, 1 skipped, 97 subtests passed**.

## Bounded milestone 3 — published and actually verified

`https://netbird.socrat.alchemmist.xyz/` is live. Application Ingresses were
created only after the final private publication gate confirmed local-auth-off,
all seven PAT collections 200, server Ready and Certificate Ready.

- Standard identity Ingress `netbird-http` UID
  `63278b52-6f67-41ac-bbc6-3b7ec69690d8` and `netbird-grpc` UID
  `e9d7c989-e29c-4478-bcdb-151dcd5f8b2c`. Both select **only** the exact approved
  NetBird host, dedicated `netbird-pilot-tls`, and uniquely named forwarder
  Service. No Grafana selector, shared default TLS store/cert, rename or deletion
  exists in the applied delta. Existing controllers were not restarted.
- After initial controller certificate propagation, **both** approved public IPs
  passed normal trusted curl verification (`ssl_verify_result=0`), dashboard 200,
  OIDC discovery 200 and exact issuer. Certificate public issuer **Let's Encrypt
  YR2**, exact SAN, validity 2026-11-02–2027-01-31. No TLS bypass was used, including
  during the initial transient trust failure.
- On both entrances: setup (exact, trailing slash and query), invitations,
  local login, signup and register all **403**. Setup/invites POST with spoofed
  `X-Forwarded-For: 127.0.0.1` also **403**. Instance returns
  `setup_required=false`. Anonymous setup-key collection correctly **401**, not
  exposed without native authentication.
- Final PAT collection check caught the inherited rule's concrete prefix bug:
  `PathPrefix(/api/setup)` unintentionally also denied `/api/setup-keys`.
  Stopped at that 403, inspected the exact path, captured a fresh private
  ConfigMap baseline, and narrowed denial to **exact setup plus slash-descendants**.
  Local-password/signup denial is unchanged. This does not create a setup key or
  grant unauthenticated access. Now all seven public PAT collections return 200;
  peers/setup keys/policies remain empty. Added regression assertions.
- Fresh anonymous Chromium (normal trusted TLS; no storage state, credentials or
  impersonation) actually navigated dashboard → `/oauth2/auth` → exact connector
  `/oauth2/auth/authentik-dbkcr0p119kc73917k1g` → Authentik authorize → default
  Authentik login flow. Exact callback verified; no request failures; only
  Authentik **Log in**, no signup link or NetBird local option. The password input
  belongs to **Authentik**, not NetBird local auth. Browser check source:
  `scripts/netbird-public-browser-check.py` (Playwright in `/tmp/hugo-oidc-venv`).
- Independent transport test `scripts/netbird-transport-check.py` used the
  private existing relay key only in memory to generate 60-second tokens. Two
  transient raw relay sessions, one through each TLS entrance, authenticated and
  exchanged a random nonce **bidirectionally across entrances**, then closed.
  No management peer enrollment, WireGuard interface, route or grant occurred.
  Separate public STUN binding transactions on UDP 3478 got **no response on
  either entrance**. STUN remains not available; **not a usable VPN**.
- Final private management readback: Ready=true; discovery 200; all PAT native
  APIs 200; local_auth_disabled=true; connector unchanged; only technical owner;
  peers/setup keys/policies=0. Generic relay `/health` is still **503** with
  **listeners=null, certificate_valid=true**. This directly demonstrates the
  pinned combined listener-reporting defect even after real relay TLS/payload
  success; management 200 was never substituted for relay proof.
- Compared all **88** preexisting identity Deployment/Service/Ingress/Certificate/
  ConfigMap/NetworkPolicy objects: original UID, spec and data equal. No changes
  to old identity workloads, certificate specs, provider config or factors.
  All three completed DNS installer Jobs/pods were deleted by their exact new
  names; no watcher or active background job remains.

Sanitized actual matrix/browser/transport evidence: `deploy/netbird/public-stage4.json`.
Private final readbacks: `stage4-final-private-readback.json`,
`stage4-final-readiness-api.json`, `stage4-transport-check.json`; PAT remains only
in the original private bootstrap journal and expires after its original one day.

### Old-app exception — explicitly NOT a pass

Initial plain-DNS anonymous baseline was Authentik 302, Grafana health 200,
Argo health 200. Final explicit home/VPS checks preserve trusted Authentik 302 and
Argo health 200. **Grafana now fails trusted TLS on both entrances**, presenting
a default certificate. Read-only inspection found **no Grafana Ingress anywhere
in the cluster**, although its private certificates remain. Shared Traefik pods
are unchanged (edge >2h old, home >2d old), not restarted by this task. There is
no demonstrated link to this uniquely named, host-scoped NetBird delta; existing
identity objects remain equal. Concurrent work is present. Supervisor instructed:
**preserve current privacy state; do not recreate Grafana routing or blanket
rollback NetBird**. This is recorded as concurrent/unattributed and must be
investigated by the parent; do not claim all old-app anonymous health passed.

### Human acceptance and exact native handover — NOT performed

The owner must personally open the published URL and complete genuine Authentik
login/MFA. This task did **not** log in as the owner, grant any native human role,
merge email identities or edit a database. The handover script's actual read-only
run **refused** because the exact personal identity is not yet present.

The tested script is installed owner-private on socrat-0:
`~/.local/state/netbird-internal-stage/owner-handover.py`. After genuine personal
login, the parent can run this read-only plan on that host:

```sh
python3 ~/.local/state/netbird-internal-stage/owner-handover.py \
  --subject CiQ5ZTMzODc3YS0zZWFhLTQ1NDEtOThlYi04Y2RjMTAwODhlZjYSHmF1dGhlbnRpay1kYmtjcjBwMTE5a2M3MzkxN2sxZw
```

Only after the successful plan and owner confirmation, append:
`--apply --confirm-personal-login-and-native-transfer`.

The canonical subject is raw UUID `9e33877a-3eaa-4541-98eb-8cdc10088ef6` + exact
connector `authentik-dbkcr0p119kc73917k1g`, encoded as upstream Dex base64 protobuf.
No email/other-UUID fallback. Script separately requires exact mapped email,
recent active personal login, no service user, single technical owner/account,
local auth off and empty grants. PUT is attempted once; native API atomically
makes that actual identity owner and demotes technical owner to admin. The
script verifies those exact roles and refuses other user/role changes. PAT is
never printed, redirected or included in arguments. No watcher; do not retry a
failed mutation blindly. Expired PAT is a stop gate, not reason to enable public
local passwords. No code was pushed.
