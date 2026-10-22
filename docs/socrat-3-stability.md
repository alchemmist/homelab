# Socrat-3 idle and watchdog

Apply `ansible/playbooks/socrat-3-stability.yml` with both the main inventory and
`ansible/inventory/socrat-3.yml`. Supply the become password outside the repository.

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
