# traefik-edge VPN-transit backend Services (out-of-band providers)

The `traefik-edge` release renders four selector-less `Service` objects whose
endpoint addresses live outside every Helm render in this repository: they
point at the VPN-transit workload running natively on the `socrat-2` host
(wireguard mesh address `10.250.0.2`, declared in
`charts/traefik-edge/values.yaml` `backendIP`/`nodeName`). The rendered
objects pair each Service with a managed `EndpointSlice`
(`templates/services.yaml`) carrying that address; pods for them do not and
must not exist.

The four rendered Service names, their single reviewed backend address and
their published listeners are:

| Rendered object name | Port | Purpose |
| --- | --- | --- |
| `traefik-edge-panel` | 18082 | 3x-ui panel behind the Moscow IP allow-list middleware |
| `traefik-edge-subscriptions` | 12096 | client subscription endpoint (`/16a19nq48vtd/`) |
| `traefik-edge-subscriptions-json` | 12096 | JSON subscription endpoint (`/16a19nq48vtd-json/`) |
| `traefik-edge-trojan` | 32087 | Trojan transport endpoint (`/connect-4e15326936f20a7a4f2cac67`) |

Routing ownership and firewall history for these exact ports are recorded in
`docs/research/socrat-2-migration-plan.md`, `docs/records/handoffs/vpn-hardening-20261108.md`
and `docs/records/handoffs/moscow-vpn-transit-20261109.md`. The
`traefik-edge-trojan` Service is additionally consumed as an in-cluster
TCP-probe target by `charts/monitoring-k3s/values.yaml`.

Because the backing process runs on the host and not in any reviewed render,
the offline adjacency check cannot observe its pods; these four Services are
registered in the pinned provider registry (`ci/quality/providers/g2-edge.yaml`)
with this document as the naming evidence.
