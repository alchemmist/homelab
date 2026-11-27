#!/usr/bin/env python3
"""Watchdog service that detects VPN failures and triggers homelab failover."""

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import select
import signal
import socket
import sqlite3
import ssl
import subprocess
import time
from pathlib import Path

CONFIG_PATH = "/etc/homelab-vpn-failover/config.json"
STATE_DIR = "/var/lib/homelab-vpn-failover"
NATIVE_UNITS = ["homelab-vpn-primary.service", "homelab-vpn-caddy.service"]


class Watchdog:
    """Watchdog that monitors link health and triggers VPN failover."""

    def __init__(self, config) -> None:
        """Initialize the failover watchdog."""
        self.config = config
        self.state = Path(config.get("state_dir", STATE_DIR))
        self.agent = config.get("agent_unit", "k3s.service")
        self.fenced_units = list(
            dict.fromkeys(
                [
                    *config.get("fenced_units", ["k3s-agent.service", "k3s.service"]),
                    self.agent,
                ]
            )
        )
        self.units = config.get("native_units", NATIVE_UNITS)
        self.timeout = config.get("timeout_seconds", 4)

    def write(self, name, data) -> None:
        """Persist state data atomically to the state directory."""
        target = self.state / name
        temporary = target.with_suffix(".tmp")
        with temporary.open("w") as stream:
            os.chmod(temporary, 0o600)
            stream.write(json.dumps(data))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        descriptor = os.open(self.state, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def command(self, *args):
        # A rejoining etcd voter may need longer than ordinary unit operations.
        """Run a command with the configured timeout and return its stdout."""
        timeout = (
            self.config.get("kubernetes_start_timeout_seconds", 180)
            if len(args) == 3
            and args[:2] == ("systemctl", "start")
            and args[2] in self.fenced_units
            else 40
        )
        return subprocess.run(
            args, check=True, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()

    def service_installed(self, unit) -> bool:
        """Report whether a systemd unit is installed on this host."""
        state = self.command(
            "systemctl", "show", unit, "--property=LoadState", "--value"
        )
        if state == "not-found":
            return False
        if state not in ("loaded", "masked"):
            raise RuntimeError("Cannot verify systemd unit: " + unit + ": " + state)
        return True

    def service_active(self, unit):
        """Report whether a systemd unit is currently active."""
        return self.command(
            "systemctl", "show", unit, "--property=ActiveState", "--value"
        ) not in (
            "inactive",
            "failed",
        )

    def kubernetes_group(self, group):
        """Check whether a cgroup belongs to Kubernetes or a fenced unit."""
        return "kubepods" in group or any(
            "/" + unit in group for unit in self.fenced_units
        )

    def processes(self):
        """Enumerate Kubernetes processes with their cgroup and cmdline."""
        result = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                group = (entry / "cgroup").read_text()
                status = (entry / "stat").read_text().rsplit(")", 1)[1].split()[0]
            except FileNotFoundError:
                continue
            if status != "Z" and self.kubernetes_group(group):
                result.append(int(entry.name))
        return result

    def terminate(self, pid, sig) -> None:
        """Signal a PID and wait for it to exit via pidfd."""
        try:
            descriptor = os.pidfd_open(pid)
        except ProcessLookupError:
            return
        try:
            try:
                group = Path("/proc", str(pid), "cgroup").read_text()
            except FileNotFoundError:
                return
            if not self.kubernetes_group(group):
                msg = "Process cgroup changed while fencing"
                raise RuntimeError(msg)
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(descriptor, sig)
        finally:
            os.close(descriptor)

    def fence(self) -> None:
        """Stop and mask the fenced services, then kill Kubernetes processes."""
        installed = [unit for unit in self.fenced_units if self.service_installed(unit)]
        for unit in installed:
            self.command("systemctl", "stop", unit)
        if any(self.service_active(unit) for unit in installed):
            msg = "Kubernetes service did not stop"
            raise RuntimeError(msg)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in self.processes():
                self.terminate(pid, sig)
            deadline = time.monotonic() + self.config.get("fence_timeout_seconds", 10)
            while self.processes() and time.monotonic() < deadline:
                time.sleep(0.2)
            if not self.processes():
                return
        msg = "Kubernetes processes remain; refusing native startup"
        raise RuntimeError(msg)

    def guard(self) -> None:
        """Validate state consistency before any failover action is taken."""
        if (
            not (self.state / "active").exists()
            or any(
                self.service_installed(unit) and self.service_active(unit)
                for unit in self.fenced_units
            )
            or self.processes()
        ):
            msg = "Native startup requires verified Kubernetes fencing"
            raise RuntimeError(msg)

    def occupied(self):
        """Report which configured listen ports are already bound on this host."""
        wanted = {
            (item["protocol"], int(item["port"]))
            for item in self.config["listen_ports"]
        }
        found = set()
        for protocol in ("tcp", "udp"):
            for suffix in ("", "6"):
                for line in (
                    Path("/proc/net/" + protocol + suffix).read_text().splitlines()[1:]
                ):
                    fields = line.split()
                    if protocol == "tcp" and fields[3] != "0A":
                        continue
                    port = int(fields[1].rsplit(":", 1)[1], 16)
                    if (protocol, port) in wanted:
                        found.add((protocol, port))
        return sorted(found)

    def preflight(self) -> None:
        """Verify required preflight files exist and are non-empty."""
        for name in self.config.get("preflight_files", []):
            path = Path(name)
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError("Required fallback file missing or empty: " + name)
        for name in self.config.get("databases", []):
            path = Path(name)
            if not path.is_file() or path.stat().st_size == 0:
                msg = "VPN database missing or empty"
                raise RuntimeError(msg)
            with sqlite3.connect(
                path.as_uri() + "?mode=ro", uri=True, timeout=self.timeout
            ) as database:
                if database.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    msg = "VPN database integrity check failed"
                    raise RuntimeError(msg)

    def health(self):
        """Probe configured TCP endpoints and collect per-host failures."""
        errors = []
        for host, port in self.config["tcp_endpoints"]:
            try:
                with socket.create_connection((host, port), self.timeout):
                    pass
            except OSError:
                errors.append("TCP listener unavailable: " + str(port))
        ws = self.config["websocket"]
        stage = "tcp_connect"
        diagnostics = {}
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            context = ssl.create_default_context()
            with socket.create_connection(
                (ws.get("address", "127.0.0.1"), ws.get("port", 443)), self.timeout
            ) as raw:
                stage = "tls_handshake"
                with context.wrap_socket(raw, server_hostname=ws["host"]) as stream:
                    stage = "websocket_response"
                    request = f"GET {ws['path']} HTTP/1.1\r\nHost: {ws['host']}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
                    stream.sendall(request.encode())
                    response = b""
                    deadline = time.monotonic() + self.timeout
                    while b"\r\n\r\n" not in response and len(response) < 16384:
                        stream.settimeout(max(0.01, deadline - time.monotonic()))
                        part = stream.recv(4096)
                        if not part or time.monotonic() >= deadline:
                            break
                        response += part
                    lines = (
                        response.split(b"\r\n\r\n", 1)[0].decode("latin1").split("\r\n")
                    )
                    headers = dict(
                        line.lower().split(":", 1) for line in lines[1:] if ":" in line
                    )
                    expected = base64.b64encode(
                        hashlib.sha1(
                            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                        ).digest()
                    ).decode()
                    status = lines[0].split()[1] if len(lines[0].split()) >= 2 else ""
                    diagnostics["http_status"] = (
                        int(status) if status.isdigit() else None
                    )
                    if len(lines[0].split()) < 2 or lines[0].split()[1] != "101":
                        msg = "WebSocket upgrade rejected"
                        raise ValueError(msg)
                    accept = next(
                        (
                            line.split(":", 1)[1].strip()
                            for line in lines[1:]
                            if line.lower().startswith("sec-websocket-accept:")
                        ),
                        "",
                    )
                    if (
                        accept != expected
                        or headers.get("upgrade", "").strip() != "websocket"
                    ):
                        msg = "WebSocket handshake invalid"
                        raise ValueError(msg)
        except (OSError, ValueError) as error:
            errors.append("Public VPN TLS/WebSocket handshake failed")
            diagnostics.update(stage=stage, exception=type(error).__name__)
            if isinstance(error, ssl.SSLCertVerificationError):
                diagnostics["tls_verify_code"] = error.verify_code
            if isinstance(error, OSError) and error.errno is not None:
                diagnostics["errno"] = error.errno
            # Never log exception text: it may contain private paths or URLs.
            return {
                "healthy": False,
                "errors": errors,
                "websocket_diagnostics": diagnostics,
            }
        return {"healthy": not errors, "errors": errors}

    def clock(self):
        """Return the boot identifier and current uptime in seconds."""
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip(), float(
            Path("/proc/uptime").read_text().split()[0]
        )

    def counters(self, boot):
        """Load accumulated failure counters if they belong to this boot."""
        try:
            saved = json.loads((self.state / "failures.json").read_text())
        except (FileNotFoundError, ValueError):
            saved = {}
        return (
            saved
            if saved.get("boot_id") == boot
            else {
                "boot_id": boot,
                "failures": 0,
                "grace_until": self.config.get("boot_grace_seconds", 180),
            }
        )

    def fencing_evidence(self, health):
        """Require loss of the workload, its traffic path and local self-repair."""
        errors = health.get("errors", [])
        port = self.config.get("vpn_workload_port", 32087)
        if health["healthy"] or not {
            f"TCP listener unavailable: {port}",
            "Public VPN TLS/WebSocket handshake failed",
        }.issubset(errors):
            return False
        # An active/starting service can still repair the workload. A failed CRI
        # request alone cannot establish absence: look for surviving containers.
        if self.service_active(self.agent):
            return False
        for pid in self.processes():
            path = Path("/proc") / str(pid)
            try:
                if "kubepods" in (path / "cgroup").read_text() and (
                    (path / "comm")
                    .read_text()
                    .strip()
                    .lower()
                    .startswith(("xray", "x-ui"))
                ):
                    return False
            except FileNotFoundError:
                continue
        return True

    def return_window(self):
        """Persistent monotonic cooldown; reboot or entry into fallback starts it anew."""
        boot, uptime = self.clock()
        marker = (self.state / "active").stat()
        generation = [boot, marker.st_ino, marker.st_mtime_ns]
        try:
            record = json.loads((self.state / "return-window.json").read_text())
        except (FileNotFoundError, ValueError):
            record = {}
        if record.get("generation") != generation:
            record = {"generation": generation, "due": uptime + 1800}
            self.write("return-window.json", record)
        return max(0, record["due"] - uptime)

    def confirm_failure(self, *, fencing=False):
        # Independent samples, under the existing lock, before destructive action.
        """Re-check health independently before any destructive action."""
        for _ in range(max(1, int(self.config.get("confirmation_checks", 2)))):
            time.sleep(max(0, self.config.get("confirmation_interval_seconds", 1)))
            health = self.health()
            if health["healthy"] or (fencing and not self.fencing_evidence(health)):
                return False, health
        return True, health

    def native_warmup(self) -> None:
        """Record bootstrap evidence that native WireGuard came up cleanly."""
        boot, uptime = self.clock()
        self.write(
            "native_warmup.json",
            {
                "boot_id": boot,
                "until": uptime + self.config.get("native_start_grace_seconds", 30),
            },
        )

    def start_native_units(self) -> None:
        """Start every non-running native unit after a port warmup marker."""
        started = False
        for unit in self.units:
            if not self.service_active(unit):
                assigned = {
                    (item["protocol"], int(item["port"]))
                    for item in self.config.get("native_unit_ports", {}).get(unit, [])
                }
                if assigned.intersection(self.occupied()):
                    raise RuntimeError("Native service ports occupied: " + unit)
                if not started:
                    self.native_warmup()
                started = True
                self.command("systemctl", "start", unit)

    def restart_recovery(self, boot: str) -> dict[str, object]:
        """Stop, re-guard and restart every native unit after a confirmed failure."""
        self.write("fallback_failures.json", {"boot_id": boot, "failures": 0})
        for unit in reversed(self.units):
            self.command("systemctl", "stop", unit)
        if any(self.service_active(unit) for unit in self.units) or self.occupied():
            msg = "Native VPN did not release ports for recovery restart"
            raise RuntimeError(msg)
        self.guard()
        self.native_warmup()
        for unit in self.units:
            self.command("systemctl", "start", unit)
        return {"mode": "fallback", "restarted": True, **self.health()}

    def activate(self):
        """Enter fallback mode after preflight, arming the active marker."""
        self.preflight()
        if not (self.state / "active").exists():
            self.write("active", {"activated_at": time.time()})
        if self.config.get("warm_return_enabled"):
            self.owner_permit.unlink(missing_ok=True)
        self.fence()
        running = [unit for unit in self.units if self.service_active(unit)]
        if not running and self.occupied():
            msg = "VPN ports still occupied; refusing native startup"
            raise RuntimeError(msg)
        self.guard()
        self.start_native_units()
        health = self.health()
        boot, uptime = self.clock()
        try:
            warmup = json.loads((self.state / "native_warmup.json").read_text())
        except (FileNotFoundError, ValueError):
            warmup = {}
        if (
            not health["healthy"]
            and warmup.get("boot_id") == boot
            and uptime < warmup.get("until", 0)
        ):
            self.write("fallback_failures.json", {"boot_id": boot, "failures": 0})
            return {"mode": "fallback", "warming_up": True, "failures": 0, **health}
        try:
            saved = json.loads((self.state / "fallback_failures.json").read_text())
        except (FileNotFoundError, ValueError):
            saved = {}
        failures = saved.get("failures", 0) if saved.get("boot_id") == boot else 0
        failures = 0 if health["healthy"] else failures + 1
        if failures >= self.config.get("failure_threshold", 4):
            confirmed, health = self.confirm_failure()
            if not confirmed:
                self.write("fallback_failures.json", {"boot_id": boot, "failures": 0})
                return {
                    "mode": "fallback",
                    "restart_cancelled": True,
                    "failures": 0,
                    **health,
                }
            return self.restart_recovery(boot)
        self.write("fallback_failures.json", {"boot_id": boot, "failures": failures})
        return {"mode": "fallback", "failures": failures, **health}

    @property
    def owner_permit(self):
        return Path("/var/lib/homelab-vpn-owner/cluster")

    def cancel_warm_return(self):
        self.owner_permit.unlink(missing_ok=True)
        self.write("active", {"reason": "warm return rollback"})
        self.fence()
        (self.state / "warming").unlink(missing_ok=True)
        return self.activate()

    def cluster_query(self, *args):
        return self.command(
            "k3s",
            "kubectl",
            "--server=" + self.config["return_api"],
            "--request-timeout=4s",
            *args,
        )

    def guarded_workloads(self, running=False):
        for ns, name in (("x-ui", "primary"), ("traefik-edge", "traefik")):
            pods = json.loads(
                self.cluster_query(
                    "-n",
                    ns,
                    "get",
                    "pods",
                    "--field-selector",
                    "spec.nodeName=socrat-2",
                    "-o",
                    "json",
                )
            )["items"]
            relevant = [
                pod
                for pod in pods
                if any(c["name"] == name for c in pod["spec"]["containers"])
            ]
            if running:
                if len(relevant) != 1 or relevant[0]["metadata"].get(
                    "deletionTimestamp"
                ):
                    return False
                pod = relevant[0]
                spec = pod["spec"]
            else:
                # Recreate waits for kubelet to acknowledge old deletions. A
                # terminating API object is not proof a process still exists.
                # Accept it only after the node-local runtime is verified fenced.
                if self.service_active(self.agent) or self.processes():
                    return False
                if any(not p["metadata"].get("deletionTimestamp") for p in relevant):
                    return False
                deployment = json.loads(
                    self.cluster_query("-n", ns, "get", "deployment", ns, "-o", "json")
                )
                spec = deployment["spec"]["template"]["spec"]
                if deployment["spec"]["strategy"]["type"] != "Recreate":
                    return False
            if len(spec["containers"]) != 1 or spec["containers"][0]["name"] != name:
                return False
            c = spec["containers"][0]
            target = (
                "/app/DockerEntrypoint.sh" if ns == "x-ui" else '/entrypoint.sh "$@"'
            )
            if c.get("command") != [
                "/bin/sh",
                "-ec",
                "until test -f /run/vpn-owner/cluster; do sleep 0.2; done; exec "
                + target,
                "--",
            ]:
                return False
            if not any(
                v.get("name") == "vpn-owner"
                and v.get("hostPath", {}).get("path") == str(self.owner_permit.parent)
                for v in spec["volumes"]
            ):
                return False
            if not any(
                v.get("name") == "vpn-owner"
                and v.get("mountPath") == "/run/vpn-owner"
                and v.get("readOnly")
                for v in c["volumeMounts"]
            ):
                return False
            if running and not any(
                "running" in st["state"]
                for st in pod["status"].get("containerStatuses", [])
            ):
                return False
        return True

    def confirm_return_path(self, probe):
        # A cold ingress may not accept the first connection. Bound the whole
        # acceptance window, not just the interval between samples.
        until = time.monotonic() + 8
        while time.monotonic() < until:
            try:
                subprocess.run(
                    [probe],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(0.01, until - time.monotonic()),
                )
                return
            except FileNotFoundError:
                self.write("external-validation.json", {"status": "unavailable", "at": time.time()})
                return
            except subprocess.CalledProcessError as error:
                # SSH transport unavailable is not evidence of a broken tunnel.
                # A reachable client reporting failure still vetoes the handoff.
                if error.returncode == 255:
                    self.write("external-validation.json", {"status": "unavailable", "at": time.time()})
                    return
                time.sleep(.2)
            except subprocess.TimeoutExpired:
                time.sleep(.2)
        raise RuntimeError("External VPN acceptance deadline expired")

    def coordinated_return(self):
        """A witness outage or busy shared lock defers the transfer, never forces it."""
        with subprocess.Popen(
            [
                "ssh",
                "-T",
                "-F",
                "/etc/homelab-vpn-failover/transition.ssh",
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
                if (
                    not select.select([lock.stdout], [], [], 5)[0]
                    or lock.stdout.readline() != b"LOCKED\n"
                ):
                    return {"mode": "fallback", "return_deferred": True}
                result = self.warm_return(lock)
                completed = result.get("mode") == "kubernetes"
                if self.config.get("persistent_witness"):
                    lock.stdin.write(b"COMMIT\n" if completed else b"ABORT\n")
                    lock.stdin.flush()
                    if lock.wait(timeout=4) != 0 or lock.stdout.read(9) != b"RELEASED\n":
                        raise RuntimeError("Unconfirmed witness release; inspect ownership before retry")
                return result
            finally:
                lock.stdin.close()
                lock.terminate()

    def warm_return(self, lock=None):
        # Preflight must not remove a fence. The external probe is a provisioned,
        # root-owned executable that makes a fresh authenticated VPN request.
        probe = "/usr/local/sbin/homelab-vpn-external-probe"
        mem = Path("/proc/meminfo").read_text().split("MemAvailable:")[1].split()[0]
        fs = os.statvfs("/var/lib/rancher/k3s")
        if (
            int(mem) < 512 * 1024
            or os.getloadavg()[0] > (os.cpu_count() or 1)
            or fs.f_bavail * fs.f_frsize < 2 * 1024**3
            or not self.owner_permit.parent.is_dir()
            or not self.guarded_workloads()
        ):
            return {"mode": "fallback", "return_deferred": True}
        self.confirm_return_path(probe)
        self.owner_permit.unlink(missing_ok=True)
        self.write("warming", {"started": time.time()})
        try:
            self.command("systemctl", "start", self.agent)
            self.cluster_query(
                "wait", "--for=condition=Ready", "node/socrat-2", "--timeout=35s"
            )
            deadline = time.monotonic() + 90
            while (
                not self.guarded_workloads(running=True) and time.monotonic() < deadline
            ):
                time.sleep(1)
            if not self.guarded_workloads(running=True) or not self.health()["healthy"]:
                raise RuntimeError(
                    "Warm-up did not preserve workload isolation and native path"
                )
            self.confirm_return_path(probe)
            if lock is not None and lock.poll() is not None:
                raise RuntimeError("Lost independent transition lock")
            for unit in reversed(self.units):
                self.command("systemctl", "stop", unit)
            if any(self.service_active(u) for u in self.units) or self.occupied():
                raise RuntimeError("Native runtime did not release ownership")
            self.owner_permit.touch(exist_ok=False)
            self.confirm_return_path(probe)
            if not self.health()["healthy"]:
                raise RuntimeError("Cluster ingress not healthy")
            (self.state / "active").unlink()
            (self.state / "warming").unlink()
            return {"mode": "kubernetes", "warm_return": True}
        except Exception:
            self.cancel_warm_return()
            raise

    def tick(self):
        """Run one supervision cycle and return the resulting mode summary."""
        if (self.state / "warming").exists():
            return self.cancel_warm_return()
        if (self.state / "inhibit").exists():
            return {"mode": "inhibited"}
        if (self.state / "active").exists():
            remaining = self.return_window()
            native = self.activate()
            if (
                self.config.get("warm_return_enabled")
                and not remaining
                and native.get("healthy")
            ):
                if self.config.get("coordinated_return"):
                    return self.coordinated_return()
                return self.warm_return()
            return {**native, "return_cooldown_seconds": remaining}
        boot, uptime = self.clock()
        saved = self.counters(boot)
        if uptime < saved["grace_until"]:
            return {"mode": "grace"}
        health = self.health()
        saved["failures"] = (
            saved["failures"] + 1 if self.fencing_evidence(health) else 0
        )
        self.write("failures.json", saved)
        if not health["healthy"]:
            self.write(
                "last_failure.json",
                {"mode": "kubernetes", "boot_id": boot, "uptime": uptime, **health},
            )
        if saved["failures"] >= self.config.get("failure_threshold", 4):
            confirmed, health = self.confirm_failure(fencing=True)
            if not confirmed:
                saved["failures"] = 0
                self.write("failures.json", saved)
                return {
                    "mode": "kubernetes",
                    "activation_cancelled": True,
                    "failures": 0,
                    **health,
                }
            return self.activate()
        return {"mode": "kubernetes", "failures": saved["failures"], **health}

    def rehearse_warm_failback(self, backend):
        """Exercise the staged protocol with an injected lab backend, never from tick."""
        # Holding workloads must survive kubelet restarts, not just prevent scheduling.
        backend.hold_cluster_vpn_and_ingress()
        try:
            backend.start_cluster()
            backend.verify_cluster_ready_and_native_path()
            backend.prepare_images_and_verify_holds()
            backend.stop_native()
            backend.verify_native_released()
            backend.release_cluster_workloads()
            backend.verify_external_cluster_tunnel()
        except Exception:
            # Even a partial release/start must be undone. Never start a second writer
            # when fencing fails; propagate that failure for operator intervention.
            backend.fence_cluster_and_verify_release()
            backend.ensure_native_running()
            raise
        return {"mode": "kubernetes"}

    def failback(self):
        """Exit fallback mode and restart the primary Kubernetes path."""
        if not (self.state / "active").exists():
            msg = "Fallback is not active"
            raise RuntimeError(msg)
        if not self.service_installed(self.agent):
            msg = "Configured Kubernetes service is not installed; keeping native VPN"
            raise RuntimeError(msg)
        if self.agent == "k3s-agent.service" and self.service_installed("k3s.service"):
            msg = "Legacy agent target conflicts with installed server; keeping native VPN"
            raise RuntimeError(msg)
        self.fence()
        for unit in reversed(self.units):
            self.command("systemctl", "stop", unit)
        if any(self.service_active(unit) for unit in self.units) or self.occupied():
            msg = "Native VPN has not released its ports; keeping Kubernetes fenced"
            raise RuntimeError(msg)
        boot, uptime = self.clock()
        self.write(
            "failures.json",
            {
                "boot_id": boot,
                "failures": 0,
                "grace_until": uptime + self.config.get("boot_grace_seconds", 180),
            },
        )
        (self.state / "active").unlink()
        descriptor = os.open(self.state, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            self.command("systemctl", "start", self.agent)
        except Exception:
            self.write(
                "active", {"activated_at": time.time(), "reason": "failback failed"}
            )
            self.fence()
            # Restore service immediately, rather than waiting for the next timer.
            self.activate()
            raise
        return {"mode": "kubernetes", "grace": True}

    def status(self):
        """Return the current failover mode and inhibition summary."""
        return {
            "mode": "fallback" if (self.state / "active").exists() else "kubernetes",
            "inhibited": (self.state / "inhibit").exists(),
            **self.health(),
        }


def main() -> int | None:
    """Execute the main operation."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["tick", "check", "status", "guard", "failback"]
    )
    parser.add_argument("--config", default=CONFIG_PATH)
    args = parser.parse_args()
    try:
        watchdog = Watchdog(json.loads(Path(args.config).read_text()))
        if args.action in ("tick", "failback"):
            watchdog.state.mkdir(mode=0o700, parents=True, exist_ok=True)
            with (watchdog.state / "lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = getattr(watchdog, args.action)()
        else:
            result = getattr(
                watchdog, "health" if args.action == "check" else args.action
            )()
        print(json.dumps(result or {"guard": True}))
        return 1 if result and result.get("healthy") is False else 0
    except Exception as error:
        print(json.dumps({"error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
