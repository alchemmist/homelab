# Happ on socrat-3

Install the pinned client and desktop launcher with `ansible/playbooks/socrat-3-happ.yml`, using both the main inventory and `ansible/inventory/socrat-3.yml`.

Import the private Socrat subscription in Happ. Subscription credentials are not stored in this repository.

Use these desktop settings:

- System proxy: enabled.
- TUN: disabled.
- HTTP inbound: enabled, port `10809`.
- SOCKS inbound: port `10808`.
- Connections from LAN: disabled.

These application preferences and the subscription are configured in Happ, not provisioned by the playbook. Firefox uses the desktop system proxy. Applications that ignore system proxy settings need their own proxy configuration.

The playbook installs a `happd` systemd override that removes `CAP_NET_ADMIN` and `CAP_NET_RAW` and enables `NoNewPrivileges`. This prevents the desktop VPN daemon from changing the node's network routes. TUN is intentionally unsupported with this override: the node also runs WireGuard and Kubernetes, which must remain reachable independently of Happ.

Verify local proxy listeners, the browser, and node connectivity after connecting:

```sh
ss -ltn | grep -E '127.0.0.1:10808|127.0.0.1:10809'
curl --max-time 15 --socks5-hostname 127.0.0.1:10808 https://api.ipify.org
ip rule
ping -c 2 10.250.0.1
```

Open ChatGPT in Firefox for the browser check; an HTTP 403 from command-line curl alone does not establish whether the browser can open the site. Check that socrat-3 remains Ready from another cluster node. Do not enable TUN as a connectivity test.
