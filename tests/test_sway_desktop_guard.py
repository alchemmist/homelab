import importlib.util
import json
import os
import struct
import unittest
from pathlib import Path


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ROOT = Path(__file__).parents[1] / "ansible/roles/debian_laptop/files/sway"
app = load("homelab_sway_app", ROOT / "homelab-sway-app")
graphics = load("homelab_graphics", ROOT / "homelab-graphics")


class LaunchGuard(unittest.TestCase):
    def setUp(self):
        self.runtime = Path(self.id().replace(".", "_"))
        self.runtime.mkdir(exist_ok=True)
        app.RUNTIME = self.runtime
        app.pid_alive = lambda pid: False
        app.pids_named = lambda executable: []
        self.spawned = []

    def spawn(self, command):
        self.spawned.append(command)
        return type("Process", (), {"pid": 4000 + len(self.spawned)})()

    def test_second_click_while_the_first_process_lives_does_not_spawn(self):
        app.open_shortcut("max", now=1000, spawn=self.spawn)
        app.pid_alive = lambda pid: pid == 4001
        app.open_shortcut("max", now=1005, spawn=self.spawn)
        self.assertEqual(len(self.spawned), 1)

    def test_click_during_cooldown_does_not_spawn_even_if_the_process_exited(self):
        app.open_shortcut("browser", now=1000, spawn=self.spawn)
        app.pid_alive = lambda pid: False
        app.open_shortcut("browser", now=1009, spawn=self.spawn)
        self.assertEqual(len(self.spawned), 1)

    def test_running_firefox_is_reused_for_another_shortcut(self):
        app.pids_named = lambda executable: [77] if executable == "firefox-esr" else []
        app.open_shortcut("gmail", now=2000, spawn=self.spawn)
        self.assertEqual(self.spawned[0][:2], ["/usr/bin/firefox-esr", "--new-window"])
        self.assertTrue(self.spawned[0][-1].endswith("mail.google.com/"))

    def test_files_do_not_open_twice_while_thunar_is_running(self):
        app.pids_named = lambda executable: [9] if executable == "thunar" else []
        self.assertIsNone(app.open_shortcut("files", now=3000, spawn=self.spawn))
        self.assertEqual(self.spawned, [])

    def test_stamp_records_the_spawned_pid(self):
        app.open_shortcut("telegram", now=4000, spawn=self.spawn)
        stamp = json.loads((self.runtime / "telegram.json").read_text())
        self.assertEqual(stamp["pids"], [4001])


class GraphicsWake(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.id().replace(".", "_"))
        self.directory.mkdir(exist_ok=True)
        graphics.runtime_dir = lambda: self.directory
        os.environ.pop("SWAYSOCK", None)

    def test_space_event_is_recognized_only_on_press(self):
        press = struct.pack("llHHi", 1, 0, graphics.EV_KEY, graphics.KEY_SPACE, 1)
        release = struct.pack("llHHi", 1, 0, graphics.EV_KEY, graphics.KEY_SPACE, 0)
        letter = struct.pack("llHHi", 1, 0, graphics.EV_KEY, 30, 1)
        self.assertTrue(graphics.space_pressed(press))
        self.assertFalse(graphics.space_pressed(release))
        self.assertFalse(graphics.space_pressed(letter))

    def test_space_brings_graphics_up_once(self):
        calls = []
        spawned = []
        graphics.command_running = lambda command: False
        graphics.graphics_up(blank=lambda *args: calls.append(args), spawn=lambda command: spawned.append(command))
        graphics.graphics_up(blank=lambda *args: calls.append(args), spawn=lambda command: spawned.append(command))
        self.assertEqual(calls[0], ("output", "*", "dpms", "on"))
        self.assertEqual([item[0] for item in spawned], ["/usr/bin/waybar", "/usr/local/bin/homelab-sway-shortcuts", "/usr/bin/mako"])
        self.assertTrue(graphics.graphics_active())
        self.assertEqual(len(spawned), 3)

    def test_watch_ignores_space_after_graphics_are_up(self):
        graphics.write_state(True)
        payload = struct.pack("llHHi", 1, 0, graphics.EV_KEY, graphics.KEY_SPACE, 1)

        class Device:
            def read(self, _size):
                return payload

            def close(self):
                pass

        spawned = []
        graphics.graphics_up = lambda **_kwargs: spawned.append("up")
        graphics.graphics_down = lambda: None

        def stop_after_one_read():
            watch_once(Device())

        def watch_once(device):
            original = graphics.watch

            def open_devices():
                return [device]

            readable = []

            def fake_select(devices, _write, _error, _timeout):
                if readable:
                    raise SystemExit
                readable.append(devices[0])
                return readable, [], []

            graphics.select.select = fake_select
            try:
                original(open_devices=open_devices, sleep=lambda _seconds: None)
            except SystemExit:
                pass

        stop_after_one_read()
        self.assertEqual(spawned, [])


if __name__ == "__main__":
    unittest.main()
