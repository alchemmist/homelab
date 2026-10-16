# Socrat-3 network recovery candidate

This is a staged test, not a verified production repair. The normal kernel,
normal initramfs, default GRUB entry, and running network drivers are unchanged.
Do not remove Ethernet until a separate wireless SSH connection is verified.

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
  during initial wireless validation. Autoconnect remains disabled.

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

The test entry has not been selected or booted. Selection and reboot require
a coordinated maintenance window with someone able to recover at the console.
Once ready, a one-time selection is:

```bash
sudo grub-reboot homelab-network-test
sudo systemctl reboot
```

The next ordinary boot returns to the normal default. If the candidate fails,
select the ordinary Debian entry at the console. Do not change GRUB_DEFAULT
or overwrite the normal initramfs to make this experiment persistent.

## Validation after trial boot

1. Confirm Ethernet SSH and the Kubernetes worker return.
2. Confirm ACPI logs show the HMLAB/S3WIFI SSDT loaded, the wireless IRQ maps
   to IOAPIC pin8, and routing register remains0x001a0002.
3. Confirm the candidate alx loaded from the test initramfs; inspect kernel
   logs for out-of-tree module load and any invalid TX-index/reset reports.
4. Scan and connect homelab-wifi with Ethernet retained. Observe IRQ deltas,
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

The live inventory still reports MSI CR61 3M / MS-16GP, BIOS E16GPAMS.109
(2013-10-15), Realtek RTL8723AE PCI10ec:8723 / AzureWave1a3b:2114,
Debian13.7 and kernel6.12.111+deb13-amd64. The running driver is rtl8723ae;
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
relevant, while a successful test of the proposed table correction is still
required before calling it the complete fix. No BIOS flashing is proposed.
