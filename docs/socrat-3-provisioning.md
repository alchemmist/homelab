# Socrat-3 provisioning

The MSI CR61 3M (AMD A4-5000, approximately 3.3 GiB usable RAM) is managed
through `ansible/inventory/socrat-3.yml`. The maintenance connection is wired
Ethernet at `192.168.0.110:22`; the account is `alchemmist`. Root escalation uses
`su -l` during bootstrap. Passwords and the Wi-Fi PSK are not stored in Git.

From `ansible/`, apply the host setup using:

```bash
ansible-playbook playbooks/debian-laptop.yml \
  -i inventory/hosts.yml -i inventory/socrat-3.yml \
  --tags kernel_safety,utilities,gnome --ask-become-pass
```

This targets only socrat-3. The existing socrat-0 and socrat-1 desktop setup is
not reapplied. The shared `desktop_terminal` role supplies Alacritty, tmux,
bottom, the 600-second graph window, descending table sorts, and font checks.
GNOME uses GDM automatic login as `alchemmist` and an account autostart entry
for the monitor terminal. The common wallpaper asset is applied to GNOME light, dark, and lock-screen backgrounds. Alacritty starts fullscreen with decorations disabled on this node. Reapply these settings with `--tags appearance`; existing terminal windows need reopening for the startup mode to take effect. SSH and clock synchronization start as system
services independently of graphical login.

## Kernel incident and current containment

On 2026-10-15, enabling `rtl8723ae msi=1` temporarily allowed the onboard
Realtek RTL8723AE to associate with SweetHome and obtain `192.168.0.137`, but
was followed by severe scheduler delays, soft lockups, RCU stalls, and loss of
remote responsiveness. The previous-boot kernel journal is retained on the
node at `/var/log/homelab/kernel-previous-boot.log` with root-only permissions.
Both the failing and following stable boots used Debian kernel
`6.12.111+deb13-amd64`.

Recorded stacks include `pci_read8_sync` from Realtek rfkill polling and
`pci_read32_sync` during channel switching. These functions access device MMIO;
the evidence does not establish a specific BIOS/ASPM repair. The role explicitly
persists `msi=0` and refuses provisioning while MSI is active. Wi-Fi automatic
connection defaults off. This is containment of the observed hang trigger,
not a claim that the original Wi-Fi scanning problem is solved. Do not enable
MSI remotely or use unsupported RTL8723BE antenna parameters on this RTL8723AE.

The GNOME greeter also initiated an automatic suspend during initial setup. The role now masks sleep/suspend/hibernate targets before starting graphical services, including GDM. These masks prevent future requests; they do not cancel a transition that was already running.

The missing Radeon firmware is supplied by `firmware-amd-graphics`. The CPU
uses `acpi-cpufreq`; absence of modern AMD CPPC support is not evidence of a
CPU failure. Older BIOS/ACPI warnings must not be hidden with global kernel
workarounds. SMART health on the system HDD passed; the `sr0` medium errors
refer to a separate optical disc, which was ejected during diagnosis.

## Network ownership

Ethernet remains under ifupdown/dhcpcd and is explicitly excluded from
NetworkManager. Only Wi-Fi is managed by NetworkManager. The Wi-Fi role can
read the locally supplied `/etc/wifi.conf` to derive its protected system
connection; credentials stay on the node. The bounded Ethernet guard is a
maintenance aid, not protection against a kernel lockup or loss of power.

## Worker enrollment

`playbooks/k3s-worker.yml` is a focused agent-only workflow, not an HA-server
conversion. The WireGuard address is `10.250.0.5`; `.4` belongs to the
Mac. This site's LAN overlaps the older site, so worker routes to remote
`192.168.0.23/32` and `.24/32` must use the respective WireGuard peers. Peer
endpoints for the old site use its public hostname and forwarded UDP ports.

The worker starts with an admission taint until networking, storage and
DaemonSet placement are checked. Syncthing must not schedule on the new host
before a matching private proxy configuration exists. The worker role reserves
memory for the desktop and Kubernetes and excludes CNI interfaces from
NetworkManager. Enrollment is not complete merely because these files exist.

`wireguard-worker.yml` configures only socrat-3. Existing peers also need to
accept its public key and management address before it can reach the cluster;
that registration is managed by `wireguard-worker-peers.yml`, which adds only the new peer without restarting existing interfaces. It recognizes peers already rendered by the common role and rejects conflicting address ownership.

## Verified on 2026-10-16

The new boot entered GNOME as alchemmist and started the shared monitor.
Radeon now binds to the GPU, and the current kernel log contains no repeat of
the previous soft lockups/RCU stalls or missing Radeon firmware error. Older
platform BIOS warnings remain and are not claimed to have been repaired.
Sleep and hibernation targets remain masked.

The common wallpaper was delivered from the repository's `wallpaper_asset`
role; its SHA-256 matches the source asset. Light/dark and lock-screen settings
point to it. The monitor window was reopened after setting fullscreen startup
and no decorations; the tmux pane and running btm process were preserved.
Reapplying the `appearance` tag completed with `changed=0` and no failures.


## Completed cluster enrollment on 2026-10-16

Socrat-3 joined as an agent-only worker running `v1.36.5+k3s1`, with node IP
`10.250.0.5` and pod CIDR `10.42.3.0/24`. It needs no public address: outbound
WireGuard handshakes and keepalives maintain its connections to the existing
nodes. Ethernet remains unmanaged by NetworkManager; SSH stays available at
`192.168.0.110`. WireGuard and k3s-agent are enabled at boot.

Apply the enrollment workflows from `ansible/` in this order:

1. `playbooks/wireguard-worker-peers.yml`
2. `playbooks/wireguard-worker.yml`
3. `playbooks/k3s-worker.yml`
4. `playbooks/syncthing-placement.yml`
5. `playbooks/k3s-worker-admit.yml`

Use both `-i inventory/hosts.yml -i inventory/socrat-3.yml`. Supply per-host
become credentials through a private inventory or Ansible Vault: old nodes
use sudo and the new worker uses `su -l`, with different passwords. Do not use
the old site's direct LAN inventory from the new site: both LANs overlap.

The worker uses `prefer-bundled-bin: true`. During verification Debian's
iptables 1.8.11 returned exit status 2 while kube-proxy checked a missing
KUBE-FORWARD chain; service rules were absent and cluster DNS timed out.
Using K3s's bundled tools restored service routing. This is the supported
[bundled-binary option](https://docs.k3s.io/known-issues#iptables).

`k3s-worker-verify.yml` creates disposable probes on all four nodes, verifies
all 16 source/destination pairs, cluster DNS, the API service, log streaming,
and a read-only NFS mount, then deletes its namespace even on failure. All
checks passed before admission. The bootstrap taint is a registration-time
safety gate; removing it from the existing Node permits normal scheduling.

Syncthing's Helm chart now restricts placement to configured private-GUI nodes.
The existing release was upgraded with retained values; all three instances
remain ready. Socrat-3 intentionally has no Syncthing pod until its instance is
configured. Desktop and autologin settings on older nodes were not reapplied.
