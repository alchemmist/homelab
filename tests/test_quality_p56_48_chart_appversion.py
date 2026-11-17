"""Plain Chart.yaml appVersion scalars keep their version text."""

from pathlib import Path

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
        assert text == expected
        version = next(
            line.removeprefix("appVersion: ")
            for line in expected.splitlines()
            if line.startswith("appVersion: ")
        )
        assert " " not in version
        assert version[:1].isdigit()
