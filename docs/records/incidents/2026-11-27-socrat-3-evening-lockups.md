# socrat-3 evening CPU stalls, 2026-11-27

Status: open. Times are MSK (UTC+3). Do not interpret loss of SSH alone as a reboot: connections reset around 22:52, but the boot ID was unchanged on reconnection.

| Boot ID | Interrupt burst observed | Kernel evidence |
| --- | --- | --- |
| `49c1e82935df41319618bc5a0e2777fb` | 20:21:05–20:21:25 | CPU 3 soft lockups (49 s, 75 s); Wi-Fi receive and IP routing in IRQ context |
| `0c0e5228e19d4241acfdaf223b51e46b` | 21:50:35–21:51:00 | CPU 3 soft lockups (49 s, 75 s); mac80211 scan receive and frame parsing |
| `3353391777e041e1a8f0bf4bf3182357` | 22:31:15–22:32:10 | CPU 3 RCU stalls at 22:32:27 and 22:33:01 |

Compare `journalctl -k -b BOOT_ID` with adjacent raw node-exporter samples for `instance="10.250.0.5:9100"`. In short intervals during all three events CPU 3 spent 99.7–99.9% of its time in softirq. Aggregate `node_intr_total` peaked at 87–89k/s; this counter **does not identify the IRQ source**. In 2,565 adjacent ~5 s intervals available in the 12 h query, median was 3.8k/s; only these three series exceeded 50k/s. Scrapes stopped before the final journal messages. Neither saturation of the HDD nor a surge in successfully received packets was common to all events. No reset-cause record established that the hardware watchdog fired.

## Temporary diagnostic, not a persistent fix

At 22:53 the Realtek Wi-Fi IRQ was moved from effective CPU 3 to CPU 1 without disabling the only active uplink. AHCI remained on CPU 3. The transient `socrat3-irq-trial-rollback.timer` was scheduled for 23:23:11 to restore the original **allowed mask** `0-3` (not necessarily effective CPU 3). At 22:57 the same boot was still running. An external sampler recorded `/proc/interrupts` by source and CPU every five seconds, along with the boot ID. Correlate deltas only within a boot, and do not count gaps as zero traffic. A quiet trial alone does not prove a fix.

If the stall recurs, compare the rising IRQ vector and the CPU/stack in the kernel trace before drawing conclusions. If no identifying sample survives, the next isolation test requires a verified working Ethernet management path before disabling Wi-Fi. Preserve the existing [network recovery guard](../../platform/nodes/socrat-3/socrat-3-network-recovery.md) and [boot/watchdog policy](../../platform/nodes/socrat-3/socrat-3-stability.md).

## Recurrence during the IRQ trial

At 23:09:35 the RCU stall followed Wi-Fi IRQ 45 to **CPU 1**. The interrupted instruction was `pci_write32_async [rtl_pci]`, with `rtl8723e_disable_interrupt [rtl8723ae]` and `_rtl_pci_interrupt [rtl_pci]` on the stack. External samples between 23:09:27 and 23:09:52 show IRQ 45 alone adding 390–404k interrupts per five seconds (~78–81k/s); AHCI added 75–626 per interval. This identifies the Realtek Wi-Fi interrupt storm as the immediate failure mechanism, not the underlying silicon/firmware/software defect. SSH was lost and a new boot ID `bf6924a4-a325-4c28-8823-bb3fdab7c030` was sampled at 23:11:58. Reset initiator unknown. IRQ affinity reverted across reboot. At 23:12 Ethernet still had no carrier; Wi-Fi remained the only default route. Do not persist CPU pinning as a fix. Establish and validate an independent wired path, then isolate the onboard radio and monitor under normal workload.

## Second outage and PCIe L1 trial

The boot after the 23:09 storm (`bf6924a4-a325-4c28-8823-bb3fdab7c030`) ended abruptly in the journal at 23:16:04 while k3s was waiting for containerd. A directed scan of the active SSID completed at 23:15:53, with normal IRQ 45 rates through 23:16:00. A new boot (`d9c01f41-6abb-4d8f-a1da-6374f3921891`) was reachable at 23:22:43. Do not infer the scan caused the reset. In this boot containerd took 185 seconds to start and k3s-agent was active at 23:27:13.

At 23:49:46 only endpoint 0000:01:00.0 PCIe L1 was disabled at runtime; automatic rollback due 00:49:46. On the same boot the median/maximum RTL IRQ rate was 87/832 per second over 319 short intervals before the change versus 96/859 over 90 intervals through 23:57:32 afterwards. Both periods are quiet relative to the storm; this does not establish efficacy. No persistent change. The 23:08–23:10 kernel journal filter found the RCU stall, not a preceding AER/MCE/OOM or panic message. Reset initiator remains unknown.
