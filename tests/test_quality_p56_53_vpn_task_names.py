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


def _tasks(items: object) -> list[dict[str, object]]:
    """Collect tasks in play order, including tasks nested in blocks."""
    tasks = []
    for item in _sequence(items):
        task = _mapping(item)
        tasks.append(task)
        for section in ("block", "rescue", "always"):
            nested = task.get(section)
            if nested is not None:
                tasks.extend(_tasks(nested))
    return tasks


def test_vpn_refresh_tasks_are_named_without_changing_actions() -> None:
    """Require unique task names and the original stage and promote actions."""
    loaded = yaml.safe_load(PLAYBOOK.read_text())
    play = _mapping(_sequence(loaded)[0])
    tasks = _tasks(play["tasks"])
    names = [task["name"] for task in tasks]
    assert play.get("name") == PLAY_NAME
    assert play.get("hosts") == "socrat-2"
    assert play.get("become") is True
    assert play.get("gather_facts") is False
    assert play.get("any_errors_fatal") is True
    variables = _mapping(play.get("vars"))
    assert variables.get("old_image") == OLD_IMAGE
    assert names == list(TASK_NAMES)
    assert len(names) == len(set(names))
    assert [
        task["ansible.builtin.command"] for task in tasks if "ansible.builtin.command" in task
    ] == list(COMMANDS)
    modes = [
        (module, args.get("path", args.get("dest")), args["mode"])
        for task in tasks
        for module, args in task.items()
        if isinstance(args, dict) and "mode" in args
    ]
    assert modes == [
        ("ansible.builtin.file", "{{ recovery }}", PRIVATE_MODE),
        ("ansible.builtin.copy", "{{ recovery }}/{{ item }}", PRIVATE_MODE),
        ("ansible.builtin.file", "{{ candidate }}", PRIVATE_MODE),
        ("ansible.builtin.copy", "{{ recovery }}/stage-accepted.json", RECEIPT_MODE),
        ("ansible.builtin.copy", "{{ recovery }}/promote.py", PRIVATE_MODE),
    ]
    assert variables["phase"] == '{{ vpn_native_refresh_phase | default("stage") }}'
    assert _mapping(tasks[0]["ansible.builtin.assert"])["that"] == [
        "phase in ['stage','promote']",
        "phase != 'promote' or (vpn_native_refresh_confirmed | default(false) | bool)",
    ]
    for task in tasks:
        for args in task.values():
            if isinstance(args, dict):
                assert args.get("state") not in ("restarted", "stopped")
