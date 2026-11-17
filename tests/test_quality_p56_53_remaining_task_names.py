"""Remaining lane playbooks keep their actions after every task is named."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MOSCOW = ROOT / "ansible/playbooks/moscow-watchdog-repair.yml"
TV = ROOT / "ansible/playbooks/tv-public-dashboard.yml"
MOSCOW_TASKS = 22
TV_TASKS = 24


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
        if not isinstance(name, str) or not name[:1].isupper():
            message = "every task needs an uppercase name"
            raise TypeError(message)
        names.append(name)
        for section in ("block", "rescue", "always"):
            nested = task.get(section)
            if nested is not None:
                names.extend(_task_names(nested))
    return names


def test_moscow_repair_names_keep_phase_and_voter_contract() -> None:
    """Name every Moscow repair task without changing its phase contract."""
    source = MOSCOW.read_text()
    play = _mapping(_sequence(yaml.safe_load(source))[0])
    names = _task_names(play.get("tasks"))
    assert play.get("hosts") == "socrat-4"
    assert names[0] == "Require a known phase and explicit confirmation"
    assert names[-1] == "Require Kubernetes mode after failback"
    assert len(names) == MOSCOW_TASKS
    assert len(names) == len(set(names))
    assert 'default("preflight")' in source
    assert "phase == 'return'" in source
    assert "controller.stat.checksum == new_sha" in source
    assert '(voters.stdout | from_json)["items"]' in source
    assert "(voters.stdout | from_json).items" not in source
    assert "kubectl delete" not in source
    assert "wg-quick" not in source


def test_tv_url_names_keep_the_single_preference_contract() -> None:
    """Name every TV URL task without changing the URL-only contract."""
    source = TV.read_text()
    play = _mapping(_sequence(yaml.safe_load(source))[0])
    names = _task_names(play.get("tasks"))
    assert play.get("hosts") == "socrat-0"
    assert "Decode the approved Fully start URL" in names
    assert names[-1] == "Clear the uncertain import marker after success"
    assert len(names) == TV_TASKS
    assert len(names) == len(set(names))
    assert "{'startURL':tv_start_url}" in source
    assert "tv_public_hash == tv_plan_hash" in source
    assert "tv_network_after.stdout == tv_network_before.stdout" in source
    assert "am force-stop de.ozerov.fully; am start -n de.ozerov.fully/.FullyActivity" in source
    assert "adb install" not in source
    assert "settings put" not in source
