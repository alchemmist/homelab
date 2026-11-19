"""Plain Chart.yaml appVersion scalars keep their version text."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

# Whole-file locks. Only the appVersion quote style was allowed to change.
CHART_TEXT = {
    "charts/open-terminal/Chart.yaml": (
        "---\napiVersion: v2\nname: open-terminal\nversion: 0.1.0\nappVersion: 0.14.1\n...\n"
    ),
    "charts/pyroscope/Chart.yaml": (
        "---\n"
        "apiVersion: v2\n"
        "name: pyroscope\n"
        "description: Private single-binary Pyroscope and Grafana CPU flame graphs\n"
        "version: 0.1.0\n"
        "appVersion: 2.4.2\n"
        "...\n"
    ),
    "charts/traefik-edge/Chart.yaml": (
        "---\n"
        "apiVersion: v2\n"
        "name: traefik-edge\n"
        "description: VPS public ingress for cluster services and VPN endpoints\n"
        "version: 0.2.0\n"
        "appVersion: 3.7.13\n"
        "...\n"
    ),
}


def test_chart_app_versions_stay_plain_strings() -> None:
    """Dotted appVersion values stay unquoted strings, byte-for-byte."""
    for relative, expected in CHART_TEXT.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        if relative == "charts/pyroscope/Chart.yaml":
            # Release is an independent owner input, not a new format baseline.
            # Keep the original whole-file lock for every other byte/field.
            image = yaml.safe_load((ROOT / "charts/pyroscope/values.yaml").read_text())["image"]
            release = image.split("@", 1)[0].rsplit(":", 1)[1]
            assert yaml.safe_load(text)["appVersion"] == release
            expected = expected.replace("appVersion: 2.4.2\n", "appVersion: " + release + "\n")
        assert text == expected
        version = next(
            line.removeprefix("appVersion: ")
            for line in expected.splitlines()
            if line.startswith("appVersion: ")
        )
        assert " " not in version
        assert version[:1].isdigit()


@pytest.mark.parametrize("violation", ["version", "quotes", "identity"])
def test_current_owner_version_input_does_not_hide_drift(
    monkeypatch: pytest.MonkeyPatch, violation: str
) -> None:
    """Keep current image consistency, exact metadata and scalar-style negatives."""
    test_chart_app_versions_stay_plain_strings()
    original = Path.read_text

    def changed(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        text = original(path, encoding=encoding, errors=errors)
        if path == ROOT / "charts/pyroscope/Chart.yaml":
            before, after = {
                "version": ("appVersion: 2.4.3", "appVersion: 99.0.0"),
                "quotes": ("appVersion: 2.4.3", 'appVersion: "2.4.3"'),
                "identity": ("name: pyroscope", "name: unreviewed"),
            }[violation]
            assert before in text
            text = text.replace(before, after, 1)
        return text

    monkeypatch.setattr(Path, "read_text", changed)
    with pytest.raises(AssertionError):
        test_chart_app_versions_stay_plain_strings()
