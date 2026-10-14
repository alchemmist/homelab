# WireGuard administrative firewall rollback

The managed systemd unit removes only its own jumps and chains when stopped:

```sh
systemctl stop wg-socrat-admin-firewall.service
```

The unit does not flush `INPUT`, `FORWARD`, or any Kubernetes chain. Re-running
the Ansible role recreates the owned chains and rules from
`wg_socrat_admin_clients`.
