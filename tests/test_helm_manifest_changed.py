"""Offline checks for the Helm manifest comparison helper."""

import contextlib
import io
import json
import runpy
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ansible/files/helm_manifest_changed.py"
ARGUMENTS = [
    str(SCRIPT),
    "--release",
    "syncthing",
    "--chart",
    "/chart",
    "--namespace",
    "syncthing",
    "--values",
    "/values",
    "--kubeconfig",
    "/config",
]


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys rather than silently keeping the last value."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            message = "Duplicate Helm comparison field"
            raise ValueError(message)
        result[key] = value
    return result


def _comparison_result(text: str) -> dict[str, bool]:
    """Admit exactly the real producer's single boolean changed field."""
    try:
        parsed: object = json.loads(text, object_pairs_hook=_unique_fields)
    except json.JSONDecodeError as exc:
        message = "Invalid Helm comparison JSON"
        raise ValueError(message) from exc
    if not isinstance(parsed, dict):
        message = "Helm comparison must be an object"
        raise TypeError(message)
    if set(parsed) != {"changed"}:
        message = "Helm comparison requires exactly the changed field"
        raise ValueError(message)
    changed: object = parsed["changed"]
    if not isinstance(changed, bool):
        message = "Helm comparison changed must be boolean"
        raise TypeError(message)
    return {"changed": changed}


class HelmManifestComparisonTests(unittest.TestCase):
    """Contract for the offline Helm manifest comparison helper."""

    def compare(
        self,
        installed: subprocess.CompletedProcess[str],
        desired: str = "manifest\n",
    ) -> dict[str, bool]:
        """Run the unchanged CLI with every process call replaced by fixture results."""
        output = io.StringIO()
        rendered = subprocess.CompletedProcess(["helm", "template"], 0, desired, "")
        with (
            patch("sys.argv", ARGUMENTS),
            patch("subprocess.run", side_effect=[rendered, installed]),
            contextlib.redirect_stdout(output),
        ):
            runpy.run_path(str(SCRIPT), run_name="__main__")
        return _comparison_result(output.getvalue())

    def test_equal_manifests_skip_upgrade(self) -> None:
        """Treat identical manifests as unchanged."""
        result = self.compare(subprocess.CompletedProcess(["helm", "get"], 0, "manifest\n", ""))
        assert not result["changed"]

    def test_changed_manifest_requires_upgrade(self) -> None:
        """Require an upgrade when the installed manifest differs."""
        result = self.compare(subprocess.CompletedProcess(["helm", "get"], 0, "old manifest", ""))
        assert result["changed"]

    def test_missing_release_allows_installation(self) -> None:
        """Allow installation when the release is absent."""
        result = self.compare(
            subprocess.CompletedProcess(["helm", "get"], 1, "", "Error: release: not found\n")
        )
        assert result["changed"]

    def test_read_failure_aborts_without_authorizing_upgrade(self) -> None:
        """Abort when reading the release fails for any other reason."""
        for error in [
            "Error: Kubernetes cluster unreachable",
            "Error: forbidden",
            "unexpected error",
        ]:
            with (
                self.subTest(error=error),
                pytest.raises(subprocess.CalledProcessError),
            ):
                self.compare(subprocess.CompletedProcess(["helm", "get"], 1, "", error))


@pytest.mark.parametrize(
    ("payload", "expected_result"),
    [
        ('{"changed":true}', {"changed": True}),
        ('{"changed":false}', {"changed": False}),
    ],
)
def test_comparison_result_preserves_boolean(
    payload: str, expected_result: dict[str, bool]
) -> None:
    """Keep both legitimate producer results without truthiness coercion."""
    assert _comparison_result(payload) == expected_result


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ("null", TypeError),
        ("[]", TypeError),
        ("true", TypeError),
        ("1", TypeError),
        ('"changed"', TypeError),
        ("{}", ValueError),
        ('{"changed":1}', TypeError),
        ('{"changed":null}', TypeError),
        ('{"changed":false,"extra":true}', ValueError),
        ('{"changed":false,"changed":true}', ValueError),
        ('{"changed":true,"changed":false}', ValueError),
        ("{broken", ValueError),
    ],
)
def test_comparison_result_rejects_protocol_drift(
    payload: str, error_type: type[Exception]
) -> None:
    """Reject malformed, ambiguous, extra-field and nonboolean CLI results."""
    with pytest.raises(error_type, match="Helm comparison"):
        _comparison_result(payload)


def test_render_failure_stops_before_reading_installed_release() -> None:
    """Refuse a render failure before a second process call or JSON authorization."""
    error = subprocess.CalledProcessError(1, ["helm", "template"], stderr="render failed")
    output = io.StringIO()
    with (
        patch("sys.argv", ARGUMENTS),
        patch("subprocess.run", side_effect=error) as process,
        contextlib.redirect_stdout(output),
        pytest.raises(subprocess.CalledProcessError) as raised,
    ):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert raised.value is error
    assert process.call_count == 1
    assert output.getvalue() == ""


if __name__ == "__main__":
    unittest.main()


@pytest.mark.parametrize(
    ("rc", "stdout", "stderr", "expected"),
    [
        (0, "same", "", "current"),
        (0, "different", "", "upgrade"),
        (1, "", "Error: release: not found\n", "install"),
        (1, "", "forbidden", None),
    ],
)
def test_explicit_plan_preserves_comparison_and_fails_closed(
    rc, stdout, stderr, expected, capsys
) -> None:
    rendered = subprocess.CompletedProcess(["helm", "template"], 0, "same\n", "")
    installed = subprocess.CompletedProcess(["helm", "get"], rc, stdout, stderr)
    with (
        patch("sys.argv", [*ARGUMENTS, "--plan"]),
        patch("subprocess.run", side_effect=[rendered, installed]),
    ):
        if expected is None:
            with pytest.raises(subprocess.CalledProcessError):
                runpy.run_path(str(SCRIPT), run_name="__main__")
            assert not capsys.readouterr().out
        else:
            runpy.run_path(str(SCRIPT), run_name="__main__")
            assert capsys.readouterr().out.strip() == expected
