"""Names for the staged native VPN refresh play do not change its actions."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/vpn-native-image-refresh.yml"
PLAY_NAME = "Refresh stale NL standby image without restarting the working VPN"
OLD_IMAGE = (
    "ghcr.io/mhsanaei/3x-ui@sha256:6c7e73c5bc4b6d7d70866616f78d6c9866b4904defad3077c1e2b5c1c89c2ec1"
)
TASK_NAMES = (
    "Refuse an unknown phase or an unconfirmed promotion",
    "Read the active failover latch",
    "Refuse promotion while the active failover latch exists",
    "Read the installed primary image pin",
    "Require the reviewed stale image pin before staging",
    "Create the private recovery directory",
    "Copy only the reviewed runtime helpers into recovery",
    "Stage the isolated candidate when the phase is stage",
    "Read the candidate directory before staging",
    "Refuse to replay an existing candidate",
    "Create the isolated candidate directory",
    "Copy only the already-cached pinned image into an isolated candidate",
    "Validate candidate on copied DB/certs in isolated network namespace",
    "Record the isolated smoke acceptance receipt",
    "Promote only after an explicit confirmed phase",
    "Copy the locked promotion helper into recovery",
    "Atomic locked directory exchange; no unit or workload restart",
)
COMMANDS = (
    "cat {{ root }}/primary/.homelab-image",
    "python3 {{ recovery }}/prepare_runtime.py {{ image }} {{ candidate }}/primary",
    "python3 {{ recovery }}/smoke_test.py --runtime-root {{ candidate }}",
    (
        "python3 {{ recovery }}/promote.py --candidate {{ candidate }} "
        "--old-image {{ old_image }} --new-image {{ image }}"
    ),
)
PRIVATE_MODE = "0700"
RECEIPT_MODE = "0600"


def _mapping(value: object) -> dict[str, object]:
    """Return a string-keyed mapping or reject a non-mapping."""
    if not isinstance(value, dict):
        message = "expected a YAML mapping"
        raise TypeError(message)
    mapped: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            message = "expected string mapping keys"
            raise TypeError(message)
        mapped[key] = item
    return mapped


def _sequence(value: object) -> list[object]:
    """Return a YAML sequence or reject a non-sequence."""
    if not isinstance(value, list):
        message = "expected a YAML sequence"
        raise TypeError(message)
    return list(value)


def _task_names(tasks: object) -> list[str]:
    """Collect task names, including tasks nested in blocks."""
    names: list[str] = []
    for item in _sequence(tasks):
        task = _mapping(item)
        name = task.get("name")
        if not isinstance(name, str):
            message = "every task needs a string name"
            raise TypeError(message)
        names.append(name)
        for section in ("block", "rescue", "always"):
            nested = task.get(section)
            if nested is not None:
                names.extend(_task_names(nested))
    return names


def _commands(tasks: object) -> list[str]:
    """Collect command module arguments without executing them."""
    commands: list[str] = []
    for item in _sequence(tasks):
        task = _mapping(item)
        command = task.get("ansible.builtin.command")
        if isinstance(command, str):
            commands.append(command)
        for section in ("block", "rescue", "always"):
            nested = task.get(section)
            if nested is not None:
                commands.extend(_commands(nested))
    return commands


def test_vpn_refresh_tasks_are_named_without_changing_actions() -> None:
    """Require unique task names and the original stage and promote actions."""
    source = PLAYBOOK.read_text()
    loaded = yaml.safe_load(source)
    play = _mapping(_sequence(loaded)[0])
    names = _task_names(play.get("tasks"))
    assert play.get("name") == PLAY_NAME
    assert play.get("hosts") == "socrat-2"
    assert play.get("become") is True
    assert play.get("gather_facts") is False
    assert play.get("any_errors_fatal") is True
    variables = _mapping(play.get("vars"))
    assert variables.get("old_image") == OLD_IMAGE
    assert names == list(TASK_NAMES)
    assert len(names) == len(set(names))
    assert _commands(play.get("tasks")) == list(COMMANDS)
    assert source.count(f"mode: '{PRIVATE_MODE}'") == len(
        ("recovery", "helpers", "candidate", "promote"),
    )
    assert source.count(f"mode: '{RECEIPT_MODE}'") == 1
    assert 'default("stage")' in source
    assert "vpn_native_refresh_confirmed | default(false)" in source
    assert "state: restarted" not in source
    assert "state: stopped" not in source
