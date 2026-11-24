"""Watchdog that monitors open-terminal browser processes and reaps stale sessions."""

import json
import logging
import os
import signal
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Never, override

ProcessIdentity = tuple[int, int]


class JsonFormatter(logging.Formatter):
    """Logging formatter that emits structured JSON records."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Render a log record as JSON, omitting exception text."""
        # Do not render exception text/tracebacks: they can contain process arguments.
        event = getattr(record, "event", "watchdog_error")
        result = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": {10: "debug", 20: "info", 30: "warn"}.get(record.levelno, "error"),
            "service": "open-terminal-browser-watchdog",
            "msg": event,
            "event": event,
        }
        for key in ("pid", "age_seconds", "processes", "signal"):
            value = getattr(record, key, None)
            if isinstance(value, (int, float)):
                result[key] = value
        return json.dumps(result, separators=(",", ":"))


@dataclass(frozen=True)
class Process:
    """Immutable record of a managed browser process."""

    pid: int
    ppid: int
    start: int
    executable: str
    args: tuple[str, ...]

    @property
    def identity(self) -> ProcessIdentity:
        """Stable (pid, start-ticks) identity of the process."""
        return self.pid, self.start


def read_process(pid: int, proc: Path = Path("/proc")) -> Process | None:
    try:
        directory = proc / str(pid)
        stat = (directory / "stat").read_text()
        fields = stat[stat.rindex(")") + 2 :].split()
        args = tuple(
            part.decode(errors="replace")
            for part in (directory / "cmdline").read_bytes().split(b"\0")
            if part
        )
        executable = Path(os.readlink(directory / "exe")).name
        return Process(pid, int(fields[1]), int(fields[19]), executable, args)
    except (OSError, ValueError, IndexError):
        return None


def snapshot(proc: Path = Path("/proc")) -> dict[int, Process]:
    result = {}
    for directory in proc.iterdir():
        if directory.name.isdigit():
            process = read_process(int(directory.name), proc)
            if process is not None:
                result[process.pid] = process
    return result


def is_test_browser(process: Process) -> bool:
    return (
        process.executable in {"chrome", "chromium", "headless_shell", "chrome-headless-shell"}
        and any(arg == "--headless" or arg.startswith("--headless=") for arg in process.args)
        and "--remote-debugging-pipe" in process.args
        and any(arg.startswith("--user-data-dir=/tmp/playwright_") for arg in process.args)
        and not any(arg == "--type" or arg.startswith("--type=") for arg in process.args)
    )


def signal_process(identity: ProcessIdentity, sig: int) -> bool:
    pid, start = identity
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return False
    except PermissionError:
        logging.warning("browser_open_denied", extra={"event": "browser_open_denied", "pid": pid})
        return False
    try:
        current = read_process(pid)
        if current is None or current.start != start:
            return False
        signal.pidfd_send_signal(fd, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        logging.warning(
            "browser_signal_denied",
            extra={"event": "browser_signal_denied", "pid": pid, "signal": sig},
        )
        return False
    finally:
        os.close(fd)


@dataclass
class Browser:
    """State of a running supervised browser instance."""

    started: float
    members: set[ProcessIdentity] = field(default_factory=set)
    terminated: float | None = None


class Watchdog:
    """Watchdog that supervises and restarts browser processes."""

    def __init__(
        self,
        lifetime: float = 900,
        grace: float = 5,
        ticks: int | None = None,
        send: Callable[[ProcessIdentity, signal.Signals], object] = signal_process,
    ) -> None:
        """Initialize watchdog timing and process handling."""
        self.lifetime = lifetime
        self.grace = grace
        self.ticks = ticks or os.sysconf("SC_CLK_TCK")
        self.send = send
        self.browsers: dict[ProcessIdentity, Browser] = {}

    def step(self, processes: Mapping[int, Process], now: float) -> None:
        """Advance one watchdog tick: track new browsers and reap ended ones."""
        for process in processes.values():
            if is_test_browser(process) and process.identity not in self.browsers:
                self.browsers[process.identity] = Browser(
                    process.start / self.ticks, {process.identity}
                )
        for root, browser in list(self.browsers.items()):
            browser.members = {
                identity
                for identity in browser.members
                if identity[0] in processes and processes[identity[0]].identity == identity
            }
            while True:
                parents = {pid for pid, start in browser.members}
                additions = {p.identity for p in processes.values() if p.ppid in parents}
                additions -= browser.members
                if not additions:
                    break
                browser.members.update(additions)
            if not browser.members:
                del self.browsers[root]
                continue
            if now - browser.started < self.lifetime:
                continue
            if browser.terminated is None:
                browser.terminated = now
                sig = signal.SIGTERM
                logging.warning(
                    "browser_expired",
                    extra={
                        "event": "browser_expired",
                        "pid": root[0],
                        "age_seconds": now - browser.started,
                        "processes": len(browser.members),
                    },
                )
            elif now - browser.terminated >= self.grace:
                sig = signal.SIGKILL
            else:
                continue
            for identity in sorted(browser.members):
                self.send(identity, sig)


def positive_setting(name: str, default: str) -> float:
    value = float(os.environ.get(name, default))
    if not 0 < value < float("inf"):
        message = f"{name} must be finite and positive"
        raise ValueError(message)
    return value


def _serve_health(port: int) -> None:
    """Expose an unauthenticated process-liveness endpoint for kube probes."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/healthz", "/health/ready", "/health/live"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok\n")
            else:
                self.send_error(404)

        def log_message(self, *args):
            return

    HTTPServer(("0.0.0.0", port), _Handler).serve_forever()


def main() -> Never:
    import threading

    threading.Thread(
        target=_serve_health,
        args=(int(os.environ.get("HEALTH_PORT", "8080")),),
        daemon=True,
    ).start()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    lifetime = positive_setting("BROWSER_MAX_AGE_SECONDS", "900")
    interval = positive_setting("BROWSER_POLL_SECONDS", "15")
    grace = positive_setting("BROWSER_GRACE_SECONDS", "5")
    watchdog = Watchdog(lifetime, grace)
    logging.info("watchdog_started", extra={"event": "watchdog_started"})
    while True:
        watchdog.step(snapshot(), time.clock_gettime(time.CLOCK_BOOTTIME))
        time.sleep(
            min(interval, grace)
            if any(b.terminated is not None for b in watchdog.browsers.values())
            else interval
        )


if __name__ == "__main__":
    main()
