"""Offline checks for update-watch version comparison."""

import importlib.util
from pathlib import Path

MODULE = Path("charts/monitoring-k3s/files/update_watch.py")


def load_module():
    spec = importlib.util.spec_from_file_location("update_watch", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_open_webui_style_gap_is_an_update() -> None:
    """Treat the newest stable tag as newer than an older slim build."""
    watch = load_module()
    releases = [
        {"tag_name": "v0.13.3", "draft": False, "prerelease": False},
        {"tag_name": "v0.13.4-rc.1", "draft": False, "prerelease": True},
        {"tag_name": "v0.12.3", "draft": False, "prerelease": False},
    ]
    latest, tag = watch.latest_stable(releases)
    assert tag == "v0.13.3"
    assert latest > watch.parse_version("v0.12.3-slim")


def test_equal_version_is_not_an_update() -> None:
    """Report no update and a successful lookup when versions match."""
    watch = load_module()

    def fetch(_repo, _timeout):
        return [{"tag_name": "v1.2.3", "draft": False, "prerelease": False}]

    samples = watch.evaluate(
        [{"id": "demo", "title": "Demo", "current": "1.2.3", "github": "acme/demo"}],
        fetch,
        1,
    )
    assert samples[0]["available"] == 0
    assert samples[0]["success"] == 1
    body = watch.render_metrics(samples)
    assert 'current="1.2.3"' in body and "} 0" in body


def test_failed_lookup_does_not_claim_an_update() -> None:
    """Keep the update gauge at zero when the lookup raises OSError."""
    watch = load_module()

    def fetch(_repo, _timeout):
        raise OSError("github unavailable")

    samples = watch.evaluate(
        [{"id": "demo", "title": "Demo", "current": "1.2.3", "github": "acme/demo"}],
        fetch,
        1,
    )
    assert samples[0]["available"] == 0
    assert samples[0]["success"] == 0


def test_catalog_lists_open_webui() -> None:
    """Require the Open WebUI catalog pin recorded in the chart values."""
    text = Path("charts/monitoring-k3s/values.yaml").read_text()
    assert "github: open-webui/open-webui" in text
    assert 'current: "0.12.3"' in text
