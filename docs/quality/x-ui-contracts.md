# x-ui VPN gateway contracts

The x-ui release (`charts/x-ui`, Deployment `x-ui`) is a host-network VPN/panel
gateway. Both pinned 3x-ui images start `/app/DockerEntrypoint.sh` with no
non-root image user and run xray/x-ui with host network configuration.

- `host-network`: panel and proxy listeners intentionally bind the node's public
  addresses on the host network; the node firewall owns that boundary.
- `run-as-non-root`: the entrypoint configures iptables/fail2ban rules, writes
  log/jail configuration and starts the VPN services, which requires root.
- `drop-net-raw-capability`: the VPN data plane and firewall/fail2ban behavior
  require NET_RAW alongside NET_ADMIN; dropping it would break that function.
- `writable-host-mount`: the host `/etc/x-ui` database, certificate and acme.sh
  directories are the persistent configuration/certificate stores for the
  gateway, not arbitrary host access. The optional `/usr/local/x-ui/bin`
  runtime directory is the intentionally persistent xray binary mount.
- `no-read-only-root-fs`: the entrypoint creates log directories and writes
  fail2ban configuration under /var/log and /etc, in addition to the writable
  persistent panel/certificate stores.

Evidence: the pinned `DockerEntrypoint.sh` was inspected directly from the image
and shows the root/iptables/file-write behavior above; these are intentional
host-gateway contracts, not general-purpose application privileges.
