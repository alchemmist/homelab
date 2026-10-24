# Host swap on socrat-3

Apply `ansible/playbooks/socrat-3-swap.yml` with both the main inventory and
`ansible/inventory/socrat-3.yml`. Supply the become password outside the repository.

The playbook activates the existing 3.5 GiB swap partition identified by UUID
`0e5b3741-8d54-40b5-b48e-cac14237ad36`. It checks the partition type and the live
kubelet configuration before making changes. It never formats a partition,
disables active swap, restarts k3s, or reboots the node.

The UUID-based entry in `/etc/fstab` makes swap persistent. `vm.swappiness=10`
is persisted in `/etc/sysctl.d/90-homelab-swap.conf` to discourage early swapping
on this rotating disk. The node's `k3s_worker_swap_enabled` inventory setting
prevents the worker role's legacy swap-disable tasks from undoing this policy.

The running kubelet must have `failSwapOn=false` and the default `NoSwap`
container policy. This enables host/application swap, not Kubernetes pod swap;
the playbook deliberately does not enable `LimitedSwap`.

Swap provides memory headroom, not additional physical RAM or a guarantee
against stalls. Disk contention can still make the node unresponsive. This
partition is not encrypted, so swapped host-process memory can persist on disk.

Verify without generating artificial memory pressure:

```sh
free -h
/usr/sbin/swapon --show
/usr/sbin/sysctl vm.swappiness
```

Also verify socrat-3 remains Ready and Happ's local proxy ports remain available.
Do not run `swapoff` on a loaded node without first checking available RAM.
