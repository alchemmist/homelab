"""Tests for removing the Rancher home landing page."""

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from typing import NotRequired, TypedDict
from unittest.mock import MagicMock, patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTION_SPEC = importlib.util.spec_from_file_location(
    "dashboard_descriptions", ROOT / "ansible/files/dashboard_descriptions.py"
)
assert DESCRIPTION_SPEC is not None
DESCRIPTIONS = importlib.util.module_from_spec(DESCRIPTION_SPEC)
DESCRIPTION_SPEC.loader.exec_module(DESCRIPTIONS)
SPEC = importlib.util.spec_from_file_location(
    "rancher_renderer", ROOT / "ansible/roles/monitoring_rancher/files/name_node_series.py"
)
assert SPEC is not None
RENDERER = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"dashboard_descriptions": DESCRIPTIONS}):
    SPEC.loader.exec_module(RENDERER)


def _mapping(value: object) -> dict[str, object]:
    """Narrow one rendered document for dictionary-style keyed access."""
    assert isinstance(value, dict)
    return value


class _DocumentMetadata(TypedDict):
    """Metadata of a rendered public dashboard ConfigMap."""

    name: str
    annotations: NotRequired[dict[str, str]]


class _Document(TypedDict):
    """Rendered manifest documents that survive dashboard filtering."""

    kind: str
    metadata: _DocumentMetadata
    data: NotRequired[dict[str, str]]


class _HomeDocument(TypedDict):
    """Dashboard ConfigMap fixture, which always has mutable data."""

    kind: str
    metadata: _DocumentMetadata
    data: dict[str, str]
    binaryData: NotRequired[dict[str, str]]


class RancherDashboardFilteringTest(unittest.TestCase):
    """Verify Rancher dashboard rendering filters disallowed resources."""
    def render(self, resources, allowed=()) -> tuple[list[_Document], MagicMock]:
        """Render resources through the fixture runner."""

        output = io.StringIO()
        with (
            patch.object(RENDERER, "RANCHER_DASHBOARD_UIDS", set(allowed)),
            patch.object(RENDERER, "apply_descriptions") as describe,
            patch.object(sys, "stdin", io.StringIO(yaml.safe_dump_all(resources))),
            patch.object(sys, "stdout", output),
        ):
            RENDERER.main()
        return list(yaml.safe_load_all(output.getvalue())), describe

    def home(self) -> _HomeDocument:
        """Return a home ConfigMap fixture."""

        return {
            "kind": "ConfigMap",
            "metadata": {"name": "home"},
            "data": {
                "home.json": json.dumps({"uid": "rancher-home-1", "title": "Home", "panels": []}),
            },
        }

    def test_drops_home_only_configmap_without_loading_its_descriptions(self) -> None:
        """Drops home only configmap without loading its descriptions."""

        resource = {"kind": "Service", "metadata": {"name": "preserved"}}
        rendered, describe = self.render([self.home(), resource])
        assert rendered == [resource]
        describe.assert_not_called()
        assert "rancher-home-1" not in RENDERER.RANCHER_DASHBOARD_UIDS

    def test_drops_all_unselected_dashboards_without_loading_descriptions(self) -> None:
        """Drops all unselected dashboards without loading descriptions."""

        resource = self.home()
        resource["data"]["diagnostic.json"] = json.dumps(
            {
                "uid": "diagnostic",
                "title": "Diagnostic",
                "panels": [],
            }
        )
        rendered, describe = self.render([resource])
        assert rendered == []
        describe.assert_not_called()

    def test_preserves_embedded_dashboard_in_shared_configmap(self) -> None:
        """Preserves embedded dashboard in shared configmap."""

        resource = self.home()
        dashboard = {"uid": "rancher-pod-1", "title": "Rancher / Pod", "panels": []}
        resource["data"]["pod.json"] = json.dumps(dashboard)
        rendered, describe = self.render([resource], allowed={"rancher-pod-1"})
        dashboard["title"] = "Pod"
        assert len(rendered) == 1
        assert set(rendered[0]["data"]) == {"pod.json"}
        assert json.loads(rendered[0]["data"]["pod.json"]) == dashboard
        assert rendered[0]["metadata"]["annotations"]["grafana_folder"] == "/tmp/dashboards/Rancher"
        describe.assert_called_once_with(dashboard)

    def test_preserves_non_dashboard_json(self) -> None:
        """Preserves non dashboard json."""

        data = {
            "settings.json": json.dumps({"uid": "settings", "enabled": True}),
            "list.json": "[1, 2]",
            "template.json": "{{ value }}",
        }
        resource = self.home()
        resource["data"].update(data)
        rendered, describe = self.render([resource])
        assert rendered[0]["data"] == data
        describe.assert_not_called()

    def test_preserves_unrelated_data_and_binary_data(self) -> None:
        """Preserves unrelated data and binary data."""

        for field, data in [
            ("data", {"settings.txt": "keep"}),
            ("binaryData", {"payload": "a2VlcA=="}),
        ]:
            with self.subTest(field=field):
                resource = self.home()
                added = _mapping(resource).setdefault(field, {})
                assert isinstance(added, dict)
                added.update(data)
                rendered, describe = self.render([resource])
                assert len(rendered) == 1
                assert _mapping(rendered[0])[field] == data
                assert "home.json" not in rendered[0]["data"]
                describe.assert_not_called()

    def test_missing_required_dashboard_still_blocks_rendering(self) -> None:
        """Missing required dashboard still blocks rendering."""

        with (
            patch.object(RENDERER, "RANCHER_DASHBOARD_UIDS", {"required"}),
            patch.object(sys, "stdin", io.StringIO(yaml.safe_dump(self.home()))),
            patch.object(sys, "stdout", io.StringIO()),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing Rancher dashboards: required"):
                RENDERER.main()


if __name__ == "__main__":
    unittest.main()
