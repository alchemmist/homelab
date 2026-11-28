import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import graph_evidence as graphs
import pytest
from core import Failure
from evidence_bundle import prepare_bundle, publish_parts, storage_objects
from graph_contract import GraphError, validate_png
from test_graph_contract import annotation, graph, png


class GraphEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = patch.object(graphs, "ARTIFACT_ROOT", Path(self.tmp.name) / "graphs")
        root.start()
        self.addCleanup(root.stop)
        space = patch.object(graphs, "MIN_FREE_BYTES", 0)
        space.start()
        self.addCleanup(space.stop)
        self.event = {
            "event_key": "a" * 64,
            "episode": "b" * 64,
            "status": "firing",
            "startsAt": "2020-01-01T00:00:00Z",
            "endsAt": None,
            "labels": {"service": "api"},
            "annotations": {"spi_graphs": annotation()},
        }
        self.raw = png()
        self.client = Mock()
        self.client.render.return_value = (self.raw, validate_png(self.raw))

    def test_retry_reuses_snapshot_without_transport(self):
        first, missing = graphs.collect(self.event, self.client)
        assert not missing
        second, missing = graphs.collect(self.event, self.client)
        assert not missing
        assert first == second
        assert self.client.render.call_count == 1
        assert graphs.read_artifact(first[0]["reference"]) == self.raw

    def test_model_context_and_binary_roundtrip(self):
        captured, missing = graphs.collect(self.event, self.client)
        bundle = prepare_bundle(self.event, {}, [{"name": "logs.json", "content": "original text"}])
        original_context = copy.deepcopy(bundle["model_context"])
        result = graphs.attach(bundle, captured, missing)
        assert result["model_context"] == original_context
        assert bundle["manifest"]["format"] == "socrat-evidence-v2"
        assert result["manifest"]["format"] == "socrat-evidence-v3"
        assert "data_base64" not in json.dumps(result)
        objects = storage_objects(result)
        assert objects[-1][1] == self.raw
        assert objects[-1][0].endswith(".png")
        manifest = json.loads(objects[0][1])
        assert manifest["artifacts"][-1]["sha256"] == hashlib.sha256(self.raw).hexdigest()
        # The external Reader contract already supports v3 and must read exact bytes.
        path = Path(__file__).resolve().parents[2] / "integrations/evidence/gateway.py"
        spec = importlib.util.spec_from_file_location("graph_reader_contract", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        reader = object.__new__(module.Reader)
        reader.object = dict(objects).__getitem__
        assert reader.read(objects[-1][0]) == self.raw
        assert reader.read(objects[1][0]) == objects[1][1]
        with pytest.raises(Failure, match="GRAPH_REQUIRES_S3"):
            publish_parts(Mock(), 1, result, {}, Mock())

    def test_capture_is_partial_and_honest(self):
        self.event["annotations"]["spi_graphs"] = annotation(
            [graph(), graph(id="missing", variables={"node": {"label": "node"}})]
        )
        captured, missing = graphs.collect(self.event, self.client)
        assert len(captured) == 1
        assert missing == [{"source": "graph:missing", "reason": "MISSING_LABEL"}]

    def test_spec_change_cannot_rewrite_immutable_capture(self):
        graphs.collect(self.event, self.client)
        self.event["annotations"]["spi_graphs"] = annotation([graph(panel_id=13)])
        with pytest.raises(GraphError, match="GRAPH_CHECKPOINT_CONFLICT"):
            graphs.collect(self.event, self.client)

    def test_collection_budget_defers_without_losing_captured_png(self):
        self.event["annotations"]["spi_graphs"] = annotation(
            [graph(), graph(id="context", panel_id=13)]
        )
        now = [0]

        def render(*args, **kwargs):
            now[0] += 10
            return self.raw, validate_png(self.raw)

        self.client.render.side_effect = render
        with patch("graph_evidence.time.monotonic", side_effect=lambda: now[0]):
            with pytest.raises(GraphError, match="GRAPH_CAPTURE_DEFERRED"):
                graphs.collect(self.event, self.client, deadline=10)
            captured, missing = graphs.collect(self.event, self.client, deadline=30)
        assert len(captured) == 2
        assert not missing
        assert self.client.render.call_count == 2

    def test_no_path_traversal_or_symlink(self):
        for ref in (
            {"event_key": "../outside", "render_digest": "a" * 64},
            {"event_key": "a" * 64, "render_digest": "../outside"},
        ):
            with pytest.raises(GraphError):
                graphs.read_artifact(ref)
        captured, _ = graphs.collect(self.event, self.client)
        ref = captured[0]["reference"]
        path = graphs.ARTIFACT_ROOT / ref["event_key"] / (ref["render_digest"] + ".png")
        path.unlink()
        path.symlink_to("/etc/passwd")
        with pytest.raises(OSError):
            graphs.read_artifact(ref)

    def test_tamper_detected_before_s3(self):
        captured, missing = graphs.collect(self.event, self.client)
        bundle = graphs.attach(prepare_bundle(self.event, {}, []), captured, missing)
        ref = captured[0]["reference"]
        path = graphs.ARTIFACT_ROOT / ref["event_key"] / (ref["render_digest"] + ".png")
        path.write_bytes(b"not a png")
        with pytest.raises(Failure, match="STORAGE_INTEGRITY"):
            storage_objects(bundle)


if __name__ == "__main__":
    unittest.main()
