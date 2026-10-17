# Private Rancher access

Rancher is available at `https://rancher.socrat.alchemmist.xyz` through the
`socrat-wg` network. Its own login and authorization remain enabled.

Private DNS on `10.250.0.1`, `10.250.0.3`, and `10.250.0.2` returns both
`10.250.0.1` (socrat-0) and `10.250.0.3` (socrat-1). Each address terminates
trusted HTTPS and proxies to the Rancher Kubernetes Service. Rancher retains
two replicas, one on each home control-plane node. DNS provides both gateways;
client retry behavior determines how quickly a client uses the other address
when a gateway disappears. This is not health-aware DNS failover.

The existing macOS split resolver for `socrat.alchemmist.xyz` covers Rancher.
Other clients must use the private DNS servers through WireGuard. WireGuard
itself does not push DNS settings to existing clients.

## Apply and verify

From `ansible/`, run:

```sh
ansible-playbook playbooks/rancher-private-access.yml --ask-become-pass
```

The playbook provisions the certificate and both private gateways, verifies
HTTPS, enables pod access, publishes private DNS, replaces the public ingress
health probe, checks Rancher self-access, then disables the public Helm ingress.
It preserves installed chart versions, existing gateway settings and credentials.
`playbooks/rancher.yml` also keeps the public ingress disabled and imports this
configuration.

From the repository root:

```sh
python3 scripts/check-rancher-private.py
```

The check verifies replica placement, private DNS, trusted HTTPS and authenticated
Kubernetes node lists through both gateways, pod self-access, and public HTTP/HTTPS
404 responses, including a forged private `X-Forwarded-For` header. It does not
stop nodes or simulate power loss.

## Routing and certificates

The Syncthing private gateway hosts `rancher-0` and `rancher-1` use the independent
`syncthing/rancher-private-tls` certificate. Proxy configuration preserves Rancher
Authorization headers and WebSockets. Only the WireGuard and Kubernetes pod
networks are allowed for these virtual hosts. Existing Grafana and other virtual
hosts retain their own access rules.

A narrow nftables rule permits same-node pod traffic from `cni0`, source
`10.42.0.0/16`, to that node's WireGuard address on port 443 to reach the private
18443 listener. It does not redirect traffic arriving on LAN/public interfaces.
CoreDNS has an exact Rancher zone, preserving other custom zones. Cert-manager
uses public recursive DNS for HTTP01 propagation checks so the private DNS answer
does not interfere with certificate renewal. Temporary public ACME challenge
routes are allowed; the Rancher application has no public ingress.

The authoritative public DNS wildcard still resolves this hostname to the home
public IP. Public application requests return Traefik's default 404; this setup
does not claim public DNS NXDOMAIN. Removing wildcard DNS matches requires a
separate change at the DNS provider and consideration of HTTP01 renewal.

The public home ingress VIP continues serving other services and ACME challenges.
Its health probe checks the local Kubernetes API and the local Traefik default
404 response, independently of Rancher.

## Cluster dashboard layout

Rancher 2.15's Events tab uses `min-width: fit-content`; long event names and
image digests can expand the entire cluster dashboard beyond the viewport.
The private gateway injects a narrowly scoped stylesheet that lets the Events
container shrink and wraps long table-cell content. It does not hide horizontal
overflow or truncate event messages, and it does not affect other Rancher tables.

The CSS is defined by `rancher_wg_response_style` in socrat-0 inventory variables
and applied to both Rancher gateways. HTML requests disable upstream compression
so NGINX can insert the stylesheet; other requests preserve content negotiation.
To reconcile the gateway without rerunning DNS or ingress migration:

```sh
cd ansible
ansible-playbook playbooks/rancher-ui.yml
```

The upstream rule is in
[Rancher 2.15 Tabbed/index.vue](https://github.com/rancher/dashboard/blob/release-2.15/shell/components/Tabbed/index.vue).
Review this compatibility override after upgrading Rancher.
