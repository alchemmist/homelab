# WireGuard administrative access plan

Status: deployed on all three nodes and the administrator Mac on 2026-10-14.
The phases below retain the design and acceptance checklist; see deployment
status for completed checks and remaining restart/failure tests.

## Outcome

Make the administrator's Mac a fourth peer of the existing `wg-socrat` mesh, with independent tunnels to each node. There must be no mandatory single administrative gateway. Ordinary OpenSSH connects to per-node private DNS names on TCP 2222.

| Endpoint | WireGuard address | Proposed public UDP endpoint |
| --- | --- | --- |
| `0.socrat.alchemmist.xyz` | `10.250.0.1` | Home router port 51830 -> socrat-0:51830 |
| `1.socrat.alchemmist.xyz` | `10.250.0.3` | Home router port 51831 -> socrat-1:51830 |
| `2.socrat.alchemmist.xyz` | `10.250.0.2` | `176.98.185.59:51830` |
| Administrator Mac | `10.250.0.4/32`, subject to collision checks | Roaming client; endpoint learned by peers |

The UDP port choices are provisional until collision checks. They are WireGuard transport details, not SSH ports. Every target SSH endpoint remains port 2222.

The Mac config contains three peers, each with only its node address as AllowedIPs. Each node trusts the Mac public key for the Mac's /32. The Mac sends traffic directly to the appropriate node and keeps its normal Internet traffic outside this tunnel. Existing inter-node peer relationships remain intact.

## Availability semantics

- If socrat-2 fails, the Mac still connects directly to socrat-0 and socrat-1 while the home Internet connection works.
- If socrat-0 fails, the Mac still connects directly to socrat-1 and socrat-2. The router's mapping to socrat-1 must not require a process on socrat-0.
- If the home router or home Internet connection fails, home nodes are unreachable externally; the VPS remains independently reachable.
- This design does not automatically route traffic for a node through another peer when only its direct public endpoint fails. Native WireGuard chooses a peer by AllowedIPs; alternate-path selection is separate routing logic.
- If transparent transit failover is required in addition to independent direct access, design and test that as an explicit extension: health checks, alternate routes, forwarding, cryptokey routing, reverse routes and client integration. Do not assign the same destination prefix to several peers and assume automatic failover.

## Existing constraints

- The deployed interface is named `wg-socrat`.
- The Ansible role currently renders a full mesh of node peers, each with its own /32.
- This network also carries Flannel. Preserve current node addresses, private keys and inter-node connectivity.
- Endpoint selection must be per local node. The VPS must not depend on socrat-1's LAN endpoint `192.168.0.24:51830`; keep dynamically learned endpoints for peers behind NAT where appropriate.
- Existing public SSH access and `socrat-2-direct` remain recovery paths throughout rollout.
- Administrative WireGuard and the 3x-ui user VPN are separate systems. The pending user VPN migration is outside this plan.

## Phase 1: baseline and recovery

1. Record peers, public keys, endpoints, AllowedIPs, routes and firewall rules without exposing private keys.
2. Confirm the proposed Mac address and public UDP ports are unused, including peers or mappings not yet in inventory.
3. Inspect macOS routing and DNS with other VPNs active; resolve any overlap with `10.250.0.0/24` before rollout.
4. Verify direct VPS SSH and provider-console recovery.
5. Save configuration backups and baseline cluster readiness, pod DNS and cross-node connectivity checks.

## Phase 2: independent public WireGuard endpoints

1. Configure persistent router UDP mappings directly to socrat-0 and socrat-1, using separate external ports.
2. Preserve home LAN address reservations.
3. Verify VPS UDP 51830 is reachable from an external network.
4. Configure narrowly scoped host firewall access.
5. Verify the home mappings survive router restart and do not need socrat-0 to reinstall them. Prefer router-persistent rules over a sole renewal process on socrat-0.

## Phase 3: declarative client mesh

1. Add a separate administrative-client registry to Ansible with names, addresses and public keys.
2. Generate the Mac private key on the Mac and keep it outside Git and ordinary logs.
3. Add the Mac peer to all three nodes, with AllowedIPs `10.250.0.4/32`.
4. Generate a Mac profile with three peers and respective AllowedIPs `10.250.0.1/32`, `10.250.0.3/32`, and `10.250.0.2/32`.
5. Configure NAT keepalives where required.
6. Apply updates using the existing `wg syncconf` approach and verify OS routes.

No node acts as the Mac's mandatory transit gateway in this phase. Broad forwarding or SNAT is not needed for direct access to each node's own WireGuard address.

## Phase 4: redundant private DNS

1. Deploy identical host-level DNS records on all three nodes, independently of Kubernetes.
2. Bind resolvers to their WireGuard addresses and restrict TCP/UDP 53 to the management network.
3. Configure macOS split DNS for the node names with all three resolver addresses.
4. Preserve public and corporate DNS behavior; do not redirect unrelated public application names into this private zone accidentally.
5. Verify resolver failover rather than assuming that listing two servers is sufficient.
6. Define disconnected behavior: private node names must not silently resolve through the public wildcard and connect to a different SSH server.

The WireGuard Apple client currently applies DNS= servers to all DNS queries. Validate a separate narrowly scoped macOS resolver setup if unrelated DNS must remain unchanged.

## Phase 5: uniform SSH port

1. Use the existing staged SSH role to enable TCP 2222 on each node while retaining working ports during migration.
2. Verify existing host keys through trusted connections before accepting the new DNS names.
3. Test fresh authenticated sessions through all three direct WireGuard paths.
4. Keep independently tested public recovery SSH on the VPS.

## Phase 6: Mac setup and ordinary SSH

Install/import the protected WireGuard profile and private DNS configuration. Document how to remove them.

Test with SSH aliases and ProxyJump disabled, supplying keys explicitly where needed:

```bash
ssh -F /dev/null -i ~/.ssh/socrat-master -p 2222 alchemmist@0.socrat.alchemmist.xyz hostname
ssh -F /dev/null -i ~/.ssh/socrat-1 -p 2222 alchemmist@1.socrat.alchemmist.xyz hostname
ssh -F /dev/null -i ~/.ssh/personal_server -p 2222 alchemmist@2.socrat.alchemmist.xyz hostname
```

With suitable keys loaded in ssh-agent, the user only needs the username, DNS name and port. Existing SSH aliases can be migrated separately.

## Phase 7: acceptance

- Test from an external network, not only from the home LAN.
- Verify each direct peer handshake, expected server host key and ordinary SSH command.
- Confirm normal Internet routing and compatibility with other VPNs on the Mac.
- Confirm cluster node readiness, pod DNS and cross-node traffic have not regressed.
- In an agreed maintenance window, make socrat-2 unavailable and verify fresh DNS resolution and SSH to both home nodes.
- Make socrat-0 unavailable while the router and socrat-1 remain online; verify fresh access to socrat-1 and socrat-2.
- Test each DNS resolver's failure independently.
- Verify persistence across reconnect, sleep/wake and appropriate node/router restarts.
- Confirm Ansible is idempotent.

Use path-specific isolation where practical. Full node outages and router reboots require a maintenance window because existing production services depend on them.

## Phase 8: cleanup and rollback

After acceptance and an agreed observation period, decide separately whether to retire old public SSH forwards and the socrat-0 SSH relay. Preserve independent recovery access.

Rollback restores only managed peer, firewall and DNS settings and removes the Mac tunnel and private resolver configuration. Do not flush the firewall or regenerate node private keys.

Document provisioning of future nodes and administrator devices, including keys, addresses, UDP reachability, DNS records and failure tests.

## References

- WireGuard cryptokey routing: https://www.wireguard.com/#cryptokey-routing
- WireGuard NAT keepalives: https://www.wireguard.com/quickstart/
- WireGuard Apple DNS behavior: https://git.zx2c4.com/wireguard-apple/tree/Sources/WireGuardKit/PacketTunnelSettingsGenerator.swift
- OpenSSH options: https://man.openbsd.org/ssh_config

## Deployment status — 2026-10-14

The official macOS WireGuard app has the active `wg-socrat-admin` profile.
The Mac has `10.250.0.4/32` and independent peers for all three nodes.
Only the three node /32 routes are installed by this profile; it has no default
route and no `DNS=` setting. Existing VPN resolvers remain present.

All three nodes now run enabled host-level `homelab-private-dns.service` and
`wg-socrat-admin-firewall.service`. SSH listens on TCP 2222, with TCP 22 retained
for recovery. The administrative peer is restricted to SSH 2222, DNS 53, and private HTTPS
443 delivered to the node-local Syncthing proxy. Raw GUI/proxy ports and transit
to other networks are not permitted by the administrative firewall. See
`syncthing-private-ui.md` for the HTTPS routing and authentication configuration.

Live checks from the Mac passed for SSH to all three private DNS names using
`-F /dev/null` and explicit identity files. All three names resolve to their
expected WireGuard addresses. UDP and TCP DNS queries succeeded against each
of the three resolvers. The unittest suite completed with 44 tests, one skipped.
Existing `socrat-0`, `socrat-1`, and `socrat-2`
SSH aliases still work. All three Kubernetes nodes report Ready.

Router mappings are persistent static WAN2 rules. Their declarative reference
is `ansible/vars/router-static-mappings.yml`; application through the vendor
interface remains manual, as described in `router-static-mappings.md`:

| External port | Destination | Purpose |
| --- | --- | --- |
| UDP 51830 | 192.168.0.23:51830 | Direct WireGuard peer socrat-0 |
| UDP 51831 | 192.168.0.24:51830 | Direct WireGuard peer socrat-1 |
| TCP 2222 | 192.168.0.23:22 | Preserved public recovery SSH |
| TCP 2223 | 192.168.0.24:2222 | Preserved public recovery SSH |
| TCP 2224 | 192.168.0.23:2224 | Preserved SSH relay to socrat-2 |

The former UPnP reconciliation service/timer on socrat-0 are stopped and disabled;
the compatibility relay socket remains active. The VPS also retains direct
public SSH on 22 and 2222. The public recovery mapping to socrat-0 still targets
22 intentionally during the compatibility period; private WireGuard SSH uses
2222 on every node.

The Mac profile is stored at
`~/Library/Application Support/WireGuard/Configurations/wg-socrat-admin.conf`
with private permissions. Import it through WireGuard's **Import tunnel(s)
from File** menu and activate it in the app. Opening the file with `open -a`
does not import it. Never commit this profile or its private key.

The default `wireguard_admin_dns_mode: split` installs one resolver at
`/etc/resolver/socrat.alchemmist.xyz`, listing 10.250.0.2, 10.250.0.3 and
10.250.0.1. It covers every subdomain, including future internal services,
while unrelated DNS stays with the existing network or corporate VPN.
Existing per-host resolver files are preserved during migration. Ansible
maintenance access is available through `inventory/direct.yml` alongside
`inventory/hosts.yml`.

Alternatively, `wireguard_admin_dns_mode: system` writes these DNS servers into
`DNS=` in the generated WireGuard profile and skips macOS resolver installation.
Import the updated profile once and reconnect to activate it. This mode sends
ordinary DNS through Socrat's private resolvers, which forward public queries
upstream. The Apple client treats this as global DNS, not suffix-only DNS;
use the default split mode when another VPN must retain its DNS configuration.
Changing mode does not remove existing resolver files automatically.

WireGuard does not push DNS settings from a server to existing clients. Each
client needs a one-time profile update or suffix resolver installation; adding
another service afterward requires only central DNS and gateway configuration.
DNS selects the private address; HTTPS certificates and private gateway routes
are configured separately on the servers.

Still pending acceptance: controlled resolver-failure tests, reconnect and
sleep/wake checks, and persistence checks after node/router restarts. No
production nodes or router were deliberately rebooted for these checks.

## Reapply the deployed configuration

Install Ansible and `wireguard-tools` on the controller. Install the official
WireGuard macOS application separately. Run these commands from `ansible/`:

```bash
ansible-playbook playbooks/wireguard-admin-client.yml --tags prepare
ansible-playbook playbooks/wireguard-admin-access.yml -i inventory/hosts.yml -i inventory/direct.yml --ask-become-pass
ansible-playbook playbooks/wireguard-admin-client.yml --tags dns --ask-become-pass
ansible-playbook playbooks/ssh-gateway.yml -i inventory/hosts.yml -i inventory/direct.yml
```

The server playbook deliberately uses the independent maintenance endpoints
in `inventory/direct.yml`; it does not depend on the new private DNS or Mac
tunnel working. SSH listeners are managed separately by `playbooks/ssh.yml`;
`homelab_ssh_preserve_ports: [22]` keeps the current recovery endpoints working.
For first-time port migration, use the staged procedure in `node-bootstrap.md`
with a maintenance inventory whose final endpoint is 2222 and bootstrap port 22.

Profile preparation preserves the existing Mac key and shows its public key.
For a new Mac, add that public key and a unique address to
`wg_socrat_admin_clients` before applying the server playbook; the current
registry describes this Mac only. Re-import the generated profile in the app
if its contents change. Ansible does not automate Apple's VPN approval dialog.

Use the explicit `-i` SSH commands in Phase 6. Public-key authorization on a node
does not make OpenSSH automatically select an arbitrarily named private key:
`~/.ssh/socrat-master`, `~/.ssh/socrat-1`, and `~/.ssh/personal_server` are selected
by the old aliases only. The private DNS names have no identity selectors in
the SSH client configuration. This deployment therefore keeps the user's
explicit-key connection workflow.

After the reported YouTube failure, the Mac profile was stopped and started
through `scutil --nc` for an A/B check. YouTube TLS timed out in both states;
Google and example.com succeeded in both states. The YouTube route stayed on
the existing `yteam` OpenVPN tunnel, and ChatGPT used the separate Splitty path.
WireGuard was restored and all three private SSH connections passed again.
This check does not establish the upstream cause of the YouTube failure.
