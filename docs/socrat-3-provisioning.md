# Socrat-3 provisioning

Since 2026-10-18 this machine also runs the K3s control plane and an etcd voter. Its existing workload runtime, resource reservations and desktop configuration were retained. Use [the current HA workflow](k3s-ha.md) for server-role maintenance; the worker bootstrap below describes its original enrollment and must not be used to demote the running server.

The MSI CR61 3M (AMD A4-5000, approximately 3.3 GiB usable RAM) is managed
through `ansible/inventory/socrat-3.yml`. The maintenance connection is wired
Ethernet at `192.168.0.110:2222`; the account is `alchemmist`. Root escalation uses
`su -l` during bootstrap. Passwords and the Wi-Fi PSK are not stored in Git.

SSH uses the common `ssh` role and port 2222. For an initial installation
still listening on port 22, migrate it before the laptop playbook:

```bash
ansible-playbook playbooks/ssh.yml --limit socrat-3 \
  -i inventory/hosts.yml -i inventory/socrat-3.yml \
  -e homelab_ssh_bootstrap_port=22 --ask-become-pass
```

The role verifies authentication on 2222 before completing the transition.
Port 22 remains available under the shared recovery-port policy.

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

## Locale and Internet time

The Debian laptop role manages `en_US.UTF-8` and `ru_RU.UTF-8`, with English as
the default system language. SSH sets `LC_CTYPE=C.UTF-8` in a managed sshd
drop-in, overriding macOS's forwarded bare `LC_CTYPE=UTF-8`, which glibc does
not recognize as a locale name. It does not force `LC_ALL`; explicit Russian
or English locale selection remains available. The full sshd configuration
is validated before reload. An interactive SSH login with the formerly failing
client environment now produces UTF-8 output without locale warnings; Russian
and English day names were both verified.

Chrony uses `2.debian.pool.ntp.org`, starts at boot, and is checked for an
active network source and synchronization within 100 ms. The timezone is
`Europe/Moscow`. At verification, the clock correction was below 1 ms.
Reapply both settings with `--tags locales,time` on `debian-laptop.yml`.

## Wireless diagnosis on 2026-10-16

The onboard RTL8723AE still does not provide a usable Wi-Fi connection.
With MSI disabled and firmware loaded, scans return no networks. The device
reports an asserted legacy INTx interrupt, but IRQ 39 (`rtl_pci`) remains at
zero, with no unhandled interrupt count. rfkill reports no block. This points
to interrupt delivery, not an SSID/password problem, but does not establish
whether firmware, BIOS routing, the driver, or hardware is the root cause.

A per-device runtime test disabled PCIe L0s, L1 and clock power management
through the kernel sysfs interface. Hardware readback confirmed the change;
scans still found no networks and the interrupt count remained zero. The
original settings were restored after the test. No experimental power setting
was persisted, and no driver reload, MSI enablement, or reboot was performed.
Ethernet SSH and all four Ready nodes were retained. Wireless autoconnect
remains disabled until a working path is verified. Do not remove Ethernet on
the assumption that Wi-Fi has been configured successfully.

A separate USB wireless adapter can be tested without reenabling the known
unstable MSI path. Further onboard-driver or boot-parameter experiments need
a controlled maintenance window with local recovery available.

## Further onboard Wi-Fi investigation

The running `rtl8723ae` module matches PCI ID `10ec:8723` and the installed
kernel vermagic. `dpkg -V firmware-realtek` reported no modified package
files, and the B-revision firmware loaded without error. Replacing the driver
with an unrelated Realtek module is not supported by this evidence.

Diagnostic ACPI tables were extracted and decompiled with `acpica-tools` in
`/home/alchemmist/wifi-diagnostics` (private directory). Do not publish the
complete dump: MSDM can contain a Windows license. BIOS is E16GPAMS.109,
dated 2013-10-15, on MSI MS-16GP / CR61 3M.

GPP1 (`00:02.3`, upstream of the Wi-Fi adapter) has no `_PRT` in the DSDT or
four SSDTs. Sibling bridge tables cover GSI28-31,36-39,40-43. The second IOAPIC
starts at GSI24, so the displayed IO-APIC pin0 is not proof of GSI0: it is
consistent with fallback routing to GSI24. The missing GPP1 table may omit
GSI32-35, but the actual chipset routing register must be checked before
asserting or fixing this.

AMD Family16h BKDG publication 48751, printed p145 Table61, recommends
Dev2Fn3 external interrupt group2 (pins8-11, GSI32-35 with this MADT).
Printed p226-228 describe D0F0xF8/FC indexed access, routing index0x12, and
read-only interrupt status index0x30. No register selector or routing writes
were made. If the live setting confirms the mismatch, investigate a narrowly
targeted missing `_PRT` SSDT and controlled IRQ reallocation; do not blindly
change global ACPI/IRQ flags or repeat MSI1.

The old watchdog trace also needs a more cautious interpretation: its first
IRQ stack includes Ethernet `alx_mask_msix`, while the interrupted RTL task's
RIP points to the return-thunk jump following a MMIO read. This does not prove
that the RTL MMIO read itself hung. IRQ/softirq starvation or PCIe interaction
remain hypotheses. Preserve Ethernet and avoid reloading alx.

During read-only investigation after installing ACPI diagnostic tools,
socrat-3 became unreachable over both Ethernet and WireGuard and changed to
NotReady. No driver, network, or boot configuration changes preceded this
outage in that investigation. Its physical state and failure cause must be
established before continuing remote work.

Primary references:
- https://www.amd.com/content/dam/amd/en/documents/archived-tech-docs/programmer-references/48751_16h_bkdg.pdf
- https://github.com/torvalds/linux/blob/v6.12/drivers/acpi/pci_irq.c
- https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/realtek/rtlwifi/pci.h
- https://github.com/torvalds/linux/blob/v6.12/drivers/net/ethernet/atheros/alx/hw.c


The subsequent boot journal established an alx TX-cleanup infinite loop even
with Wi-Fi MSI disabled. Hardware register reads confirmed the missing Wi-Fi
route, and a bounded hardware remap found networks but produced an IRQ storm,
so it was reverted. A separate, unselected test boot image is now prepared;
see [the recovery candidate](socrat-3-network-recovery.md) for evidence,
validation, and rollback. No working wireless connection is claimed yet.

## Standard administrator shell

The laptop role imports the existing `base` and `starship` roles and installs
the Debian `zsh` and `starship` packages before applying the shared prompt.
`alchemmist` uses `/usr/bin/zsh` as its login shell, matching socrat-0; the
machine-wide prompt configuration is `/etc/starship/starship.toml`. The
hostname and local loopback resolution are both `socrat-3`.

Apply with `--tags shell` on `debian-laptop.yml`, using the supplemental
socrat-3 inventory. New SSH logins pick up Zsh automatically; an existing
interactive Bash session can use `exec zsh -l` without reconnecting.

Alacritty on socrat-3 also enables `colors.transparent_background_colors`.
Together with `window.opacity=0.0`, this applies transparency to application
cell backgrounds as well as the default background. The setting is a host
inventory override in the shared terminal role and can be reapplied with
`--tags alacritty`. The running window was updated through Alacritty IPC;
its tmux pane was retained. Visual confirmation remains with the local user.

The current graphical desktop is now Sway, selected by
`homelab_laptop_desktop: sway`; GNOME is retained for rollback. See
[the family desktop setup](socrat-3-sway.md) for applications, controls,
validation and deployment. The earlier fullscreen monitor-at-login setup is
superseded by an on-demand monitor shortcut in this desktop.
