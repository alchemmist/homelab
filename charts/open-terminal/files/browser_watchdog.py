import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    start: int
    executable: str
    args: tuple[str, ...]

    @property
    def identity(self):
        return self.pid, self.start


def read_process(pid, proc=Path('/proc')):
    try:
        directory = proc / str(pid)
        stat = (directory / 'stat').read_text()
        fields = stat[stat.rindex(')') + 2:].split()
        args = tuple(part.decode(errors='replace') for part in (directory / 'cmdline').read_bytes().split(b'\0') if part)
        executable = Path(os.readlink(directory / 'exe')).name
        return Process(pid, int(fields[1]), int(fields[19]), executable, args)
    except (OSError, ValueError, IndexError):
        return None


def snapshot(proc=Path('/proc')):
    result = {}
    for directory in proc.iterdir():
        if directory.name.isdigit():
            process = read_process(int(directory.name), proc)
            if process is not None:
                result[process.pid] = process
    return result


def is_test_browser(process):
    return (
        process.executable in {'chrome', 'chromium', 'headless_shell', 'chrome-headless-shell'}
        and any(arg == '--headless' or arg.startswith('--headless=') for arg in process.args)
        and '--remote-debugging-pipe' in process.args
        and any(arg.startswith('--user-data-dir=/tmp/playwright_') for arg in process.args)
        and not any(arg == '--type' or arg.startswith('--type=') for arg in process.args)
    )


def signal_process(identity, sig):
    pid, start = identity
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return False
    except PermissionError:
        logging.warning('Permission denied opening browser process pid=%s', pid)
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
        logging.warning('Permission denied signaling browser process pid=%s signal=%s', pid, sig)
        return False
    finally:
        os.close(fd)


@dataclass
class Browser:
    started: float
    members: set = field(default_factory=set)
    terminated: float | None = None


class Watchdog:
    def __init__(self, lifetime=900, grace=5, ticks=None, send=signal_process):
        self.lifetime = lifetime
        self.grace = grace
        self.ticks = ticks or os.sysconf('SC_CLK_TCK')
        self.send = send
        self.browsers = {}

    def step(self, processes, now):
        for process in processes.values():
            if is_test_browser(process) and process.identity not in self.browsers:
                self.browsers[process.identity] = Browser(process.start / self.ticks, {process.identity})
        for root, browser in list(self.browsers.items()):
            browser.members = {
                identity for identity in browser.members
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
                logging.warning('Expiring Playwright browser pid=%s age=%.1fs processes=%s', root[0], now - browser.started, len(browser.members))
            elif now - browser.terminated >= self.grace:
                sig = signal.SIGKILL
            else:
                continue
            for identity in sorted(browser.members):
                self.send(identity, sig)


def positive_setting(name, default):
    value = float(os.environ.get(name, default))
    if not 0 < value < float('inf'):
        raise ValueError(f'{name} must be finite and positive')
    return value


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    lifetime = positive_setting('BROWSER_MAX_AGE_SECONDS', '900')
    interval = positive_setting('BROWSER_POLL_SECONDS', '15')
    grace = positive_setting('BROWSER_GRACE_SECONDS', '5')
    watchdog = Watchdog(lifetime, grace)
    logging.info('Browser watchdog started max_age=%ss poll=%ss grace=%ss', lifetime, interval, grace)
    while True:
        watchdog.step(snapshot(), time.clock_gettime(time.CLOCK_BOOTTIME))
        time.sleep(min(interval, grace) if any(b.terminated is not None for b in watchdog.browsers.values()) else interval)


if __name__ == '__main__':
    main()
