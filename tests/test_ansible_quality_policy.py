"""Exercise the actual Ansible parser/safety rules without executing a play."""

import json
from pathlib import Path
import subprocess
import shutil

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
