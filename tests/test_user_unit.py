"""Exercise the synchronous unit boundary with Ansible, local files and a fake manager."""

import grp
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROLE = Path(__file__).resolve().parents[1] / "ansible/roles/desktop_environment"
UNIT = "caffeine-lid-inhibit.service"


@pytest.fixture
def desktop(tmp_path):
    # Execute the actual role task with a synthetic home; not a repository play or inventory.
    (task,) = yaml.safe_load((ROLE / "tasks/caffeine.yml").read_text())
    user = pwd.getpwuid(os.geteuid()).pw_name
    assert task["become"]
    assert task["become_user"] == "{{ homelab_user }}"
    assert task["homelab_user_unit"]["group"] == "{{ homelab_user }}"
    try:
        expected_gid = grp.getgrnam(user).gr_gid
    except KeyError:
        # The macOS development account has no same-name group. Keep the real
        # role expression on Linux CI and only adapt this absent fixture group.
        expected_gid = os.getegid()
        task["homelab_user_unit"]["group"] = grp.getgrgid(expected_gid).gr_name
    (tmp_path / "files").symlink_to(ROLE / "files")
    dest = tmp_path / ".config/systemd/user" / UNIT
    dest.parent.mkdir(parents=True)
    events = tmp_path / "events"
    fake = tmp_path / "systemctl"
    fake.write_text(
        "#!/bin/sh\nset -eu\n"
        'test "$*" = "--user daemon-reload"\n'
        'test "$XDG_RUNTIME_DIR" = "/run/user/$(id -u)"\n'
        'test "$DBUS_SESSION_BUS_ADDRESS" = "unix:path=$XDG_RUNTIME_DIR/bus"\n'
        'cmp "$DEST" "$SOURCE"\n'
        'echo reload >> "$EVENTS"\n'
        'test ! -f "$FAIL"\n'
    )
    fake.chmod(0o755)
    handler = {
        "name": "Terminal restart",
        "ansible.builtin.shell": 'echo terminal >> "$EVENTS"',
    }
    play = {
        "hosts": "localhost",
        "gather_facts": False,
        "vars": {
            "ansible_user": user,
            "homelab_user": user,
            "homelab_user_home": str(tmp_path),
            "ansible_python_interpreter": sys.executable,
        },
        "environment": {
            "PATH": f"{tmp_path}:{os.defpath}",
            "DEST": str(dest),
            "SOURCE": str(ROLE / "files" / UNIT),
            "EVENTS": str(events),
            "FAIL": str(tmp_path / "fail"),
            "DBUS_SESSION_BUS_ADDRESS": "invalid:wrong-inherited-bus",
        },
        "tasks": [
            {
                "ansible.builtin.debug": {"msg": "queue"},
                "changed_when": True,
                "notify": handler["name"],
            },
            {**task, "register": "unit"},
            {"ansible.builtin.assert": {"that": "unit.changed == expected_change"}},
            {"ansible.builtin.shell": 'echo continue >> "$EVENTS"'},
        ],
        "handlers": [handler],
    }
    cfg = tmp_path / "ansible.cfg"
    cfg.write_text("[defaults]\n")
    path = tmp_path / "play.yml"
    path.write_text(yaml.safe_dump([play], sort_keys=False))

    def run(*, changed=True, check=False, fails=False):
        events.unlink(missing_ok=True)
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                "localhost,",
                "-c",
                "local",
                str(path),
                "-e",
                json.dumps({"expected_change": changed}),
                *(["--check"] if check else []),
            ],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=60,
            env={
                **os.environ,
                "ANSIBLE_CONFIG": str(cfg),
                "ANSIBLE_LIBRARY": str(ROLE / "library"),
            },
        )
        assert result.returncode == (2 if fails else 0), result.stdout + result.stderr
        if dest.is_file() and not check and not fails:
            assert (dest.stat().st_uid, dest.stat().st_gid) == (
                os.geteuid(),
                expected_gid,
            )
        return events.read_text().splitlines() if events.exists() else []

    return dest, run


def test_user_unit_converges_before_continuation_and_leaves_handlers_queued(desktop) -> None:
    dest, run = desktop
    assert run(check=True) == []
    assert not list(dest.parent.iterdir())
    assert run() == ["reload", "continue", "terminal"]
    assert dest.stat().st_mode & 0o777 == 0o644
    assert run(changed=False) == ["continue", "terminal"]
    assert run(check=True, changed=False) == []
    dest.chmod(0o600)
    assert run(check=True) == []
    assert dest.stat().st_mode & 0o777 == 0o600
    assert run() == ["reload", "continue", "terminal"]
    assert dest.stat().st_mode & 0o777 == 0o644


def test_failed_reload_blocks_later_tasks_and_retries_with_unchanged_bytes(
    desktop, tmp_path
) -> None:
    dest, run = desktop
    target = tmp_path / "overridden-unit"
    target.write_text("old contents")
    dest.symlink_to(target)
    fail = tmp_path / "fail"
    fail.touch()
    assert run(fails=True) == ["reload"]
    assert dest.is_symlink()
    assert target.read_bytes() == (ROLE / "files" / UNIT).read_bytes()
    (backup,) = tmp_path.glob("overridden-unit.*~")
    assert backup.read_text() == "old contents"
    fail.unlink()
    pending = dest.with_name(f".{dest.name}.reload-pending")
    assert pending.is_dir()
    assert run(check=True, changed=True) == []
    assert pending.is_dir()
    assert run() == ["reload", "continue", "terminal"]
    assert run(changed=False) == ["continue", "terminal"]


def test_install_failure_never_reloads_or_runs_later_work(desktop) -> None:
    dest, run = desktop
    dest.mkdir()
    assert run(fails=True) == []
