"""Names for the Moscow CPU override play do not change its actions."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/otel-socrat4-cpu-tuning.yml"
PLAY_NAME = "Tune telemetry parallelism on the one-vCPU Moscow gateway"
SERVICE_NAME = "homelab-otel-agent.service"
PROTECTED_SHA256 = (
    "9d4e959e94812f664c742da447a7a07e29ba629e95d98ff0321cbfee48909f45",
    "d246fafdf1b0f08a6ddb254bb8a89e5572f11c4c3ce33e98ef4dd48a31d781f9",
    "7b580cb2bc73bc3cec47c0994ca5b8bb10bc2da74844f8d5350dd3bf05adc2ab",
)
TASK_NAMES = (
    "Require the Moscow gateway host",
    "Read the online processor count",
    "Require exactly one online processor",
    "Hash the protected telemetry files before the override",
    "Stop when a protected telemetry file has drifted",
    "Hash any staged processor override",
    "Read loaded systemd drop-in paths",
    "Stop when an override exists or is already loaded",
    "Require a healthy agent before touching the service",
    "Create the telemetry agent drop-in directory",
    "Install only the reviewed one-line environment override",
    "Activate only the telemetry-agent override",
    "Reload and restart only the telemetry agent",
    "Require the telemetry agent health endpoint after restart",
    "Remove only the new override on failed acceptance",
    "Reload and restart the telemetry agent after rollback",
    "Fail closed after restoring the previous telemetry configuration",
    "Hash the protected telemetry files after the override",
    "Require the protected telemetry files to be unchanged",
)
COMMANDS = (
    "getconf _NPROCESSORS_ONLN",
    "systemctl show homelab-otel-agent.service -p DropInPaths --value",
)


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


def _service_restarts(tasks: object) -> list[str]:
    """Collect systemd service names that this play restarts."""
    services: list[str] = []
    for item in _sequence(tasks):
        task = _mapping(item)
        service = task.get("ansible.builtin.systemd_service")
        if isinstance(service, dict):
            rendered = _mapping(service)
            name = rendered.get("name")
            if rendered.get("state") == "restarted" and isinstance(name, str):
                services.append(name)
        for section in ("block", "rescue", "always"):
            nested = task.get(section)
            if nested is not None:
                services.extend(_service_restarts(nested))
    return services


def test_otel_cpu_tasks_are_named_without_changing_actions() -> None:
    """Require unique task names and the original one-service rollback."""
    source = PLAYBOOK.read_text()
    play = _mapping(_sequence(yaml.safe_load(source))[0])
    variables = _mapping(play.get("vars"))
    protected = _sequence(variables.get("protected_files"))
    digests = tuple(_mapping(item).get("sha256") for item in protected)
    names = _task_names(play.get("tasks"))
    assert play.get("name") == PLAY_NAME
    assert play.get("hosts") == "socrat-4"
    assert play.get("any_errors_fatal") is True
    assert digests == PROTECTED_SHA256
    assert names == list(TASK_NAMES)
    assert len(names) == len(set(names))
    assert _commands(play.get("tasks")) == list(COMMANDS)
    assert _service_restarts(play.get("tasks")) == [SERVICE_NAME, SERVICE_NAME]
    assert "not old_override.stat.exists" in source
    assert "postimages" in source
