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
