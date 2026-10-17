# Socrat-3 network recovery

Persistent guarded MSI Wi-Fi is verified on an ordinary Debian boot with
kernel6.12.113+deb13-amd64. Ethernet remains connected as the preferred path;
a temporary route change also verified administration and cluster traffic
through Wi-Fi.

## Confirmed evidence

The MSI MS-16GP / CR61 3M firmware omits GPP1._PRT. A guarded read of AMD
host-bridge index0x12 returned0x001a0002: external interrupt group2, zero
swizzle, corresponding to GSI32-35. Index0x30 returned0x100, confirming pin8
(GSI32) asserted. Linux assigned rtl_pci IOAPIC pin0, consistent with GSI24.
The read changed only the index selector and restored it; no routing data
was changed by that probe.

A separate bounded runtime test moved only the Wi-Fi bridge's external group
from2 to0. Scanning immediately found SweetHome at100% signal, proving that
missing interrupts prevented reception. However, a longer association test
produced sustained approximately60,000 IRQ/s and failed authentication.
The original route0x001a0002 was restored, Wi-Fi was left disconnected and
no remapping service was persisted. This is not an acceptable workaround.

The later Ethernet hang occurred with Wi-Fi MSI disabled. The first traceback
at18:34:29 on2026-10-16 is inside alx TX cleanup, with hardware consumer index
0xffff. Its software index wraps within the ring and can never reach0xffff;
after buffers are freed, the remaining budget no longer decreases. The same
loop persists in the later watchdog traces. This corrects the earlier,
overly specific attribution to Wi-Fi MSI or a stuck RTL MMIO read.

## Candidate changes

- An additional SSDT supplies GPP1._PRT for the actual GSI32-35 route. It does
  not change hardware routing, enable MSI, or replace the whole DSDT.
- The alx candidate validates the hardware TX consumer index before cleanup.
  An invalid index schedules the existing reset worker and returns instead of
  entering an unbounded loop. This bounds the failure; the underlying reason
  for the invalid PCIe read remains unproven.
- Wi-Fi profile route metric2000 keeps working Ethernet metric1002 preferred
  during initial wireless validation. Autoconnect was disabled for those trials
  and is enabled in the verified persistent configuration.

## Preparation

From `ansible/`, with the private per-host escalation credentials available:

```bash
ansible-playbook playbooks/socrat-3-network-recovery-stage.yml \
  -i inventory/hosts.yml -i inventory/socrat-3.yml --ask-become-pass
```

The play is hardware- and kernel-gated to MS-16GP and6.12.111+deb13-amd64.
It uses Debian source6.12.111-1 and matching headers, dry-runs the patch,
builds the module outside the live modules directory, compiles the SSDT, and
builds a separate image:

```text
/boot/initrd.img-6.12.111+deb13-amd64-homelab-network
```

The ACPI hook and replacement alx module are added only to the candidate
initramfs configuration. The play verifies the normal initramfs checksum is
unchanged. The optional GRUB entry is `homelab-network-test`, titled
`Debian - socrat-3 network recovery test`; the default remains0.

Three one-shot trial boots have been performed with console recovery available.
A third trial subsequently verified the replacement alx. Further trial boots
require coordinated console recovery. A one-time selection is:

```bash
ansible-playbook playbooks/socrat-3-network-recovery-test.yml \
  -i inventory/hosts.yml -i inventory/socrat-3.yml --ask-become-pass
```

The next ordinary boot returns to the normal default. If the candidate fails,
select the ordinary Debian entry at the console. Do not change GRUB_DEFAULT
or copy the experimental initramfs over the normal image. The managed
persistent installation described below builds a separate normal configuration.

## Trial results on 2026-10-17

The first trial loaded the ACPI override and mapped the wireless interrupt to
IOAPIC pin8 as intended. It nevertheless produced approximately60,000 IRQ/s,
including while Wi-Fi radio was off. Unloading the RTL driver stopped the
storm. Correcting the ACPI mapping therefore does not constitute a working
wireless repair, and this configuration must not become the normal boot.

The running alx build ID did not match the patched candidate. Investigation
found that Debian initramfs-tools queues the original module for copying after
custom hooks: the original alx.ko.xz was restored alongside patched alx.ko,
and depmod selected the original. The first trial did not exercise the TX
consumer-index guard.

The second trial boot kept Wi-Fi blacklisted and successfully restored SSH
through WireGuard. However, its loaded alx still matched the original module;
the attempted replacement and forced loading had not established the required
protection. At that stage, the new MSI-enabled Wi-Fi trial had not yet been performed.

The revised staging approach places the candidate at updates/homelab/alx.ko,
uses module-search priority plus forced loading, and verifies the finished
initramfs archive. The third trial confirmed that the running build ID matched this candidate.
An archive containing the patched file alone is insufficient evidence that
the kernel actually selected it.

The third trial loaded the protected alx and enabled RTL8723AE MSI. Wi-Fi
received192.168.0.137, passed10/10 external ping probes, and transferred64MiB
in each direction over SSH. No alx resets or kernel lockups were observed in
that trial. The timed rollback forcibly unloaded Wi-Fi and produced a
mac80211 pending-ACK warning in ieee80211_free_ack_frame, not a lockup.
Reloading and reconnecting subsequently worked. Forced module unload is not
part of normal operation.

These one-shot boots used the existing Debian installation; no OS reinstall
was performed. The staged trials preserved the ordinary initramfs. Persistent
installation below intentionally updates it after preserving a rollback copy.

## Persistent installation and final verification

Run `playbooks/socrat-3-network-recovery-install.yml` with the same inventory
and private escalation credentials. It verifies the loaded candidate, installs
homelab-alx6.12.111-1 through DKMS, and includes that module in the normal
initramfs. The normal image contains no trial ACPI override: MSI avoids the
unusable legacy interrupt route.

A blacklist prevents automatic RTL loading. The guarded startup service checks
that DKMS is installed for the running kernel, module resolution selects the
DKMS driver, and its build ID matches the loaded alx before enabling MSI Wi-Fi.
If a future kernel lacks a working matching DKMS build, wireless activation
fails closed rather than loading it without protection. Ethernet startup does
not depend on this service.

The original ordinary image is preserved at:

```text
/boot/initrd.img-6.12.111+deb13-amd64-before-homelab-alx
```

The first ordinary boot selected kernel6.12.113 and correctly refused Wi-Fi
because its matching DKMS build was missing. The added
network_recovery_kernels.yml tasks install matching headers, build DKMS and
verify initramfs module resolution for the installed107,111 and113 kernels.

The final ordinary boot on6.12.113 passed the loaded-module build-ID check.
The guard service is active and Wi-Fi automatically connected to SweetHome
at192.168.0.137. Sway and k3s are active.

For validation, Wi-Fi temporarily received route metric500. The route to the
public WireGuard endpoint selected wlp1s0, and SSH through the socrat-3
WireGuard alias remained available. Each of the three other WireGuard peers
passed5/5 ping probes and an external HTTPS request returned200. The existing
k3s-worker-verify checks passed all16 pod-network paths, DNS, API access,
read-only NFS access and pod logs. The temporary verification namespace was removed successfully.
The node is uncordoned and all four cluster nodes report Ready.

Ethernet remains connected with metric1002; Wi-Fi metric2000 was restored
after validation. No invalid TX-index reports, watchdog/RCU lockups or the
pending-ACK warning appeared in this final boot. Existing BIOS warnings remain;
this is not a claim that the boot log contains no warnings.

## Validation after trial boot

1. Confirm Ethernet SSH and the Kubernetes worker return.
2. Confirm ACPI logs show the HMLAB/S3WIFI SSDT loaded. The test entry keeps
   rtl8723ae blacklisted until explicit loading; no wireless IRQ is expected
   before that step. The native interrupt mapping alone is not a working fix.
3. Compare the running alx build ID with the patched candidate, not just its
   filename or the initramfs contents. Inspect kernel logs for invalid TX-index
   or reset reports. Do not start another Wi-Fi experiment if the IDs differ.
4. Confirm no IRQ storm with Wi-Fi disconnected before attempting a bounded
   wireless trial. Scan and connect homelab-wifi with Ethernet retained. Observe IRQ deltas,
   CPU load and kernel warnings for sustained traffic, not only discovery.
5. Verify SSH through the Wi-Fi DHCP address using a route that actually
   traverses Wi-Fi, then verify WireGuard connectivity through that interface.
6. Only after successful validation enable wireless autoconnect and plan
   normal boot persistence. Until then, the kernel safety guard stays in place.

`tests/test_alx_tx_guard.py` extracts the actual TX-cleanup function from
`ALX_SOURCE` and compiles a C harness. The old implementation times out for
indices256 and65535; the patched Debian source passes those and valid wrap,
empty, and budget cases. This test does not validate the complete hardware.

## Published reports reviewed on 2026-10-17

Before the trials, the inventory reported MSI CR61 3M / MS-16GP, BIOS E16GPAMS.109
(2013-10-15), Realtek RTL8723AE PCI10ec:8723 / AzureWave1a3b:2114,
Debian 13.7 and kernel 6.12.111+deb13-amd64. The driver was rtl8723ae;
firmware-realtek is20250410-2. rfkill reports neither software nor hardware
blocking. No driver or firmware configuration was changed for this review.

- Debian bug785327 reported an MSI machine whose RTL8723AE was detected but
  returned no scan results on Debian8/kernel3.16. The maintainer moved the
  issue from firmware-realtek to the kernel package and requested diagnostics.
  The reviewed messages contain no confirmed repair for Debian13:
  https://mail-archive.com/debian-bugs-dist%40lists.debian.org/msg1322208.html
- Kernel bug216672 reports the exact CR61 3M/MS-16GP family, RTL8723AE, and
  soft lockups on kernels5.19/6.0.6, with BIOS E16GPAMS.10A (2013-11-25).
  The developer could not explain the reported instruction-level stall and
  requested a known-good kernel comparison. The accessible thread has no
  verified fix; the current Bugzilla status could not be checked because
  of its access challenge. It must not be equated with our alx TX-loop bug:
  https://lkml.indiana.edu/hypermail/linux/kernel/2211.1/06266.html
  https://lkml.indiana.edu/hypermail/linux/kernel/2211.1/08217.html
- Linux6.12 source explicitly binds PCI10ec:8723 and selects rtl8723fw_B.bin
  for B-cut hardware. The MODULE_FIRMWARE metadata naming rtl8723efw.bin
  does not establish that the wrong runtime firmware is being loaded:
  https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/net/wireless/realtek/rtlwifi/rtl8723ae/sw.c
  https://packages.debian.org/trixie/all/firmware-realtek/filelist

The installed driver also has an independent aspm parameter, currently1.
Our runtime per-link ASPM-disable experiment did not restore scanning, but
it is not identical to initializing the driver with aspm=0 from boot. That
would be a separate controlled diagnostic, not a proven fix from these
reports. Old advice to install an out-of-tree rtlwifi driver or repeat old
IRQ patches is not justified merely by matching the card name.

The absence of a user-visible Wi-Fi option in BIOS setup does not rule out
firmware-supplied ACPI routing defects. Our GSI mismatch measurements remain
relevant. The first trial verified that the table correction takes effect,
but its IRQ storm disproved that it is sufficient for a usable connection.
No BIOS flashing is proposed.
