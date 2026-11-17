"""Offline contract for the swe-mini release workflow.

The publish job still builds and deploys the same image. Action references are
the commits their previous tags resolved to, and checkout does not persist
credentials into the workspace.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github/workflows/swe-mini-release.yml"
_GIT_SHA_LENGTH = 40
_STEP_COUNT = 8
_STATEMENT_COUNT = 3
_TIMEOUT_MINUTES = 20
_PAIR_COUNT = 2
_CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
_SETUP_PYTHON = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
_BUILDX = "docker/setup-buildx-action@8d2750c68a42422c14e847fe6c8ac0403b4cbd6f"
_BUILD_PUSH = "docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8"
_DEPLOY = "alchemmist/deploy-to-socrat@56037a9bf2a4d7b5c0fd715911a0efa9032ae7a6"
_HEX_DIGITS = set("0123456789abcdef")
_TRIGGER_KEY = "on"
_CLEANUP_NAME = "Remove ephemeral registry credentials"


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    result: dict[str, object] = {}
    for key, item in value.items():
        assert isinstance(key, str)
        result[key] = item
    return result


def _load(text: str) -> dict[str, object]:
    """Load workflow YAML. PyYAML 1.1 parses the trigger key as boolean true."""
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict)
    result: dict[str, object] = {}
    saw_trigger = False
    for key, item in loaded.items():
        if key is True:
            assert not saw_trigger
            saw_trigger = True
            result[_TRIGGER_KEY] = item
            continue
        assert isinstance(key, str)
        result[key] = item
    assert saw_trigger
    return result


def _sequence(value: object) -> list[object]:
    assert isinstance(value, list)
    return list(value)


def _text(value: object) -> str:
    assert isinstance(value, str)
    return value


def _secret(name: str) -> str:
    return "${{ secrets." + name + " }}"


def _pinned_sha(uses: str) -> str:
    action, separator, sha = uses.rpartition("@")
    assert separator == "@"
    assert action
    assert len(sha) == _GIT_SHA_LENGTH
    assert set(sha) <= _HEX_DIGITS
    return sha


def _workflow() -> dict[str, object]:
    return _load(_WORKFLOW.read_text())


def _publish(workflow: dict[str, object]) -> dict[str, object]:
    jobs = _mapping(workflow["jobs"])
    assert set(jobs) == {"publish"}
    return _mapping(jobs["publish"])


def _steps(workflow: dict[str, object]) -> list[dict[str, object]]:
    publish = _publish(workflow)
    return [_mapping(step) for step in _sequence(publish["steps"])]


def _constant(value: ast.expr) -> object:
    assert isinstance(value, ast.Constant)
    return value.value


def test_release_trigger_stays_manual_or_mainline_and_read_only() -> None:
    """Dispatch and mainline path filters stay read-only and least privilege."""
    text = _WORKFLOW.read_text()
    assert text.startswith("---\n")
    assert text.endswith("...\n")
    workflow = _load(text)
    assert workflow["name"] == "SWE Mini Release"
    assert _mapping(workflow["permissions"]) == {"contents": "read"}
    assert _mapping(workflow["concurrency"]) == {
        "group": "swe-mini-release",
        "cancel-in-progress": False,
    }
    trigger = _mapping(workflow[_TRIGGER_KEY])
    assert set(trigger) == {"workflow_dispatch", "push"}
    assert trigger["workflow_dispatch"] == {}
    push = _mapping(trigger["push"])
    assert _sequence(push["branches"]) == ["main"]
    assert _sequence(push["paths"]) == [
        "services/swe-mini/**",
        ".github/workflows/swe-mini-release.yml",
    ]
    publish = _publish(workflow)
    assert "permissions" not in publish
    assert publish["name"] == "publish"
    assert publish["runs-on"] == "ubuntu-24.04"
    assert publish["timeout-minutes"] == _TIMEOUT_MINUTES


def test_release_workflow_pins_current_actions_without_persisted_credentials() -> None:
    """Freeze the current action commits and refuse a credential-bearing checkout."""
    steps = _steps(_workflow())
    assert len(steps) == _STEP_COUNT
    checkout, setup, tests, harbor, buildx, image, deploy, cleanup = steps
    assert checkout["uses"] == _CHECKOUT
    assert _mapping(checkout["with"]) == {"persist-credentials": False}
    assert setup["uses"] == _SETUP_PYTHON
    assert _mapping(setup["with"]) == {"python-version": "3.12"}
    assert tests["name"] == "Test publication boundaries"
    assert tests["run"] == "python -m unittest discover -s tests/swe_mini -v"
    assert harbor["name"] == "Verify existing scoped Harbor robot"
    assert harbor["run"] == "python3 scripts/harbor_ci_auth.py --repository homelab/swe-mini"
    assert _mapping(harbor["env"]) == {
        "HARBOR_USERNAME": _secret("HARBOR_USERNAME"),
        "HARBOR_PASSWORD": _secret("HARBOR_PASSWORD"),
    }
    assert buildx["uses"] == _BUILDX
    assert image["uses"] == _BUILD_PUSH
    assert image["id"] == "image"
    assert deploy["name"] == "Deploy to Socrat"
    assert deploy["uses"] == _DEPLOY
    assert cleanup["name"] == _CLEANUP_NAME
    assert cleanup["if"] == "always()"
    for uses in (_CHECKOUT, _SETUP_PYTHON, _BUILDX, _BUILD_PUSH, _DEPLOY):
        _pinned_sha(uses)


def test_release_image_build_and_deploy_inputs_stay_unchanged() -> None:
    """Harbor publish, cache, and deploy inputs keep their original values."""
    _checkout, _setup, _tests, _harbor, buildx, image, deploy, _cleanup = _steps(_workflow())
    assert _mapping(buildx["with"]) == {"driver-opts": "env.GODEBUG=tlsmlkem=0\n"}
    assert _mapping(image["with"]) == {
        "context": "services/swe-mini",
        "push": True,
        "platforms": "linux/amd64",
        "tags": "harbor.socrat.alchemmist.xyz/homelab/swe-mini:${{ github.sha }}",
        "cache-from": "type=gha",
        "cache-to": "type=gha,mode=max",
    }
    assert _mapping(deploy["with"]) == {
        "token": _secret("HOMELAB_DEPLOY_KEY"),
        "app": "swe-mini",
        "image_version": "${{ steps.image.outputs.digest }}",
    }


def _cleanup_module() -> ast.Module:
    matches = [step for step in _steps(_workflow()) if step.get("name") == _CLEANUP_NAME]
    assert len(matches) == 1
    script = _text(matches[0]["run"])
    marker = "<<'PY'\n"
    assert script.startswith("python3 - " + marker)
    source, terminator, trailing = script.split(marker, 1)[1].rpartition("\nPY")
    assert terminator == "\nPY"
    assert trailing == "\n"
    module = ast.parse(source)
    assert len(module.body) == _STATEMENT_COUNT
    return module


def test_release_cleanup_selects_only_the_ephemeral_harbor_directory() -> None:
    """Cleanup reads DOCKER_CONFIG and accepts only this job's runner directory."""
    module = _cleanup_module()
    imported = module.body[0]
    assignment = module.body[1]
    conditional = module.body[2]
    assert isinstance(imported, ast.Import)
    assert [alias.name for alias in imported.names] == ["os", "pathlib"]
    assert isinstance(assignment, ast.Assign)
    assert len(assignment.targets) == 1
    target = assignment.targets[0]
    assert isinstance(target, ast.Name)
    assert target.id == "directory"
    path_call = assignment.value
    assert isinstance(path_call, ast.Call)
    assert isinstance(path_call.func, ast.Attribute)
    assert path_call.func.attr == "Path"
    assert len(path_call.args) == 1
    config = path_call.args[0]
    assert isinstance(config, ast.Call)
    assert isinstance(config.func, ast.Attribute)
    assert config.func.attr == "get"
    assert len(config.args) == _PAIR_COUNT
    assert [_constant(argument) for argument in config.args] == ["DOCKER_CONFIG", "/nonexistent"]
    assert isinstance(conditional, ast.If)
    assert isinstance(conditional.test, ast.BoolOp)
    assert isinstance(conditional.test.op, ast.And)
    assert len(conditional.test.values) == _PAIR_COUNT
    guard = conditional.test.values[0]
    assert isinstance(guard, ast.Call)
    assert isinstance(guard.func, ast.Attribute)
    assert guard.func.attr == "startswith"
    assert len(guard.args) == 1
    assert _constant(guard.args[0]) == "harbor-ci-auth-"
    parent_check = conditional.test.values[1]
    assert isinstance(parent_check, ast.Compare)
    assert len(parent_check.ops) == 1
    assert isinstance(parent_check.ops[0], ast.Eq)
    assert isinstance(parent_check.left, ast.Attribute)
    assert parent_check.left.attr == "parent"
    assert len(parent_check.comparators) == 1
    comparator = parent_check.comparators[0]
    assert isinstance(comparator, ast.Call)
    assert isinstance(comparator.func, ast.Attribute)
    assert comparator.func.attr == "Path"
    assert len(comparator.args) == 1
    runner_temp = comparator.args[0]
    assert isinstance(runner_temp, ast.Subscript)
    assert _constant(runner_temp.slice) == "RUNNER_TEMP"


def test_release_cleanup_unlinks_only_the_guarded_config_file() -> None:
    """The unlink stays inside the guard and tolerates an already removed file."""
    conditional = _cleanup_module().body[2]
    assert isinstance(conditional, ast.If)
    assert conditional.orelse == []
    assert len(conditional.body) == 1
    statement = conditional.body[0]
    assert isinstance(statement, ast.Expr)
    assert isinstance(statement.value, ast.Call)
    unlink = statement.value
    assert isinstance(unlink.func, ast.Attribute)
    assert unlink.func.attr == "unlink"
    assert unlink.args == []
    assert len(unlink.keywords) == 1
    missing_ok = unlink.keywords[0]
    assert missing_ok.arg == "missing_ok"
    assert _constant(missing_ok.value) is True
