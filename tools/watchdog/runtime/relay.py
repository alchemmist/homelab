#!/usr/bin/env python3
"""Node-local Moscow relay watchdog.

Never manages control-plane or management relay. The worker agent is fenced
before native start; fallback marker fences its boot. No API availability-only
failover. Native mode is sticky until explicit failback.
"""

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import select
import signal
import socket
import ssl
import subprocess
import time
from typing import TypedDict

ROOT = pathlib.Path("/var/lib/homelab-vpn-transit/relay-failover")
CONFIG = pathlib.Path("/etc/homelab-vpn-transit/failover.json")
AGENT = "k3s-agent.service"
NATIVE = "homelab-vpn-transit-native.service"
TCP = (80, 443, 32053, 32083, 32084)
UDP = (443, 32085, 32086)
WEBSOCKET_STATUS = 101
WITNESS_UNAVAILABLE_EXIT = 255
MIN_FREE_DISK_BYTES = 2 * 1024**3
FAILURE_THRESHOLD = 4


def persistent_number(value: object) -> float:
    """Numeric watch state, read as untrusted persistence: 0.0 when corrupt."""
    return float(value) if isinstance(value, (int, float)) else 0.0


class Diagnosis(TypedDict, total=False):
    """Autonomous classification of why four data-path failures occurred."""

    recover_local: bool
    scope: str
    upstream_probe: dict[str, object]


def run(
    args: list[str], timeout: int = 25, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a fixed, reviewed command and optionally require success."""
    p = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError("Command failed: " + str(args[:3]))
    return p


def atomic(path: pathlib.Path, value: object) -> None:
    """Persist a JSON value atomically with fsync on file and directory."""
    tmp = path.with_suffix(".tmp")
    data = json.dumps(value, sort_keys=True).encode()
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    tmp.chmod(0o600)
    tmp.replace(path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)


def boot_id() -> str:
    """Return the current kernel boot identifier."""
    return pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def active(unit: str) -> bool:
    """Return True when the given systemd unit reports active."""
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def free_ports() -> bool:
    """Verify every public port can be bound fresh (no live local owner)."""
    for typ, ports in [(socket.SOCK_STREAM, TCP), (socket.SOCK_DGRAM, UDP)]:
        for port in ports:
            with socket.socket(socket.AF_INET, typ) as s:
                # Match Go TCP listeners: TIME_WAIT is not a live port owner. Never reuse UDP.
                if typ == socket.SOCK_STREAM:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                if typ == socket.SOCK_STREAM:
                    s.listen(1)
    return True


def identity(pid: int, cid: str) -> dict[str, object] | None:
    """Verify the pid belongs to the reviewed container id and return its identity."""
    p = pathlib.Path("/proc") / str(pid)
    if not p.exists():
        return None
    cg = (p / "cgroup").read_text()
    if cid not in cg:
        msg = "Container id mismatch in cgroup"
        raise RuntimeError(msg)
    if "kubepods" not in cg and "cri-containerd" not in cg:
        msg = "Process is outside the reviewed container runtime"
        raise RuntimeError(msg)
    return {"pid": pid, "cid": cid, "start": (p / "stat").read_text().split()[21]}


def pod_processes() -> list[dict[str, object]]:
    """List the vpn-transit relay pod worker identities with stable start times."""
    p = run(["k3s", "crictl", "--timeout=5s", "ps", "-o", "json"], timeout=9)
    result: list[dict[str, object]] = []
    for c in json.loads(p.stdout)["containers"]:
        labels = c.get("labels", {})
        if (
            labels.get("io.kubernetes.pod.namespace") != "vpn-transit"
            or not labels.get("io.kubernetes.pod.name", "").startswith("vpn-transit-")
            or labels.get("io.kubernetes.pod.name", "").startswith("vpn-transit-rehearsal-")
            or labels.get("io.kubernetes.container.name") != "relay"
        ):
            continue
        v = json.loads(run(["k3s", "crictl", "--timeout=5s", "inspect", c["id"]], timeout=9).stdout)
        i = identity(int(v["info"]["pid"]), str(c["id"]))
        if i:
            result.append(i)
    return result


def terminate_owned(i: dict[str, object]) -> None:
    """Stop the identified owned relay worker, escalating to SIGKILL if needed."""
    pid_value = i["pid"]
    if not isinstance(pid_value, int):
        reason = "Unusable container pid"
        raise TypeError(reason)
    pid = pid_value
    cid = str(i["cid"])
    now = identity(pid, cid)
    if now is None:
        return
    if now != i:
        msg = "Owned process identity changed before termination"
        raise RuntimeError(msg)
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not pathlib.Path("/proc", str(pid)).exists():
            return
        time.sleep(0.1)
    now = identity(pid, cid)
    if now == i:
        os.kill(pid, signal.SIGKILL)


def probe(
    config: dict[str, object],
    host: str = "127.0.0.1",
    source: tuple[str, int] | None = None,
    detail: dict[str, object] | None = None,
) -> bool:
    """Probe the reviewed TLS/WebSocket data path and record stage detail."""
    # Same strict TLS/WS identity and ACLs on the local and direct upstream path.
    d = detail if detail is not None else {}
    d.update(at=time.time(), stage="connect", ok=False)
    try:
        for port in (32053, 32083, 32084):
            d.update(stage="tcp", port=port)
            with socket.create_connection((host, port), timeout=2, source_address=source):
                pass
        d.update(stage="tcp", port=443)
        with socket.create_connection((host, 443), timeout=3, source_address=source) as sock:
            d["stage"] = "tls"
            with ssl.create_default_context().wrap_socket(
                sock, server_hostname="vpn.alchemmist.xyz"
            ) as t:
                d["stage"] = "websocket"
                req = (
                    "GET "
                    + str(config["ws_path"])
                    + " HTTP/1.1\r\nHost: vpn.alchemmist.xyz\r\n"
                    + "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    + "Sec-WebSocket-Key: "
                    + base64.b64encode(os.urandom(16)).decode("ascii")
                    + "\r\nSec-WebSocket-Version: 13\r\n\r\n"
                )
                t.sendall(req.encode())
                line = t.recv(1024).split(b"\r\n")[0]
                # Record only the numeric HTTP status, never the private path/response body.
                parts = line.split()
                d["http_status"] = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                if d["http_status"] != WEBSOCKET_STATUS:
                    msg = "Websocket upgrade did not return switching protocols"
                    raise RuntimeError(msg)
        d.update(stage="complete", ok=True)
        return True
    except (OSError, RuntimeError, ssl.SSLError) as e:
        d.update(error=type(e).__name__, errno=getattr(e, "errno", None))
        raise


def local_listeners_respond() -> bool:
    """Check whether every local data-path port accepts a TCP connection."""
    for port in (32053, 32083, 32084, 443):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass
        except OSError:
            return False
    return True


class Controller:
    """Failover controller for the VPN transit links."""

    def __init__(self) -> None:
        """Load config and persisted state for the failover controller."""
        self.config = json.loads(CONFIG.read_text())
        self.marker = ROOT / "fallback.active"
        self.state: dict[str, object] = (
            json.loads((ROOT / "state.json").read_text())
            if (ROOT / "state.json").exists()
            else {"mode": "prepared", "failures": 0}
        )

    def save(self, **fields: object) -> None:
        """Persist updated state fields atomically."""
        self.state.update(fields)
        atomic(ROOT / "state.json", self.state)

    def receipt(self, action: str, **fields: object) -> None:
        """Append a timestamped receipt file for the taken action."""
        v = {"action": action, "at": time.time(), **fields}
        atomic(ROOT / (str(time.time_ns()) + "-" + action + ".json"), v)

    def healthy(self) -> bool:
        """Probe endpoints and update the persistent last-probe results."""
        self.last_probe: dict[str, object] = {}
        try:
            probe(self.config, detail=self.last_probe)
            return True
        except (OSError, RuntimeError, ssl.SSLError):
            return False

    def recovery_scope(self) -> Diagnosis:
        # Only after the existing four failures. An upstream outage is not evidence
        # that stopping a still-listening local worker can improve the data path.
        """Determine the scope of local recovery, if any is warranted."""
        detail: dict[str, object] = {}
        try:
            probe(self.config, host="10.250.0.2", source=("10.250.0.40", 0), detail=detail)
            scope = "local-path-failed-upstream-healthy"
            if not active(AGENT):
                scope = "local-agent-inactive"
            elif not local_listeners_respond():
                scope = "local-listener-failed"
            return {
                "recover_local": True,
                "scope": scope,
                "upstream_probe": detail,
            }
        except (OSError, RuntimeError, ssl.SSLError):
            return {
                "recover_local": False,
                "scope": "upstream-or-path-unhealthy",
                "upstream_probe": detail,
            }

    def prerequisites(self) -> None:
        """Pin the binary hash and validate the native path before use."""
        digest = hashlib.sha256(
            pathlib.Path("/usr/local/libexec/xray-transit").read_bytes()
        ).hexdigest()
        if digest != self.config["binary_sha256"]:
            msg = "Native binary hash does not match the pinned value"
            raise RuntimeError(msg)
        if not active("homelab-vpn-management-relay.service"):
            msg = "Management relay must stay active for any transition"
            raise RuntimeError(msg)
        if active("homelab-vpn-transit.service"):  # retired combined service
            msg = "Retired combined transit service must never run"
            raise RuntimeError(msg)
        r = run(["ip", "route", "get", "10.250.0.2"]).stdout
        if "dev wg-socrat" not in r:
            msg = "Upstream route must leave via the reviewed wireguard interface"
            raise RuntimeError(msg)
        if "src 10.250.0.40" not in r:
            msg = "Upstream route must use the reviewed transit source address"
            raise RuntimeError(msg)

    def activate(self, reason: str) -> None:
        """Enter the xray fallback mode after all prerequisites pass."""
        if self.state["mode"] == "native-primary":
            msg = "Native primary cannot be reactivated as fallback"
            raise RuntimeError(msg)
        self.prerequisites()
        processes: list[dict[str, object]] = []
        try:
            processes = pod_processes()
        except (RuntimeError, subprocess.TimeoutExpired):
            if active(AGENT):
                raise
        if self.permit.parent.is_dir():
            self.permit.unlink(missing_ok=True)
        if self.config.get("warm_return_enabled"):
            self.save(return_boot=boot_id(), return_after=time.monotonic() + 1800)
        atomic(self.marker, {"reason": reason, "at": time.time()})
        self.save(mode="transition-to-native", healthy=False)
        run(["systemctl", "stop", AGENT], timeout=75)
        if active(AGENT):
            msg = "Worker agent still active after stop"
            raise RuntimeError(msg)
        with contextlib.suppress(RuntimeError, subprocess.TimeoutExpired):
            processes += pod_processes()
        unique = {i["pid"]: i for i in processes}
        for i in unique.values():
            terminate_owned(i)
        # During interrupted warm-up the original native relay may still own
        # every public port. Do not ask it to release those ports or restart it.
        if self.config.get("warm_return_enabled") and active(NATIVE):
            if not self.healthy():
                msg = "Native relay still owns ports but its path is unhealthy"
                raise RuntimeError(msg)
            self.save(mode="native", failures=0, healthy=True)
            self.receipt("native-preserved", reason=reason)
            return
        # Unknown owner means STOP, never kill it or start a competing listener.
        for _ in range(30):
            try:
                free_ports()
                break
            except OSError:
                time.sleep(0.2)
        free_ports()
        run(["systemctl", "start", NATIVE])
        if not active(NATIVE):
            msg = "Native relay failed to become active"
            raise RuntimeError(msg)
        for _ in range(15):
            if self.healthy():
                break
            time.sleep(1)
        if not self.healthy():
            msg = "Native relay did not become healthy after activation"
            raise RuntimeError(msg)
        self.save(mode="native", failures=0, healthy=True)
        self.receipt("native-accepted", reason=reason, owned_containers_fenced=len(unique))

    def promote(self) -> None:
        """Explicitly accept a healthy fenced native relay as the permanent primary."""
        self.prerequisites()
        if not self.marker.exists():
            msg = "Promotion requires the fallback marker"
            raise RuntimeError(msg)
        if self.state["mode"] != "native":
            msg = "Promotion requires the native fallback mode"
            raise RuntimeError(msg)
        if active(AGENT):
            msg = "Promotion requires the fenced agent to stay stopped"
            raise RuntimeError(msg)
        if not active(NATIVE):
            msg = "Promotion requires an active native relay"
            raise RuntimeError(msg)
        if not self.healthy():
            msg = "Promotion requires a healthy native relay"
            raise RuntimeError(msg)
        self.save(mode="native-primary", failures=0, healthy=True)
        self.receipt("native-primary-accepted")

    def demote(self) -> None:
        """Explicit rollback preparation; never starts a worker or releases its fence."""
        self.prerequisites()
        if not self.marker.exists():
            msg = "Demotion requires the fallback marker"
            raise RuntimeError(msg)
        if self.state["mode"] != "native-primary":
            msg = "Demotion requires the native-primary mode"
            raise RuntimeError(msg)
        if active(AGENT):
            msg = "Demotion requires the fenced agent to stay stopped"
            raise RuntimeError(msg)
        if not active(NATIVE):
            msg = "Demotion requires an active native relay"
            raise RuntimeError(msg)
        if not self.healthy():
            msg = "Demotion requires a healthy native relay"
            raise RuntimeError(msg)
        self.save(mode="native", failures=0, healthy=True)
        self.receipt("native-primary-demoted")

    def failback(self) -> None:
        """Return to the native primary path after re-validation."""
        self.prerequisites()
        if not self.marker.exists():
            msg = "Failback requires the fallback marker"
            raise RuntimeError(msg)
        if self.state["mode"] != "native":
            msg = "Failback requires the native fallback mode"
            raise RuntimeError(msg)
        if self.config.get("warm_return_enabled"):
            self.warm_return()
            if self.state.get("mode") != "kubernetes":
                msg = "Coordinated return deferred; native relay retained"
                raise RuntimeError(msg)
            return
        self.save(mode="transition-to-kubernetes", healthy=False)
        try:
            run(["systemctl", "stop", NATIVE])
            if active(NATIVE):
                msg = "Native relay still active after stop"
                raise RuntimeError(msg)
            free_ports()
            if self.permit.parent.is_dir():
                atomic(self.permit, {"owner": "kubernetes"})
            self.marker.unlink()
            fd = os.open(ROOT, os.O_DIRECTORY)
            os.fsync(fd)
            os.close(fd)
            run(["systemctl", "reset-failed", AGENT], check=False)
            run(["systemctl", "start", AGENT], timeout=75)
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                if self.healthy() and pod_processes():
                    if active(NATIVE):
                        msg = "Native relay must not stay active after cluster accept"
                        raise RuntimeError(msg)
                    self.save(mode="kubernetes", failures=0, healthy=True)
                    self.receipt("kubernetes-accepted")
                    return
                time.sleep(3)
            msg = "Pod data-path recovery deadline exceeded"
            raise RuntimeError(msg)
        except Exception:
            self.activate("failback failed; native rollback")
            raise

    @property
    def permit(self) -> pathlib.Path:
        """Path of the cluster port-ownership permit file."""
        return pathlib.Path("/var/lib/homelab-vpn-transit/port-owner/cluster")

    def agent_allowed(self) -> bool:
        """Return True only when a fenced warm return may boot the agent."""
        if not self.marker.exists():
            return True
        return (
            self.config.get("warm_return_enabled") is True
            and self.state.get("mode") == "warming"
            and self.state.get("warming_boot") == boot_id()
            and not self.permit.exists()
            and active(NATIVE)
        )

    def witness(self) -> None:
        """Run the optional external witness probe and record its verdict."""
        # Optional external validation supplements mandatory local/upstream probes.
        try:
            response = run(["/usr/local/sbin/homelab-vpn-external-probe"], timeout=7, check=False)
        except FileNotFoundError:
            self.receipt("external-validation-unavailable")
            return
        if response.returncode == WITNESS_UNAVAILABLE_EXIT:
            self.receipt("external-validation-unavailable")
        elif response.returncode:
            msg = "Reachable external VPN client rejected path"
            raise RuntimeError(msg)

    def warm_return(self) -> None:
        """Coordinate the witnessed return to the kubernetes data path."""
        # A separate SSH identity invokes a fixed flock command on socrat-0.
        # EOF releases it, including after a controller crash. Never substitute
        # a failed/queued lock with a local-only decision.
        with subprocess.Popen(
            [
                "ssh",
                "-T",
                "-F",
                "/etc/homelab-vpn-transit/transition.ssh",
                "-oBatchMode=yes",
                "-oStrictHostKeyChecking=yes",
                "-oConnectTimeout=3",
                "-oServerAliveInterval=2",
                "-oServerAliveCountMax=1",
                "vpn-transition",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as lock:
            stdout = lock.stdout
            stdin = lock.stdin
            if stdout is None or stdin is None:
                msg = "Witness lock pipes unavailable"
                raise RuntimeError(msg)
            try:
                token = b"LOCKED\n"
                reply = b""
                deadline = time.monotonic() + 5
                while reply != token:
                    left = deadline - time.monotonic()
                    if left <= 0 or not select.select([stdout], [], [], left)[0]:
                        self.receipt("return-deferred", reason="witness-lock-timeout")
                        return
                    chunk = os.read(stdout.fileno(), len(token) - len(reply))
                    reply += chunk
                    if not chunk or not token.startswith(reply):
                        self.receipt(
                            "return-deferred",
                            reason="witness-lock-not-granted",
                            ssh_status=lock.poll(),
                        )
                        return
                self._handoff(lock)
                mode_value = self.state["mode"]
                if self.config.get("persistent_witness"):
                    stdin.write(b"COMMIT\n" if mode_value == "kubernetes" else b"ABORT\n")
                    stdin.flush()
                    if lock.wait(timeout=4) != 0 or stdout.read(9) != b"RELEASED\n":
                        msg = "Unconfirmed witness release; inspect ownership before retry"
                        raise RuntimeError(msg)
            finally:
                stdin.close()
                lock.terminate()

    def _handoff(self, lock: subprocess.Popen[bytes]) -> None:
        """Perform the gated cluster takeover while holding the witness lock."""
        self.prerequisites()
        if (
            not self.marker.exists()
            or self.state["mode"] != "native"
            or active(AGENT)
            or not active(NATIVE)
        ):
            return
        if self.permit.exists() or not self.permit.parent.is_dir():
            return
        meminfo = pathlib.Path("/proc/meminfo").read_text().splitlines()
        available = next(
            (
                int(parts[1])
                for line in meminfo
                if (parts := line.split())
                and parts[0] == "MemAvailable:"
                and len(parts) == 3
                and parts[1].isdigit()
                and parts[2] == "kB"
            ),
            0,
        )
        disk = os.statvfs("/var/lib/rancher/k3s")
        if (
            available < 256 * 1024
            or disk.f_bavail * disk.f_frsize < MIN_FREE_DISK_BYTES
            or os.getloadavg()[0] > (os.cpu_count() or 1)
        ):
            return
        probe(self.config, host="10.250.0.2", source=("10.250.0.40", 0))
        self.witness()
        self.save(mode="warming", warming_boot=boot_id(), failures=0)
        try:
            run(["systemctl", "start", AGENT], timeout=90)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if lock.poll() is not None:
                    msg = "Lost independent transition lock"
                    raise RuntimeError(msg)
                owners = pod_processes()
                if len(owners) == 1 and pathlib.Path(f"/proc/{owners[0]['pid']}/exe").samefile(
                    "/usr/local/libexec/vpn-transit-gate"
                ):
                    break
                time.sleep(0.5)
            else:
                msg = "No verified relay waiting at ownership gate"
                raise RuntimeError(msg)
            self.witness()
            if lock.poll() is not None:
                msg = "Lost independent transition lock"
                raise RuntimeError(msg)
            run(["systemctl", "stop", NATIVE])
            free_ports()
            if lock.poll() is not None:
                msg = "Lost transition lock during native shutdown"
                raise RuntimeError(msg)
            atomic(self.permit, {"owner": "kubernetes"})
            until = time.monotonic() + 8
            while not self.healthy() and time.monotonic() < until:
                if lock.poll() is not None:
                    msg = "Lost transition lock during cluster acceptance"
                    raise RuntimeError(msg)
                time.sleep(0.2)
            self.witness()
            if (
                not self.healthy()
                or not pod_processes()
                or active(NATIVE)
                or lock.poll() is not None
            ):
                msg = "Unverified cluster handoff"
                raise RuntimeError(msg)
            self.save(mode="committing", failures=0)
            self.marker.unlink()
            self.save(mode="kubernetes", failures=0, healthy=True)
            self.receipt("warm-return-accepted")
        except Exception:
            self.activate("interrupted or failed warm return")
            raise

    def tick(self) -> None:
        """Run one supervision cycle of probe, decide and act."""
        if self.config.get("warm_return_enabled") and self.state["mode"] in (
            "warming",
            "committing",
        ):
            self.activate("recover interrupted warm return")
            return
        if self.state["mode"] == "prepared":
            return
        if self.marker.exists():
            ok = active(NATIVE) and self.healthy()
            # A late healthy native relay may outlive activate()'s bounded probe window.
            # Reconcile bookkeeping only: never replay activation, remove the fence or
            # start an agent. Unknown states and unhealthy transitions remain fenced.
            if self.state["mode"] == "transition-to-native" and ok:
                if active(AGENT):
                    msg = "Agent active during fenced native transition"
                    raise RuntimeError(msg)
                self.prerequisites()
                self.receipt(
                    "native-reconciled",
                    reason="native healthy after activation deadline",
                )
                self.save(mode="native", failures=0, healthy=True)
            else:
                self.save(healthy=ok, last_probe=getattr(self, "last_probe", {}))
            if ok and self.config.get("warm_return_enabled") and self.state["mode"] == "native":
                boot = boot_id()
                now = time.monotonic()
                if self.state.get("return_boot") != boot:
                    self.save(return_boot=boot, return_after=now + 1800)
                elif now >= persistent_number(self.state.get("return_after")):
                    self.save(return_after=now + 1800)
                    self.warm_return()
            return
        if self.state["mode"] != "kubernetes":
            msg = "Uncertain transition; inspect receipts, do not replay"
            raise RuntimeError(msg)
        boot = boot_id()
        if self.state.get("boot_id") != boot:
            self.save(boot_id=boot, grace_until=time.time() + 120, healthy=False, failures=0)
        ok = self.healthy()
        if not ok and time.time() < persistent_number(self.state.get("grace_until", 0)):
            self.save(healthy=False, last_probe=getattr(self, "last_probe", {}))
            return
        if ok:
            self.save(grace_until=0)
        n = 0 if ok else int(persistent_number(self.state.get("failures", 0))) + 1
        self.save(
            healthy=ok,
            failures=min(n, FAILURE_THRESHOLD),
            last_probe=getattr(self, "last_probe", {}),
        )
        if ok:
            if self.state.get("failure_scope"):
                self.save(failure_scope=None)
        elif n >= FAILURE_THRESHOLD:
            diagnosis = self.recovery_scope()
            if self.state.get("failure_scope") != diagnosis["scope"]:
                self.receipt(
                    "failure-classified",
                    **diagnosis,
                    local_probe=getattr(self, "last_probe", {}),
                )
            self.save(failure_scope=diagnosis["scope"], failure_diagnosis=diagnosis)
            if diagnosis["recover_local"]:
                self.activate("four data-path failures; " + diagnosis["scope"])

    def status(self) -> dict[str, object]:
        """Return the current mode, marker and probe summary."""
        return {
            **self.state,
            "native_active": active(NATIVE),
            "agent_active": active(AGENT),
            "fallback_marker": self.marker.exists(),
            "data_path_healthy": self.healthy(),
        }


def main() -> None:
    """Dispatch the reviewed supervisor action under the exclusive tree lock."""
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument(
        "action",
        choices=[
            "tick",
            "status",
            "activate",
            "failback",
            "promote",
            "demote",
            "agent-allowed",
        ],
    )
    a = p.parse_args()
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    # ExecCondition runs inside the controller's systemctl start operation;
    # taking the transaction lock here would deadlock the worker startup.
    if a.action == "agent-allowed":
        raise SystemExit(0 if Controller().agent_allowed() else 1)
    with (ROOT / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if a.action == "tick" else 0))
        except BlockingIOError:
            return
        c = Controller()
        if a.action == "status":
            print(json.dumps(c.status()))
        elif a.action == "activate":
            c.activate("explicit controlled activation")
        else:
            getattr(c, a.action)()


if __name__ == "__main__":
    main()
