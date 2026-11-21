"""Offline checks for update-watch version comparison."""

import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import NoReturn, TypedDict
from unittest.mock import patch

import pytest

MODULE = Path("charts/monitoring-k3s/files/update_watch.py")


class Release(TypedDict):
    """Concrete release fields emitted by these local fetch fixtures."""

    tag_name: str
    draft: bool
    prerelease: bool


def load_module() -> ModuleType:
    """Document this test or helper."""
    """Load the actual module without claiming unverified callable signatures."""
    spec = importlib.util.spec_from_file_location("update_watch", MODULE)
    if spec is None or spec.loader is None:
        message = "cannot load update watch"
        raise ImportError(message)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_open_webui_style_gap_is_an_update() -> None:
    """Document this test or helper."""
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
    """Document this test or helper."""
    """Report no update and a successful lookup when versions match."""
    watch = load_module()

    def fetch(_repo: str, _timeout: int) -> list[Release]:
        """Document this test or helper."""
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
    """Document this test or helper."""
    """Keep the update gauge at zero when the lookup raises OSError."""
    watch = load_module()

    def fetch(_repo: str, _timeout: int) -> NoReturn:
        """Document this test or helper."""
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
    """Document this test or helper."""
    """Require the Open WebUI catalog pin recorded in the chart values."""
    text = Path("charts/monitoring-k3s/values.yaml").read_text()
    assert "github: open-webui/open-webui" in text
    assert 'current: "0.12.3"' in text


@pytest.mark.parametrize("spec", [None, ModuleSpec("update_watch", loader=None)])
def test_loader_refuses_missing_spec_or_loader(spec: ModuleSpec | None) -> None:
    """Document this test or helper."""
    """Refuse incomplete loader metadata before constructing or executing a module."""
    with (
        patch("importlib.util.spec_from_file_location", return_value=spec),
        patch("importlib.util.module_from_spec") as construct,
        pytest.raises(ImportError, match="cannot load update watch"),
    ):
        load_module()
    construct.assert_not_called()


def test_import_and_fixture_evaluation_do_not_start_external_work() -> None:
    """Document this test or helper."""
    """Trap network, poller and HTTP-server entrypoints throughout the original cases."""
    with (
        patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")) as network,
        patch("threading.Thread", side_effect=AssertionError("poller forbidden")) as poller,
        patch(
            "http.server.ThreadingHTTPServer", side_effect=AssertionError("server forbidden")
        ) as server,
    ):
        test_open_webui_style_gap_is_an_update()
        test_equal_version_is_not_an_update()
        test_failed_lookup_does_not_claim_an_update()
        test_catalog_lists_open_webui()
    network.assert_not_called()
    poller.assert_not_called()
    server.assert_not_called()


def test_statefulset_target_and_ambiguous_workload():
    """Document this test or helper."""
    import pytest

    watch = load_module()
    assert watch.workload_ref({"statefulset": "openhands"}) == ("statefulsets", "openhands")
    assert watch.workload_ref({"deployment": "open-webui"}) == ("deployments", "open-webui")
    with pytest.raises(ValueError):
        watch.workload_ref({"deployment": "a", "statefulset": "b"})


def test_openhands_uses_running_canvas_tag_not_sdk_version():
    """Document this test or helper."""
    import yaml

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
        lambda repo, t: [{"tag_name": "v1.42.0"}],
        1,
        {"openhands": "ghcr.io/openhands/agent-canvas:1.41.0@sha256:fixture"},
    )
    assert samples[0]["current"] == "1.41.0"
    assert samples[0]["latest"] == "1.42.0"
    assert samples[0]["available"] == 1
    assert samples[0]["success"] == 1
