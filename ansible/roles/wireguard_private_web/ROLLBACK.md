# Private WireGuard web NAT rollback

The managed service owns only the `ip homelab_private_web` nftables table. Set
`wireguard_private_web_enabled: false` in inventory, disable the service, and
remove that table explicitly when rolling back:

```sh
systemctl disable --now wireguard-private-web.service
nft delete table ip homelab_private_web
```
