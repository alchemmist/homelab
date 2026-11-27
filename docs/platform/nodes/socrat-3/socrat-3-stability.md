# Socrat-3 idle and watchdog

Apply `ansible/playbooks/socrat-3-stability.yml` with the main inventory,
`ansible/inventory/hosts.yml`. Supply the become password outside the repository.

The playbook is for the Kabini A4-5000 in socrat-3. It does not reboot the node,
restart k3s, or change GRUB. The network-recovery check still requires
`GRUB_CMDLINE_LINUX_DEFAULT="quiet"`, so the idle limit is applied by a boot unit
instead of `processor.max_cstate=1`.

C2 here is a processor idle depth, not a CPU core. All four cores stay online.
The unit `/etc/systemd/system/homelab-disable-c2.service` runs
`/usr/local/sbin/homelab-disable-c2` at boot and disables only cpuidle states
named C2. C1 and POLL stay available. The same command is applied to the running
system, so a reboot is not required for the limit to take effect.

The machine already has an SP5100 TCO watchdog with a fixed 60 second timeout.
`/etc/systemd/system.conf.d/homelab-watchdog.conf` sets `RuntimeWatchdogSec=60s`.
When that file is new, or the watchdog is not already active, the play asks PID 1
to re-exec and open `/dev/watchdog0`. systemd then pings it. If the kernel stops
scheduling userspace, the timer reboots the machine in about a minute. The device
does not accept a different timeout; the play refuses any other identity or timeout.

This does not repair the earlier Ethernet TX loop or the Wi-Fi interrupt route.
Those stay covered by the patched `alx` module and the MSI Wi-Fi startup guard.

Verify:

```sh
for d in /sys/devices/system/cpu/cpu*/cpuidle/state*; do
  printf '%s %s %s\n' "$d" "$(cat "$d/name")" "$(cat "$d/disable")"
done
cat /sys/class/watchdog/watchdog0/state /sys/class/watchdog/watchdog0/timeleft
systemctl is-enabled homelab-disable-c2.service
```

C2 `disable` is `1`, C1 `disable` is `0`, and the watchdog `state` is `active`
with `timeleft` between 1 and 60. Also confirm socrat-3 stays Ready.

## 2026-11-27: separate the runtime stall from the subsequent boot failure

| Evidence | Interpretation |
| --- | --- |
| The overnight boot ran with `ro quiet`, **without** ramoops. At 22:15:31 UTC on Nov 26, `Lid closed` and `Suspending...` appeared in the same second. `suspend.target` was masked; logind kept trying until the journal ended at 00:04:52 UTC on Nov 27. | A confirmed lid-policy loop, not proof that the machine suspended or that the loop caused the final hang. |
| Later boot attempts stopped displaying output after `Physical KASLR disabled: no suitable memory region!`. The generated GRUB entry contained `memmap=0x100000$0x7f000000` with an unescaped dollar sign. | The ramoops drop-in changed the boot memory map and its argument was unsafe to pass through GRUB. No failed-boot journal proves exactly where the kernel stopped. Disabling KASLR is not the fix. |
| A subsequent text-mode boot logged an `alx` transmit-queue timeout, RCU stall and CPU soft lockup. Stacks included network polling and Radeon VGA detection over I²C; console work waited on DRM. | This happened without Sway. Neither the interrupted GPU stack nor the Ethernet timeout alone identifies the cause of every freeze. The loaded `alx` build ID matched the DKMS module; see [network recovery](socrat-3-network-recovery.md). |

**Known-good boot:** `/etc/default/grub.d/99-ramoops.cfg` was retired (kept on
host with `.disabled` suffix), GRUB regenerated and checked with
`grub-script-check /boot/grub/grub.cfg`. The stability playbook rejects the
active drop-in; it does not regenerate GRUB. A normal unattended reboot of
`6.12.113+deb13-amd64` confirmed `ro quiet` in `/proc/cmdline`, then SSH and
Kubernetes `Ready` without user input. `k3s-agent` spent several minutes
waiting for containerd under high disk I/O pressure. Do not power-cycle merely
because SSH returns before kubelet is ready. SMART on `sda` passed with zero
reallocated, pending, offline-uncorrectable and UDMA CRC counts; the recorded
read errors on `sr0` refer to the optical drive, not the system disk.

**Lid and power:** logind now ignores the lid on battery, external power and
while docked. With Ethernet and AC attached, the closed-lid check confirmed
`Lid closed` without subsequent suspend requests, reachable SSH and fresh
node heartbeats. [Worker power rules](../../../../charts/monitoring-k3s/templates/socrat-3-power-rules.yaml)
raise `Socrat3OnBattery` (warning, ADP1 offline for 2m) and `Socrat3BatteryLow`
(critical, BAT1 at or below 20% for 2m, even on AC). Do not change the etcd
voter alerts or disable critical-battery protection for this worker.

**If it recurs:** record the UTC time and match it to `journalctl --list-boots
--utc`. Use the boot ID rather than assuming `-1` after multiple restarts.
Inspect `journalctl -k -b BOOT_ID --utc` and `journalctl -u systemd-logind -b
BOOT_ID --utc`. Compare with Loki `{host_name="socrat-3",service_name="host-journal"}`
over the same interval. Prior kernel boot messages were present remotely, but
the exact soft-lockup trace was only found locally; both pstore directories
were empty. A journald service watchdog restart is not evidence that the
hardware watchdog reset the host. Do not re-enable the retired memory reservation
just to obtain a dump.
