"""Tests for the Sway desktop session guard."""

import contextlib
import importlib.util
import json
import os
import struct
import unittest
from pathlib import Path
from types import ModuleType


def load(name, path) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


BASE_PROCESS_PID = 4000
LAUNCH_SPAWN_COUNT = 3

ROOT = Path(__file__).parents[1] / "ansible/roles/debian_laptop/files/sway"
app = load("homelab_sway_app", ROOT / "homelab-sway-app")
graphics = load("homelab_graphics", ROOT / "homelab-graphics")


class LaunchGuard(unittest.TestCase):
    """Exercise the sway desktop launch guard behaviour."""

    def setUp(self) -> None:
        self.runtime = Path(self.id().replace(".", "_"))
        self.runtime.mkdir(exist_ok=True)
        app.RUNTIME = self.runtime
        app.pid_alive = lambda pid: False
        app.pids_named = lambda executable: []
        self.spawned: list[str] = []

    def spawn(self, command) -> object:
        self.spawned.append(command)
        return type("Process", (), {"pid": BASE_PROCESS_PID + len(self.spawned)})()

    def test_second_click_while_the_first_process_lives_does_not_spawn(self) -> None:
        app.open_shortcut("max", now=1000, spawn=self.spawn)
        app.pid_alive = lambda pid: pid == BASE_PROCESS_PID + 1
        app.open_shortcut("max", now=1005, spawn=self.spawn)
        assert len(self.spawned) == 1

    def test_click_during_cooldown_does_not_spawn_even_if_the_process_exited(
        self,
    ) -> None:
        app.open_shortcut("browser", now=1000, spawn=self.spawn)
        app.pid_alive = lambda pid: False
        app.open_shortcut("browser", now=1009, spawn=self.spawn)
        assert len(self.spawned) == 1

    def test_running_firefox_is_reused_for_another_shortcut(self) -> None:
        app.pids_named = lambda executable: [77] if executable == "firefox-esr" else []
        app.open_shortcut("gmail", now=2000, spawn=self.spawn)
        assert self.spawned[0][:2] == ["/usr/bin/firefox-esr", "--new-window"]
        assert self.spawned[0][-1].endswith("mail.google.com/")

    def test_files_do_not_open_twice_while_thunar_is_running(self) -> None:
        app.pids_named = lambda executable: [9] if executable == "thunar" else []
        assert app.open_shortcut("files", now=3000, spawn=self.spawn) is None
        assert self.spawned == []

    def test_stamp_records_the_spawned_pid(self) -> None:
        app.open_shortcut("telegram", now=4000, spawn=self.spawn)
        stamp = json.loads((self.runtime / "telegram.json").read_text())
        assert stamp["pids"] == [4001]


class GraphicsWake(unittest.TestCase):
    """Check the graphics wake guard's file-based state handling."""

    def setUp(self) -> None:
        self.directory = Path(self.id().replace(".", "_"))
        self.directory.mkdir(exist_ok=True)
        graphics.runtime_dir = lambda: self.directory
        os.environ.pop("SWAYSOCK", None)

    def test_space_event_is_recognized_only_on_press(self) -> None:
        press = struct.pack("llHHi", 1, 0, graphics.EV_KEY, graphics.KEY_SPACE, 1)
        release = struct.pack("llHHi", 1, 0, graphics.EV_KEY, graphics.KEY_SPACE, 0)
        letter = struct.pack("llHHi", 1, 0, graphics.EV_KEY, 30, 1)
        assert graphics.space_pressed(press)
        assert not graphics.space_pressed(release)
        assert not graphics.space_pressed(letter)

    def test_space_brings_graphics_up_once(self) -> None:
        calls = []
        spawned = []
        graphics.command_running = lambda command: False
        graphics.graphics_up(
            blank=lambda *args: calls.append(args),
            spawn=spawned.append,
        )
        graphics.graphics_up(
            blank=lambda *args: calls.append(args),
            spawn=spawned.append,
        )
        assert calls[0] == ("output", "*", "dpms", "on")
        assert [item[0] for item in spawned] == [
            "/usr/bin/waybar",
            "/usr/local/bin/homelab-sway-shortcuts",
            "/usr/bin/mako",
        ]
        assert graphics.graphics_active()
        assert len(spawned) == LAUNCH_SPAWN_COUNT

    def test_watch_ignores_space_after_graphics_are_up(self) -> None:
        graphics.write_state(True)
        payload = struct.pack("llHHi", 1, 0, graphics.EV_KEY, graphics.KEY_SPACE, 1)

        class Device:
            def read(self, _size) -> bytes:
                return payload

            def close(self) -> None:
                pass

        spawned = []
        graphics.graphics_up = lambda **_kwargs: spawned.append("up")
        graphics.graphics_down = lambda: None

        def stop_after_one_read() -> None:
            watch_once(Device())

        def watch_once(device) -> None:
            original = graphics.watch

            def open_devices() -> list[object]:
                return [device]

            readable: list[object] = []

            def fake_select(
                devices, _write, _error, _timeout
            ) -> tuple[list[object], list[object], list[object]]:
                if readable:
                    raise SystemExit
                readable.append(devices[0])
                return readable, [], []

            graphics.select.select = fake_select
            with contextlib.suppress(SystemExit):
                original(open_devices=open_devices, sleep=lambda _seconds: None)

        stop_after_one_read()
        assert spawned == []


if __name__ == "__main__":
    unittest.main()
