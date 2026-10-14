# Router static mappings

The desired state for the home router is stored in [`ansible/vars/router-static-mappings.yml`](../ansible/vars/router-static-mappings.yml). It records the persistent WAN2 port forwards and DHCP reservations required by the Socrat nodes.

The current mappings are:

| Interface | Protocol | External port | Destination | Purpose |
| --- | --- | ---: | --- | --- |
| WAN2 | UDP | 51830 | `192.168.0.23:51830` | WireGuard peer `socrat-0` |
| WAN2 | UDP | 51831 | `192.168.0.24:51830` | WireGuard peer `socrat-1` |
| WAN2 | TCP | 2222 | `192.168.0.23:22` | Public recovery SSH for `socrat-0` |
| WAN2 | TCP | 2223 | `192.168.0.24:2222` | Public recovery SSH for `socrat-1` |
| WAN2 | TCP | 2224 | `192.168.0.23:2224` | SSH relay to `socrat-2` |

The DHCP reservations are `192.168.0.23` for `socrat-0` at `10:7c:61:08:33:76` and `192.168.0.24` for `socrat-1` at `38:d5:7a:e6:01:8b`.

This file is a declarative desired-state reference. The router does not expose a supported automation interface in this repository, so Ansible does not apply these entries. Apply changes through the router's persistent static WAN2 configuration, then update the YAML and verify that the live rules match it. Do not restore the old UPnP reconciliation service while these static rules are authoritative.

After a router restart, verify that all five forwards and both DHCP reservations remain present. From an external network, test UDP reachability for WireGuard and TCP reachability for ports 2222 through 2224. Keep the VPS SSH endpoint as an independent recovery path.
