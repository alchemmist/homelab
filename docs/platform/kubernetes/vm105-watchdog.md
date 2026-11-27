# VM105 recovery from the MOS workstation

**Scope:** `testing-class` is Proxmox VM **105**; inside Linux and Kubernetes it is `socrat-5`. The watchdog can restart this guest's K3s service or request a graceful reboot of this guest. It cannot power on a stopped VM, reset a hung guest, operate on a sibling VM/CT, or repair the Proxmox web console. Restarting the guest interrupts workloads on this node.

## Where the components live

| Location | Component and responsibility |
| --- | --- |
| MOS workstation `mos-xk4zgt`, account `admin` | `~/.config/systemd/user/mos-vm105-watch.{timer,service}`. The timer starts a oneshot outbound SSH check about 10 seconds after timer activation, then three minutes after each check finishes. User lingering is enabled so logout does not stop the timer. Service timeout: 50 seconds. Results go to the user journal. |
| MOS SSH client | Uses only `~/.ssh/mos-vm105-watch` for this check. Current destination: `root@172.18.85.136` (guest LAN, **not** the Proxmox host). Strict host-key checking against `~/.ssh/homelab-vm105/known_hosts-restored-candidate`; `172.18.84.112` is the lookup alias for the pinned key, not the connection destination. |
| VM105 guest | One `restrict,command="/usr/local/sbin/mos-vm105-check"` entry in `/root/.ssh/authorized_keys` binds the watchdog key to the root-owned checker. No interactive shell or forwarding through this key. The checker verifies its hostname, reads local health and executes any permitted action **inside the guest**. |
| Guest state | `/var/lib/mos-vm105-watch/` (root only): `lock` serializes checks; `failures`/`lastbad` count failed samples; `attempts`/`action` track restart requests; `healthy`/`rebooted` control rearming; `hold` inhibits actions. State survives reboot. |
| Other cluster nodes | The guest queries the Kubernetes API on `socrat-0` (`10.250.0.1`) or `socrat-1` (`10.250.0.3`), port 6443. Read-only checks; no restart commands go to peers. |

[Deployed unit files and guest script](../../../deploy/proxmox/vm105-observer/mos/). RuDesktop was used for installation, not as a runtime dependency. No incoming MOS management tunnel, NetBird enrollment, or Proxmox API credential is needed by the service. The earlier `vm105-observer.timer` on the hypervisor was removed; do not reinstall it as part of this scheme.

## Decision sequence

1. **Reach the pinned guest over SSH.** Transport failures, changed addresses and host-key mismatches end the MOS check before guest code runs. They do not count as guest failures. A maintenance hold, missing `/mnt/files` mount or uptime below ten minutes also prevents action.
2. **Check three local signals:** `systemctl is-active k3s`, local API `/readyz` returning `ok`, and the `Ready` condition of node `socrat-5` equal to `True`. All three must pass. Success logs `k3s-and-node-ready` and clears failure and restart counters. This is not an application, storage integrity or etcd quorum test.
3. **Count guest failures.** After three consecutive counted failures, consider recovery. Samples less than 150 seconds apart do not count twice; a gap over 420 seconds starts a new failure streak. Three observations at three-minute intervals span approximately six minutes from first observation to third, not a guaranteed ten-minute outage.
4. **Try K3s before reboot.** Require at least one peer `/readyz` to return `ok`. Otherwise log `cluster-unreachable-no-action`. Request `systemctl restart --no-block k3s` at most three times in the failure sequence. Record each request before issuing it; it is not proof of success. Wait at least ten minutes after each action, including the third, and reassess on a later timer tick. With a three-minute timer this is usually around twelve minutes between actions.
5. **Escalate only on corroboration.** A healthy peer must also report `socrat-5` Ready=`False` or `Unknown`. A missing node, failed lookup or peer reporting `True` does not authorize reboot. Otherwise persist the reboot latch, sync and request `systemctl reboot`. No forced reset, Proxmox fallback, or datastore change.
6. **After reboot:** wait out boot grace. While latched, further unhealthy checks cannot restart K3s or reboot again. The latch clears on a healthy check at least 30 minutes after the first healthy timestamp with no intervening observed guest health failure. This is not a daily quota or proof of continuous health during unobserved intervals.

## Operator checks

On **MOS, as `admin`**:

```sh
systemctl --user list-timers --all mos-vm105-watch.timer
journalctl --user -u mos-vm105-watch.service --since today --no-pager
loginctl show-user admin -p Linger
```

Read the **message**, not just the unit exit status: `maintenance`, `disk-not-mounted`, `boot-grace`, `recovery-grace`, `peer-not-confirming-outage` and `reboot-latched` are decisions not to act, not declarations of health. A failed SSH session appears in the MOS journal. There is no out-of-band notification channel. Manually starting the oneshot is **not** a dry run.

For planned work, **before stopping K3s**, pause the timer on MOS (`systemctl --user disable --now mos-vm105-watch.timer`) and check that the oneshot has finished. Alternatively, as root in the guest, `touch /var/lib/mos-vm105-watch/hold` before maintenance. Neither cancels an action already issued. Verify health before resuming: remove the guest hold if used, then `systemctl --user enable --now mos-vm105-watch.timer` on MOS if disabled. To revoke access permanently, disable the timer and remove **only the watchdog forced-command key entry** from the guest, preserving unrelated keys.

If SSH stops working, confirm the guest address and identity through an already authorized management path (e.g. `qm guest cmd 105 network-get-interfaces` on Proxmox). If DHCP changed it, update the destination in the MOS unit and its repository source, preserve the verified host-key pin, run `systemctl --user daemon-reload`, and inspect the next scheduled check. Never disable host verification or substitute a hypervisor root key.

## Boot and acceptance limits

On 2026-11-27, K3s and SSH were enabled for boot; `/mnt/files` was in fstab and mounted; Guest Agent was active. The deployed MOS check returned `k3s-and-node-ready`. The escalation path was **not** failure-injected on production. A previous graceful reboot brought back guest Linux and the data mount but did not by itself resolve the K3s/etcd incident. A guest reboot cannot guarantee recovery from a shared control-plane failure.

After an incident verify node Ready from an independent API, local storage mounted as expected, and application readiness (especially Grafana external health and n8n). Before further manual restarts preserve guest K3s logs including the previous boot, MOS journal and peer etcd logs over the same interval. Do not clear WALs, start the old container or detach the VM's disks to test the watchdog.
