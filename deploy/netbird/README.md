# NetBird control plane and machine peers

**Current deployment and failure-test limits:**
[four routing peers and independent relays](../../docs/netbird-independent-access.md).
Five peers (owner + four existing nodes), genuine owner-only admin JWT source,
no All grants. Existing-client data-plane service-outage tests passed; restarting
the client without management failed. Do not claim full HA or retire legacy WG.
The staged gates and machine-stage5 state below are historical inputs.

**Historical continuation:** [STUN + Kubernetes machine peers](../../docs/netbird-kubernetes-machine-peers.md),
[`machine-stage5.json`](machine-stage5.json). Control plane is installed and
OIDC-only. STUN-only coturn on existing socrat-2 is externally and host-origin
Binding-tested; machine enrollment remains blocked on genuine JWT groups.
`netbird-stun.py` renders the bounded live STUN listener; `netbird-host-peer.py`
renders **zero-replica** direct-overlay peers, not routed Networks. The legacy
proposal/gates below remain historical inputs, not a live-state assertion.

[Русский runbook, blockers и acceptance](../../docs/netbird-user-access-pilot.md).

- `pilot.inputs.json` records the approved FQDN `netbird.socrat.alchemmist.xyz`.
  Every other deployment field and every review gate stays empty or false.
- `candidates.json` records repo candidates `traefik` and `local-path` with
  `verified: false`. Grafana and socrat-2 SSH are approved and not deployable.
  Router mode is existing-node, placement is unresolved, and the groups claim is not verified.
- `runtime-audit.json` is the 2026-11-02 read-only SSH observation. It is not a
  passing review.
- `traefik-scope-delta.json` describes the one namespace watch addition. It does
  not edit `charts/traefik-edge`, because that Argo application self-heals.
- `images.lock.json` pins NetBird 0.82.0 and reuses the chart's Traefik digest
  for the edge forwarder. The forwarder digest was not re-verified at the registry.
- `../../scripts/netbird-pilot.py` compiles manifests and runtime config. It does
  not apply them.
- `../../scripts/netbird-deploy.py` is `check`, `plan`, and `apply`. Apply needs
  an explicit context and the confirmation phrase, never calls Argo, and refuses
  the current repo inputs.
- `../../scripts/netbird-bootstrap.py` claims `/api/setup` only on loopback.
- `../../scripts/netbird-backup.py` plans a quiesced SQLite copy. It is not HA.

Community management stays one replica and can be planned without routers.
Existing-node router mode is allowed only after an explicit review. This repo does
not generate or install those routers, and `router_compose` must not be applied to
socrat-0..3.
