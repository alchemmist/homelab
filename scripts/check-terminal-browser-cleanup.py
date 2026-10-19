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
from pathlib import Path


def load(path):
    spec = importlib.util.spec_from_file_location('browser_watchdog_probe', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tree(module, root):
    snapshot = module.snapshot()
    selected = {root}
    while True:
        children = {p.pid for p in snapshot.values() if p.ppid in selected}
        if children <= selected:
            return {pid: process for pid, process in snapshot.items() if pid in selected}
        selected.update(children)


def alive(module, identities):
    snapshot = module.snapshot()
    return [identity for identity in identities if identity[0] in snapshot and snapshot[identity[0]].identity == identity]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watchdog', required=True)
    parser.add_argument('--playwright-module', default='/home/user/.npm/_npx/e41f203b7505f1fb/node_modules/playwright-core')
    parser.add_argument('--browser', default='/home/user/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome')
    args = parser.parse_args()
    module = load(args.watchdog)
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError('Could not enable fixture process adoption')
    with tempfile.TemporaryDirectory(prefix='playwright_homelab_probe_') as directory:
        script = Path(directory) / 'fixture.js'
        script.write_text(
            f'const {{chromium}} = require({json.dumps(args.playwright_module)});\n'
            '(async () => {\n'
            f'const context = await chromium.launchPersistentContext(process.argv[2], {{executablePath: {json.dumps(args.browser)}, headless: true, args: ["--no-sandbox"]}});\n'
            'const page = await context.newPage();\n'
            'await page.goto("data:text/html,<canvas></canvas>");\n'
            'await page.evaluate(() => { const draw = () => requestAnimationFrame(draw); draw(); });\n'
            'console.log("BROWSER_READY");\n'
            'throw new Error("intentional browser cleanup fixture failure");\n'
            '})().catch(error => console.error(error.message));\n'
        )
        identities = set()
        fixtures = []
        marker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            with tempfile.TemporaryDirectory(prefix='playwright_homelab_wrapper_') as profile:
                process = subprocess.Popen(['homelab-browser-test', '--timeout', '8', '--', 'node', str(script), profile], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                fixtures.append(process)
                deadline = time.monotonic() + 15
                recognized = False
                while process.poll() is None and time.monotonic() < deadline:
                    own = tree(module, process.pid)
                    identities.update(p.identity for p in own.values())
                    recognized |= any(module.is_test_browser(p) for p in own.values())
                    time.sleep(.05)
                output = process.communicate(timeout=2)[0]
                assert process.returncode == 124, (process.returncode, output)
                assert recognized and 'BROWSER_READY' in output, output
                assert not alive(module, identities), alive(module, identities)
                print('wrapper: real Chromium initialized, timeout=124, all captured descendant identities removed')
            with tempfile.TemporaryDirectory(prefix='playwright_homelab_watchdog_') as profile:
                process = subprocess.Popen(['node', str(script), profile], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                fixtures.append(process)
                watchdog = module.Watchdog(lifetime=1, grace=.2)
                deadline = time.monotonic() + 12
                browser_seen = False
                browser_identities = set()
                while time.monotonic() < deadline:
                    own = tree(module, process.pid)
                    identities.update(p.identity for p in own.values())
                    for p in own.values():
                        if module.is_test_browser(p):
                            browser_seen = True
                            browser_identities.update(q.identity for q in tree(module, p.pid).values())
                    snapshot = module.snapshot()
                    owned_snapshot = {pid: p for pid, p in snapshot.items() if p.identity in identities}
                    watchdog.step(owned_snapshot, time.clock_gettime(time.CLOCK_BOOTTIME))
                    if browser_seen and not alive(module, browser_identities):
                        break
                    time.sleep(.05)
                assert browser_seen, 'real Chromium not recognized by watchdog'
                assert not alive(module, browser_identities), alive(module, browser_identities)
                assert marker.poll() is None, 'unrelated marker process was terminated'
                print('watchdog: actual Playwright Chromium recognized and expired; unrelated process survived')
        finally:
            identities.update(p.identity for p in tree(module, os.getpid()).values() if p.pid != os.getpid())
            for identity in identities:
                module.signal_process(identity, signal.SIGKILL)
            for process in fixtures + [marker]:
                process.wait(timeout=5)
            while True:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                    if not pid:
                        break
                except ChildProcessError:
                    break


if __name__ == '__main__':
    main()
