# Router static mappings

The desired state for the home router is stored in [`ansible/vars/router-static-mappings.yml`](../ansible/vars/router-static-mappings.yml). It records the persistent WAN2 port forwards and DHCP reservations required by the Socrat nodes.

The managed recovery and web mappings are:

| Interface | Protocol | External port | Destination | Purpose |
| --- | --- | ---: | --- | --- |
| WAN2 | TCP | 80 | `192.168.0.250:80` | Home ingress VIP |
| WAN2 | TCP | 443 | `192.168.0.250:443` | Home ingress VIP |
| WAN2 | UDP | 51830 | `192.168.0.23:51830` | WireGuard peer `socrat-0` |
| WAN2 | UDP | 51831 | `192.168.0.24:51830` | WireGuard peer `socrat-1` |
| WAN2 | TCP | 2222 | `192.168.0.23:22` | Public recovery SSH for `socrat-0` |
| WAN2 | TCP | 2223 | `192.168.0.24:2222` | Public recovery SSH for `socrat-1` |
| WAN2 | TCP | 2224 | `192.168.0.23:2224` | SSH relay to `socrat-2` |

The DHCP reservations are `192.168.0.23` for `socrat-0` at `10:7c:61:08:33:76` and `192.168.0.24` for `socrat-1` at `38:d5:7a:e6:01:8b`.

The router is a Rotek RX-23302 at `192.168.0.1`. Its DHCP pool is `192.168.0.10`–`192.168.0.200`; the home ingress VIP `192.168.0.250` is outside it. WAN2 TCP 80/443 now target the VIP as listed above. Readback confirmed that the seven other live forwarding rules were preserved; unrelated rules are not reproduced in this managed subset. See [the HA runbook](k3s-ha.md) for deployment and verification.

The vendor interface is automated narrowly by `ansible/roles/home_ingress_ha/files/router_api.py`. It reads credentials as JSON on standard input and defaults to read-only inspection. Keep credentials in a private file outside the repository, not command arguments. Its `--apply --expected-old ADDRESS --destination ADDRESS` mode accepts only the two exact expected WAN2 TCP web forwards (`socrat-http` and `socrat-https`), verifies the complete rule set before and after each change, and preserves unrelated rules.

The router cannot edit forwarding destinations atomically. The helper deletes and recreates one rule at a time, briefly interrupting that port. If adding the replacement fails it attempts to restore the exact previous rule; if the second replacement fails, it also rolls back the completed first replacement. Inspect readback after errors: connectivity loss may prevent rollback. Reverse the expected and destination addresses to perform a guarded rollback. Do not restore UPnP reconciliation while static rules are authoritative.

After changes or a router restart, verify all recovery and web forwards and both DHCP reservations. From an external network, test WireGuard, TCP 2222 through 2224 and certificate-validated Rancher HTTPS. Keep direct VPS SSH as an independent recovery path. The VIP does not protect against router, home WAN or whole-home power failures.

The access point drops broadcast ARP from wired clients toward the Wi-Fi node. The home ingress helper sends directed ARP announcements for each physical node address and for the locally owned VIP to the router and peer every three seconds. Keep router and peer MAC addresses in inventory current after hardware changes. Five forced neighbor-cache clears recovered within three seconds; graceful keepalived handovers in both directions completed in under one second. No physical node shutdown was used in these tests.
