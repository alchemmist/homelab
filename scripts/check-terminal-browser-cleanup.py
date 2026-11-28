"""Check that the terminal browser watchdog cleans up browser artifacts."""

import argparse
import ctypes
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import types as types_module
from pathlib import Path
from typing import Protocol, cast

WRAPPER_TIMEOUT_EXIT_CODE = 124


class Proc(Protocol):
    """Attributes of the loaded watchdog's immutable process records."""

    pid: int
    ppid: int
    identity: tuple[int, int]


def load(path: str) -> types_module.ModuleType:
    """Load a Python module from the supplied path."""
    spec = importlib.util.spec_from_file_location("browser_watchdog_probe", path)
    if spec is None or spec.loader is None:
        msg = "Watchdog probe module could not be loaded"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tree(module: types_module.ModuleType, root: int) -> dict[int, Proc]:
    """Return every snapshot process at or below the given root pid."""
    snapshot = cast("dict[int, Proc]", module.snapshot())
    selected = {root}
    while True:
        children = {p.pid for p in snapshot.values() if p.ppid in selected}
        if children <= selected:
            return {pid: process for pid, process in snapshot.items() if pid in selected}
        selected.update(children)


def alive(
    module: types_module.ModuleType, identities: set[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Return which of the given identities are still present in the snapshot."""
    snapshot = cast("dict[int, Proc]", module.snapshot())
    return [
        identity
        for identity in identities
        if identity[0] in snapshot and snapshot[identity[0]].identity == identity
    ]


def _reap_children() -> None:
    """Collect any remaining adopted children without blocking the exit path."""
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
            if not pid:
                break
        except ChildProcessError:
            break


def _fixture_script(playwright_module: str, browser: str) -> str:
    """Render the reviewed Playwright fixture whose browser the watchdog must reap."""
    launch = (
        "const context = await chromium.launchPersistentContext(process.argv[2], "
        "{executablePath: " + json.dumps(browser) + ', headless: true, args: ["--no-sandbox"]});'
    )
    lines = [
        f"const {{chromium}} = require({json.dumps(playwright_module)});",
        "(async () => {",
        launch,
        "const page = await context.newPage();",
        'await page.goto("data:text/html,<canvas></canvas>");',
        "await page.evaluate(() => { const draw = () => requestAnimationFrame(draw); draw(); });",
        'console.log("BROWSER_READY");',
        'throw new Error("intentional browser cleanup fixture failure");',
        "})().catch(error => console.error(error.message));",
    ]
    return "\n".join(lines) + "\n"


def _check_wrapper_phase(
    module: types_module.ModuleType,
    script: Path,
    identities: set[tuple[int, int]],
    fixtures: list[subprocess.Popen[str] | subprocess.Popen[bytes]],
) -> None:
    """Verify the wrapper tears its whole Chromium tree down on timeout."""
    with tempfile.TemporaryDirectory(prefix="playwright_homelab_wrapper_") as profile:
        process = subprocess.Popen(
            ["homelab-browser-test", "--timeout", "8", "--", "node", str(script), profile],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        fixtures.append(process)
        deadline = time.monotonic() + 15
        recognized = False
        while process.poll() is None and time.monotonic() < deadline:
            own = tree(module, process.pid)
            identities.update(p.identity for p in own.values())
            recognized |= any(module.is_test_browser(p) for p in own.values())
            time.sleep(0.05)
        output = process.communicate(timeout=2)[0]
        if process.returncode != WRAPPER_TIMEOUT_EXIT_CODE:
            msg = "Wrapper exit code mismatch: " + repr((process.returncode, output))
            raise RuntimeError(msg)
        if not recognized:
            msg = "Real Chromium was never recognized: " + repr(output)
            raise RuntimeError(msg)
        if "BROWSER_READY" not in output:
            msg = "Browser-ready marker missing from wrapper output: " + repr(output)
            raise RuntimeError(msg)
        if alive(module, identities):
            msg = "Captured descendant identities outlived the wrapper"
            raise RuntimeError(msg)
        print(
            "wrapper: real Chromium initialized, timeout=124, "
            "all captured descendant identities removed"
        )


def _check_watchdog_phase(
    module: types_module.ModuleType,
    script: Path,
    identities: set[tuple[int, int]],
    fixtures: list[subprocess.Popen[str] | subprocess.Popen[bytes]],
    marker: subprocess.Popen[bytes],
) -> None:
    """Verify the standalone watchdog recognizes and expires only real Playwright Chromium."""
    with tempfile.TemporaryDirectory(prefix="playwright_homelab_watchdog_") as profile:
        process = subprocess.Popen(
            ["node", str(script), profile],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        fixtures.append(process)
        watchdog = module.Watchdog(lifetime=1, grace=0.2)
        deadline = time.monotonic() + 12
        browser_seen = False
        browser_identities: set[tuple[int, int]] = set()
        while time.monotonic() < deadline:
            own = tree(module, process.pid)
            identities.update(p.identity for p in own.values())
            for p in own.values():
                if module.is_test_browser(p):
                    browser_seen = True
                    browser_identities.update(q.identity for q in tree(module, p.pid).values())
            snapshot = module.snapshot()
            owned_snapshot = {pid: p for pid, p in snapshot.items() if p.identity in identities}
            boottime = cast("int", getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC))
            watchdog.step(owned_snapshot, time.clock_gettime(boottime))
            if browser_seen and not alive(module, browser_identities):
                break
            time.sleep(0.05)
        if not browser_seen:
            msg = "real Chromium not recognized by watchdog"
            raise RuntimeError(msg)
        if alive(module, browser_identities):
            msg = "Browser identities outlived the watchdog grace window"
            raise RuntimeError(msg)
        if marker.poll() is not None:
            msg = "unrelated marker process was terminated"
            raise RuntimeError(msg)
        print(
            "watchdog: actual Playwright Chromium recognized and expired; "
            "unrelated process survived"
        )


def main() -> None:
    """Run the command-line entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchdog", required=True)
    parser.add_argument(
        "--playwright-module",
        default="/home/user/.npm/_npx/e41f203b7505f1fb/node_modules/playwright-core",
    )
    parser.add_argument(
        "--browser",
        default="/home/user/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome",
    )
    args = parser.parse_args()
    module = load(args.watchdog)
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        msg = "Could not enable fixture process adoption"
        raise RuntimeError(msg)
    with tempfile.TemporaryDirectory(prefix="playwright_homelab_probe_") as directory:
        script = Path(directory) / "fixture.js"
        script.write_text(_fixture_script(args.playwright_module, args.browser))
        identities: set[tuple[int, int]] = set()
        fixtures: list[subprocess.Popen[str] | subprocess.Popen[bytes]] = []
        marker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            _check_wrapper_phase(module, script, identities, fixtures)
            _check_watchdog_phase(module, script, identities, fixtures, marker)
        finally:
            identities.update(
                p.identity for p in tree(module, os.getpid()).values() if p.pid != os.getpid()
            )
            for identity in identities:
                module.signal_process(identity, signal.SIGKILL)
            for fixture in [*fixtures, marker]:
                fixture.wait(timeout=5)
        _reap_children()


if __name__ == "__main__":
    main()
