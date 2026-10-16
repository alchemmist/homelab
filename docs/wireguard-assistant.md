# Tim phone access to all Socrat nodes

The current ready-to-import profile is `socrat-tim.conf`, stored privately in
the operator's Downloads directory. It has its own key pair and address
`10.250.0.7/32`, registered as `tim-phone` in `wg_socrat_admin_clients`.
The private key is present in that local file, not in this repository.
Disable the older tunnel before importing and enabling the replacement.

The profile contains independent peers for socrat-0, socrat-1 and socrat-2.
Socrat-0's AllowedIPs includes both `10.250.0.1/32` and `10.250.0.5/32`.
The other peers cover `10.250.0.3/32` and `10.250.0.2/32`. There is no default
route: ordinary Internet traffic remains on the phone's normal connection.

On socrat-0, the shared administrative firewall permits only the explicit
forwarding rule from Tim's `.7` address to socrat-3 `.5`, TCP2222. A scoped
SNAT rule translates its source to socrat-0's `.1` address, which socrat-3's
existing WireGuard peer already accepts. Replies are translated back by
conntrack. This avoids adding conflicting AllowedIPs on socrat-3. Other
forwarded destinations and ports remain denied. The original administrator
and cluster peer rules remain in place. The gateway's IPv4 forwarding is
persisted, and the owned firewall chains are replaced through reload.

The client uses DNS `10.250.0.2`, `10.250.0.1`, `10.250.0.3`. Each private
resolver contains exact records for all four nodes, including socrat-3.
Public names are forwarded to explicit upstreams `1.1.1.1` and `9.9.9.9`;
the servers still listen only on their WireGuard addresses and retain the
administrative source-IP firewall. This makes the profile usable on a phone
without macOS-specific resolver files or broken public DNS resolution.

## Haven settings

Use username `tim`, TCP port2222 and Tim's SSH key named `phone` for every
host. Disable Jump Host in these profiles:

| Host | Private address |
| --- | --- |
| 0.socrat.alchemmist.xyz | 10.250.0.1 |
| 1.socrat.alchemmist.xyz | 10.250.0.3 |
| 2.socrat.alchemmist.xyz | 10.250.0.2 |
| 3.socrat.alchemmist.xyz | 10.250.0.5 |

WireGuard and SSH keys are separate. The registered SSH fingerprint is
`SHA256:AvFh805CQs8+HBJvjHrUWPtAn5mINCaQr7Wuo42jvBQ`. The existing older SSH
key remains authorized. Tim has no sudo rights. Authentication on socrat-3
is still performed by socrat-3; the gateway provides only network forwarding.

## Provisioning

From `ansible/`, apply `playbooks/wireguard-tim-client.yml` with the normal
inventory and the existing per-host administrative escalation credentials.
The play persists gateway forwarding, applies the shared firewall and WG
roles on the three public entry points, and refreshes all private resolvers.
It does not restart the WireGuard interfaces or reconfigure other desktops.

`files/verify_wg_client.py` runs on the gateway with root privileges, a private
profile path, and a JSON mapping of addresses to independently trusted SSH
public host keys. It creates a disposable network namespace and uses the
new client's actual cryptographic identity. Only the gateway/local peer
underlay endpoints are substituted to avoid router hairpin dependencies;
inner routes, client address, firewall and NAT are exercised unchanged.
It checks four distinct SSH identities, all private node DNS records,
public UDP/TCP DNS, and denial of an unrequested forwarded port. Namespace,
interface and temporary copied credentials are removed after verification.
This does not replace final import testing in the phone application.

## Legacy profile

The older `assistant` peer at `10.250.0.6` is retained during migration. Its
old `socrat-assistant.conf` has no phone DNS setting or direct route to
socrat-3. Do not confuse it with the new ready profile. The operator's
`antonmoss-mac` peer remains at `10.250.0.4`.
