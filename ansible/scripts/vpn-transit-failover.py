#!/usr/bin/env python3
"""Node-local Moscow relay watchdog. Never manages control-plane or management relay.
The worker agent is fenced before native start; fallback marker fences its boot.
No API availability-only failover. Native mode is sticky until explicit failback.
"""

import argparse
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
    p = subprocess.run(
        args, check=False, capture_output=True, text=True, timeout=timeout
    )
    if check and p.returncode:
        raise RuntimeError("Command failed: " + str(args[:3]))
    return p


def atomic(path, value) -> None:
    tmp = path.with_suffix(".tmp")
    data = json.dumps(value, sort_keys=True).encode()
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)


def boot_id() -> str:
    return pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def free_ports() -> bool:
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
    p = pathlib.Path("/proc") / str(pid)
    if not p.exists():
        return None
    cg = (p / "cgroup").read_text()
    assert cid in cg
    assert "kubepods" in cg or "cri-containerd" in cg
    return {"pid": pid, "cid": cid, "start": (p / "stat").read_text().split()[21]}


def pod_processes() -> list[dict[str, object]]:
    p = run(["k3s", "crictl", "--timeout=5s", "ps", "-o", "json"], timeout=9)
    result: list[dict[str, object]] = []
    for c in json.loads(p.stdout)["containers"]:
        labels = c.get("labels", {})
        if (
            labels.get("io.kubernetes.pod.namespace") != "vpn-transit"
            or not labels.get("io.kubernetes.pod.name", "").startswith("vpn-transit-")
            or labels.get("io.kubernetes.pod.name", "").startswith(
                "vpn-transit-rehearsal-"
            )
            or labels.get("io.kubernetes.container.name") != "relay"
        ):
            continue
        v = json.loads(
            run(["k3s", "crictl", "--timeout=5s", "inspect", c["id"]], timeout=9).stdout
        )
        i = identity(int(v["info"]["pid"]), str(c["id"]))
        if i:
            result.append(i)
    return result


def terminate_owned(i: dict[str, object]) -> None:
    pid_value = i["pid"]
    if not isinstance(pid_value, int):
        reason = "Unusable container pid"
        raise TypeError(reason)
    pid = pid_value
    cid = str(i["cid"])
    now = identity(pid, cid)
    if now is None:
        return
    assert now == i
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
    # Same strict TLS/WS identity and ACLs on the local and direct upstream path.
    d = detail if detail is not None else {}
    d.update(at=time.time(), stage="connect", ok=False)
    try:
        for port in (32053, 32083, 32084):
            d.update(stage="tcp", port=port)
            with socket.create_connection(
                (host, port), timeout=2, source_address=source
            ):
                pass
        d.update(stage="tcp", port=443)
        with socket.create_connection(
            (host, 443), timeout=3, source_address=source
        ) as sock:
            d["stage"] = "tls"
            with ssl.create_default_context().wrap_socket(
                sock, server_hostname="vpn.alchemmist.xyz"
            ) as t:
                d["stage"] = "websocket"
                req = (
                    "GET "
                    + str(config["ws_path"])
                    + " HTTP/1.1\r\nHost: vpn.alchemmist.xyz\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
                )
                t.sendall(req.encode())
                line = t.recv(1024).split(b"\r\n")[0]
                # Record only the numeric HTTP status, never the private path/response body.
                parts = line.split()
                d["http_status"] = (
                    int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                )
                assert d["http_status"] == 101
        d.update(stage="complete", ok=True)
        return True
    except (OSError, AssertionError, ssl.SSLError) as e:
        d.update(error=type(e).__name__, errno=getattr(e, "errno", None))
        raise


def local_listeners_respond() -> bool:
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

        self.config = json.loads(CONFIG.read_text())
        self.marker = ROOT / "fallback.active"
        self.state: dict[str, object] = (
            json.loads((ROOT / "state.json").read_text())
            if (ROOT / "state.json").exists()
            else {"mode": "prepared", "failures": 0}
        )

    def save(self, **fields) -> None:
        """Persist updated state fields atomically."""
        self.state.update(fields)
        atomic(ROOT / "state.json", self.state)

    def receipt(self, action, **fields) -> None:
        """Append a timestamped receipt file for the taken action."""
        v = {"action": action, "at": time.time(), **fields}
        atomic(ROOT / (str(time.time_ns()) + "-" + action + ".json"), v)

    def healthy(self) -> bool:
        """Probe endpoints and update the persistent last-probe results."""
        self.last_probe: dict[str, object] = {}
        try:
            probe(self.config, detail=self.last_probe)
            return True
        except (OSError, AssertionError, ssl.SSLError):
            return False

    def recovery_scope(self) -> Diagnosis:
        # Only after the existing four failures. An upstream outage is not evidence
        # that stopping a still-listening local worker can improve the data path.
        """Determine the scope of local recovery, if any is warranted."""
        detail: dict[str, object] = {}
        try:
            probe(
                self.config, host="10.250.0.2", source=("10.250.0.40", 0), detail=detail
            )
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
        except (OSError, AssertionError, ssl.SSLError):
            return {
                "recover_local": False,
                "scope": "upstream-or-path-unhealthy",
                "upstream_probe": detail,
            }

    def prerequisites(self) -> None:
        """Pin the binary hash and validate the native path before use."""
        assert (
            hashlib.sha256(
                pathlib.Path("/usr/local/libexec/xray-transit").read_bytes()
            ).hexdigest()
            == self.config["binary_sha256"]
        )
        assert active("homelab-vpn-management-relay.service")
        assert not active("homelab-vpn-transit.service")  # retired combined service
        r = run(["ip", "route", "get", "10.250.0.2"]).stdout
        assert "dev wg-socrat" in r
        assert "src 10.250.0.40" in r

    def activate(self, reason: str) -> None:
        """Enter the xray fallback mode after all prerequisites pass."""
        assert self.state["mode"] != "native-primary", (
            "Native primary cannot be reactivated as fallback"
        )
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
        assert not active(AGENT)
        with contextlib.suppress(RuntimeError, subprocess.TimeoutExpired):
            processes += pod_processes()
        unique = {i["pid"]: i for i in processes}
        for i in unique.values():
            terminate_owned(i)
        # During interrupted warm-up the original native relay may still own
        # every public port. Do not ask it to release those ports or restart it.
        if self.config.get("warm_return_enabled") and active(NATIVE):
            if not self.healthy():
                raise RuntimeError(
                    "Native relay still owns ports but its path is unhealthy"
                )
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
        assert active(NATIVE)
        for _ in range(15):
            if self.healthy():
                break
            time.sleep(1)
        assert self.healthy()
        self.save(mode="native", failures=0, healthy=True)
        self.receipt(
            "native-accepted", reason=reason, owned_containers_fenced=len(unique)
        )

    def promote(self) -> None:
        """Explicitly accept a healthy fenced native relay as the permanent primary."""
        self.prerequisites()
        assert self.marker.exists()
        assert self.state["mode"] == "native"
        assert not active(AGENT)
        assert active(NATIVE)
        assert self.healthy()
        self.save(mode="native-primary", failures=0, healthy=True)
        self.receipt("native-primary-accepted")

    def demote(self) -> None:
        """Explicit rollback preparation; never starts a worker or releases its fence."""
        self.prerequisites()
        assert self.marker.exists()
        assert self.state["mode"] == "native-primary"
        assert not active(AGENT)
        assert active(NATIVE)
        assert self.healthy()
        self.save(mode="native", failures=0, healthy=True)
        self.receipt("native-primary-demoted")

    def failback(self) -> None:
        """Return to the native primary path after re-validation."""
        self.prerequisites()
        assert self.marker.exists()
        assert self.state["mode"] == "native"
        if self.config.get("warm_return_enabled"):
            self.warm_return()
            if self.state["mode"] != "kubernetes":
                raise RuntimeError("Coordinated return deferred; native relay retained")
            return
        self.save(mode="transition-to-kubernetes", healthy=False)
        try:
            run(["systemctl", "stop", NATIVE])
            assert not active(NATIVE)
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
                    assert not active(NATIVE)
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
    def permit(self):
        return pathlib.Path("/var/lib/homelab-vpn-transit/port-owner/cluster")

    def agent_allowed(self):
        if not self.marker.exists():
            return True
        return (
            self.config.get("warm_return_enabled") is True
            and self.state.get("mode") == "warming"
            and self.state.get("warming_boot") == boot_id()
            and not self.permit.exists()
            and active(NATIVE)
        )

    def witness(self):
        run(["/usr/local/sbin/homelab-vpn-external-probe"], timeout=7)

    def warm_return(self):
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
            try:
                if not select.select([lock.stdout], [], [], 5)[0]:
                    self.receipt("return-deferred", reason="witness-lock-timeout")
                    return
                if os.read(lock.stdout.fileno(), 7) != b"LOCKED\n":
                    self.receipt("return-deferred", reason="witness-lock-not-granted", ssh_status=lock.poll())
                    return
                self._handoff(lock)
            finally:
                lock.stdin.close()
                lock.terminate()

    def _handoff(self, lock):
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
        available = int(
            pathlib.Path("/proc/meminfo")
            .read_text()
            .split("MemAvailable:")[1]
            .split()[0]
        )
        disk = os.statvfs("/var/lib/rancher/k3s")
        if (
            available < 256 * 1024
            or disk.f_bavail * disk.f_frsize < 2 * 1024**3
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
                    raise RuntimeError("Lost independent transition lock")
                owners = pod_processes()
                if len(owners) == 1 and os.path.samefile(
                    f"/proc/{owners[0]['pid']}/exe",
                    "/usr/local/libexec/vpn-transit-gate",
                ):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("No verified relay waiting at ownership gate")
            self.witness()
            if lock.poll() is not None:
                raise RuntimeError("Lost independent transition lock")
            run(["systemctl", "stop", NATIVE])
            free_ports()
            atomic(self.permit, {"owner": "kubernetes"})
            until = time.monotonic() + 8
            while not self.healthy() and time.monotonic() < until:
                time.sleep(0.2)
            self.witness()
            if (
                not self.healthy()
                or not pod_processes()
                or active(NATIVE)
                or lock.poll() is not None
            ):
                raise RuntimeError("Unverified cluster handoff")
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
            if (
                ok
                and self.config.get("warm_return_enabled")
                and self.state["mode"] == "native"
            ):
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
            self.save(
                boot_id=boot, grace_until=time.time() + 120, healthy=False, failures=0
            )
        ok = self.healthy()
        if not ok and time.time() < persistent_number(self.state.get("grace_until", 0)):
            self.save(healthy=False, last_probe=getattr(self, "last_probe", {}))
            return
        if ok:
            self.save(grace_until=0)
        n = 0 if ok else int(persistent_number(self.state.get("failures", 0))) + 1
        self.save(
            healthy=ok, failures=min(n, 4), last_probe=getattr(self, "last_probe", {})
        )
        if ok:
            if self.state.get("failure_scope"):
                self.save(failure_scope=None)
        elif n >= 4:
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
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
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
    # ExecCondition runs inside the controller's systemctl start operation;
    # taking the transaction lock here would deadlock the worker startup.
    if a.action == "agent-allowed":
        raise SystemExit(0 if Controller().agent_allowed() else 1)
    with (ROOT / "lock").open("a") as lock:
        try:
            fcntl.flock(
                lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if a.action == "tick" else 0)
            )
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
