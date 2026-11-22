"""Offline checks for update-watch version comparison."""

import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import NoReturn, TypedDict
from unittest.mock import patch

import pytest
import yaml

MODULE = Path("charts/monitoring-k3s/files/update_watch.py")


class Release(TypedDict):
    """Concrete release fields emitted by these local fetch fixtures."""

    tag_name: str
    draft: bool
    prerelease: bool


def load_module() -> ModuleType:
    """Load the actual module without claiming unverified callable signatures."""
    spec = importlib.util.spec_from_file_location("update_watch", MODULE)
    if spec is None or spec.loader is None:
        message = "cannot load update watch"
        raise ImportError(message)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_open_webui_style_gap_is_an_update() -> None:
    """Treat the newest stable tag as newer than an older slim build."""
    watch = load_module()
    releases: list[Release] = [
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

    def fetch(_repo: str, _timeout: int) -> list[Release]:
        return [{"tag_name": "v1.2.3", "draft": False, "prerelease": False}]

    samples = watch.evaluate(
        [{"id": "demo", "title": "Demo", "current": "1.2.3", "github": "acme/demo"}],
        fetch,
        1,
    )
    assert samples[0]["available"] == 0
    assert samples[0]["success"] == 1
    body = watch.render_metrics(samples)
    assert 'current="1.2.3"' in body
    assert "} 0" in body


def test_failed_lookup_does_not_claim_an_update() -> None:
    """Keep the update gauge at zero when the lookup raises OSError."""
    watch = load_module()

    def fetch(_repo: str, _timeout: int) -> NoReturn:
        message = "github unavailable"
        raise OSError(message)

    samples = watch.evaluate(
        [{"id": "demo", "title": "Demo", "current": "1.2.3", "github": "acme/demo"}],
        fetch,
        1,
    )
    assert samples[0]["available"] == 0
    assert samples[0]["success"] == 0


def test_catalog_lists_open_webui() -> None:
    """Require the Open WebUI catalog pin recorded in the chart values."""
    catalog = yaml.safe_load(Path("charts/monitoring-k3s/values.yaml").read_text())["updateWatch"]
    [target] = [target for target in catalog["targets"] if target["id"] == "open-webui"]
    assert target["github"] == "open-webui/open-webui"
    assert target["current"] == "0.12.3"


@pytest.mark.parametrize("spec", [None, ModuleSpec("update_watch", loader=None)])
def test_loader_refuses_missing_spec_or_loader(spec: ModuleSpec | None) -> None:
    """Refuse incomplete loader metadata before constructing or executing a module."""
    with (
        patch("importlib.util.spec_from_file_location", return_value=spec),
        patch("importlib.util.module_from_spec") as construct,
        pytest.raises(ImportError, match="cannot load update watch"),
    ):
        load_module()
    construct.assert_not_called()


def test_import_and_fixture_evaluation_do_not_start_external_work() -> None:
    """Trap network, poller and HTTP-server entrypoints throughout the original cases."""
    with (
        patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")) as network,
        patch("threading.Thread", side_effect=AssertionError("poller forbidden")) as poller,
        patch(
            "http.server.ThreadingHTTPServer",
            side_effect=AssertionError("server forbidden"),
        ) as server,
    ):
        test_open_webui_style_gap_is_an_update()
        test_equal_version_is_not_an_update()
        test_failed_lookup_does_not_claim_an_update()
        test_catalog_lists_open_webui()
    network.assert_not_called()
    poller.assert_not_called()
    server.assert_not_called()


def test_statefulset_target_and_ambiguous_workload() -> None:
    import pytest

    watch = load_module()
    assert watch.workload_ref({"statefulset": "openhands"}) == (
        "statefulsets",
        "openhands",
    )
    assert watch.workload_ref({"deployment": "open-webui"}) == (
        "deployments",
        "open-webui",
    )
    with pytest.raises(ValueError):
        watch.workload_ref({"deployment": "a", "statefulset": "b"})


def test_openhands_uses_running_canvas_tag_not_sdk_version() -> None:
    watch = load_module()
    catalog = yaml.safe_load(Path("charts/monitoring-k3s/values.yaml").read_text())["updateWatch"][
        "targets"
    ]
    target = next(x for x in catalog if x["id"] == "openhands")
    assert target["github"] == "OpenHands/OpenHands"
    assert target["statefulset"] == "openhands"
    assert target["namespace"] == "openhands"
    assert target["container"] == "agent-canvas"
    samples = watch.evaluate(
        [target],
        lambda _repo, _t: [{"tag_name": "v1.42.0"}],
        1,
        {"openhands": "ghcr.io/openhands/agent-canvas:1.41.0@sha256:fixture"},
    )
    assert samples[0]["current"] == "1.41.0"
    assert samples[0]["latest"] == "1.42.0"
    assert samples[0]["available"] == 1
    assert samples[0]["success"] == 1


def test_searxng_uses_only_versioned_image_tags():
    import io
    import json

    watch = load_module()
    target = {"id": "searxng", "current": "2026.10.19", "source": "searxng-image-tags"}
    for tags, expected in [
        (["latest", "2026.11.21-c6ee3e9fd", "2099.1.1-dev"], 1),
        ([], 0),
    ]:
        body = json.dumps({"results": [{"name": name} for name in tags]}).encode()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(body)):
            sample = watch.evaluate([target], None, 1)[0]
        assert (sample["success"], sample["available"]) == (expected, expected)


def test_actionable_counts_exclude_suppressed_but_emit_real_zero() -> None:
    render = load_module().actionable_metrics
    alerts = [
        {
            "labels": {"severity": "warning", "alertname": "PodFailed"},
            "status": {"state": state},
        }
        for state in ("suppressed", "active")
    ]
    assert b'severity="warning"} 0\n' in render(alerts[:1])
    assert b'severity="warning"} 1\n' in render(alerts)
    with pytest.raises(ValueError):
        render({})


def test_status_page_catalog_tracks_gatus_not_retired_kuma() -> None:
    targets = yaml.safe_load(Path("charts/monitoring-k3s/values.yaml").read_text())[
        "updateWatch"
    ]["targets"]
    catalog = {item["id"]: item for item in targets}
    chart = yaml.safe_load(
        Path("charts/uptime-kuma/charts/gatus/Chart.yaml").read_text()
    )
    assert "uptime-kuma" not in catalog
    assert catalog["gatus"]["github"] == "TwiN/gatus"
    assert catalog["gatus"]["current"] == chart["appVersion"]
