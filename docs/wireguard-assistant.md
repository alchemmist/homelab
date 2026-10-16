# Assistant WireGuard access

The `assistant` entry in `wg_socrat_admin_clients` assigns `10.250.0.6/32` to
public key `RdRir+QQhVg9aSwGNmBcvSKDak7gQyuaYfJx8KDgXB4=`. Its private key
was generated in the user's WireGuard application and is not in this repository.

Apply registration from `ansible/` with `playbooks/wireguard-admin-peers.yml`.
Use the normal inventory and suitable private per-host escalation credentials.
The play targets only the three public entry points, applies the shared admin
firewall before activating peers, and synchronizes WireGuard without restarting
interfaces. The original administrator peer and worker mesh remain configured.

The client profile uses these independent peers:

| Node | AllowedIPs | Endpoint |
| --- | --- | --- |
| socrat-0 | 10.250.0.1/32 | socrat.alchemmist.xyz:51830 |
| socrat-1 | 10.250.0.3/32 | socrat.alchemmist.xyz:51831 |
| socrat-2 | 10.250.0.2/32 | 176.98.185.59:51830 |

Use their public keys from inventory and PersistentKeepalive=25. The client
Interface has Address=10.250.0.6/32 and the original private key matching the
registered public key. The generated local `socrat-assistant.conf` is a template:
replace its PrivateKey placeholder before importing or sharing. Exporting the
original tunnel after replacing its other settings also preserves the key.
Do not use the same peer simultaneously on two devices.

There is no default route and no global DNS setting. Existing private DNS
servers have static local records and no public forwarder: putting them in
WireGuard's global DNS field would break ordinary DNS. For macOS private
names, create `/etc/resolver/0.socrat.alchemmist.xyz` (and equivalent files for
1 and 2) containing:

```text
nameserver 10.250.0.2
nameserver 10.250.0.3
nameserver 10.250.0.1
timeout 6
options attempts:1
```

SSH on these entry points uses TCP 2222 and still requires separate SSH
credentials. The firewall also permits private DNS and the configured private
HTTPS endpoints. Transit to other networks is denied. Socrat-3 has no public
WireGuard endpoint; SSH access to it uses an authorized jump-host login on
socrat-0, targeting 10.250.0.5:22, as with the current administrator's SSH alias.

Registration and firewall deployment were verified on all three entry points.
A client handshake cannot be verified until the user imports the completed
profile and activates it; the server does not possess the client private key.
