"""Exercise the actual Ansible parser/safety rules without executing a play."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "task,rule",
    [
        ({"ansible.builtin.shell": "false | true"}, "risky-shell-pipe"),
        ({"unavailable.collection.fake_module": {}}, "syntax-check"),
    ],
)
def test_real_linter_rejects_unsafe_or_unresolved_tasks(tmp_path, task, rule) -> None:
    """Reject unsafe or unresolved tasks with offline ansible-lint."""
    import yaml

    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Parser fixture",
                    "hosts": "localhost",
                    "gather_facts": False,
                    "tasks": [task],
                }
            ]
        )
    )
    executable = shutil.which("ansible-lint")
    assert executable is not None
    result = subprocess.run(
        [
            executable,
            "--offline",
            "--config-file",
            str(ROOT / "quality/ansible-lint.yaml"),
            "--project-dir",
            str(tmp_path),
            "--format",
            "sarif",
            str(playbook),
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 2
    rules = {
        f["ruleId"] for run in json.loads(result.stdout)["runs"] for f in run.get("results", [])
    }
    assert any(r.startswith(rule) for r in rules)


@pytest.mark.parametrize("prop,rc", [("LoadState", 0), (None, 3), (None, 4), (None, 1)])
def test_unit_probe_preserves_systemctl_status(prop, rc, monkeypatch):
    """Keep the real active-state exit status for the caller's failure policy."""
    import runpy
    from unittest.mock import Mock

    from ansible.module_utils import basic

    module = Mock(check_mode=False, params={"units": ["test.service"], "property": prop})
    module.run_command.return_value = (rc, "loaded\n", "message\n")
    module.exit_json.side_effect = SystemExit(0)
    module.fail_json.side_effect = SystemExit(1)
    monkeypatch.setattr(basic, "AnsibleModule", lambda **_: module)
    with pytest.raises(SystemExit) as outcome:
        runpy.run_path(
            str(ROOT / "ansible/playbooks/library/homelab_systemd_probe.py"),
            run_name="__main__",
        )
    assert outcome.value.code == int(rc != 0)
    operation = ["show", "--property", prop, "--value"] if prop else ["is-active"]
    module.run_command.assert_called_once_with(["systemctl", *operation, "--", "test.service"])
    returned = (module.fail_json if rc else module.exit_json).call_args.kwargs
    assert returned["rc"] == rc
    assert returned["stdout"] == "loaded"
    assert returned["stderr"] == "message"
    assert returned["changed"] is False
