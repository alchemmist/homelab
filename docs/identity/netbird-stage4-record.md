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
