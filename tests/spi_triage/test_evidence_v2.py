"""Tests for the SPI triage evidence pipeline (v2)."""

import json
import sys
import unittest
from pathlib import Path
from typing import TypedDict
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "charts/spi-triage/files"))
from core import Failure, digest
from evidence_bundle import (
    PART_SIZE,
    index_markdown,
    index_marker,
    prepare_bundle,
    publish_parts,
    redact,
)
from provenance import DeploymentCollector
from telemetry import TelemetryCollector, absolute_window, grafana_explore_url
from test_triage import event


class BundleArtifact(TypedDict):
    """Manifest entry describing one bundled artifact."""

    sha256: str
    truncated: bool


class BundleManifest(TypedDict):
    """Manifest listing the artifacts and links of a bundle."""

    artifacts: list[BundleArtifact]
    links: list[dict[str, str]]


class BundlePart(TypedDict):
    """Source excerpt staged into the diagnostic bundle."""

    id: str
    text: str
    marker: str


class Bundle(TypedDict):
    """Diagnostic bundle: manifest plus excerpt parts."""

    manifest: BundleManifest
    parts: list[BundlePart]


class TelemetryArtifact(TypedDict):
    """Telemetry record for one collected artifact."""

    name: str


class TelemetryGap(TypedDict):
    """Reason a telemetry artifact could not be collected."""

    reason: str


class TelemetryResult(TypedDict):
    """Telemetry collection result with artifacts, links and gaps."""

    artifacts: list[TelemetryArtifact]
    links: list[dict[str, object]]
    missing: list[TelemetryGap]


class ArtifactTests(unittest.TestCase):
    """Tests for evidence v2 artifact bundling."""

    def bundle(self, text: str = "diagnostic") -> Bundle:
        """Prepare a fresh evidence bundle with the given text."""
        result: Bundle = prepare_bundle(
            event(),
            {"window": {"start": 1, "end": 2}},
            [{"name": "logs.json", "content": text, "source": {"query": "test"}}],
        )
        return result

    def test_recursive_redaction_keeps_topology(self) -> None:
        """Verify recursive redaction preserves structure while hiding values."""
        raw = {
            "password": "very confidential",
            "token": "abcdef",
            "stack": 'host=10.250.0.1 api_key="two words"\nCookie: foo=bar; session=abc\nAuthorization: Bearer abcdef\npostgres://user:pass@db/foo',
            "pem": "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
            "safe": "socrat-1",
        }
        value = json.dumps(redact(raw))
        assert "two words" not in value
        assert "foo=bar" not in value
        assert "user:pass" not in value
        assert "very confidential" not in value
        assert "10.250.0.1" in value
        assert "socrat-1" in value
        assert "BEGIN RSA" not in value

    def test_known_exact_secret(self) -> None:
        """Verify exact known secrets are replaced deterministically."""
        assert redact("a super-secret-value b", ["super-secret-value"]) == "a [REDACTED] b"

    def test_deterministic_and_manifest(self) -> None:
        """Verify bundle preparation is deterministic and ships a manifest."""
        a = self.bundle()
        assert a == self.bundle()
        assert "sha256" in a["manifest"]["artifacts"][0]
        assert a["parts"][0]["id"] == "MANIFEST"

    def test_explicit_truncation_and_parts(self) -> None:
        """Verify oversized payloads truncate into explicit parts."""
        b = self.bundle("x" * 100000)
        assert b["manifest"]["artifacts"][0]["truncated"]
        assert all(len(x["text"]) <= PART_SIZE for x in b["parts"])

    def test_no_arbitrary_links(self) -> None:
        """Verify bundles cannot smuggle arbitrary external links."""
        b = self.bundle()
        b["manifest"]["links"] = [{"title": "evil", "url": "https://evil.example"}]
        assert "evil" not in index_markdown(b)

    def test_idempotent_parts(self) -> None:
        """Verify part uploads re-run without duplicating artifacts."""
        g = Mock()
        g.comments.return_value = []
        g.request.return_value = {"html_url": "https://github.com/a/b/issues/1#issuecomment-1"}
        b = self.bundle()
        state = {}
        save = Mock()
        publish_parts(g, 9, b, state, save)
        n = g.request.call_count
        publish_parts(g, 9, b, state, save)
        assert g.request.call_count == n

    def test_lost_response_reconciles(self) -> None:
        """Verify a lost upload response reconciles safely."""
        g = Mock()
        g.comments.return_value = []
        g.request.side_effect = Failure("UPSTREAM_TIMEOUT")
        b = self.bundle()
        state = {}
        save = Mock()
        with self.assertRaises(Failure):
            publish_parts(g, 9, b, state, save)
        marker = state["pending"]
        g.comments.return_value = [
            {
                "body": marker,
                "user": {"login": "renamed-socrat[bot]", "type": "Bot"},
                "performed_via_github_app": {"id": 5569869},
                "html_url": "https://github.com/test",
            }
        ]
        g.request.side_effect = None
        g.request.return_value = {"html_url": "https://github.com/test"}
        publish_parts(g, 9, b, state, save)
        assert state["index_done"]
        assert g.request.call_count == len(b["parts"]) + 1

    def test_ambiguous_not_blindly_retried(self) -> None:
        """Verify ambiguous outcomes are not blindly retried."""
        g = Mock()
        g.comments.return_value = []
        g.request.side_effect = Failure("HTTP_500")
        b = self.bundle()
        state = {}
        save = Mock()
        with self.assertRaises(Failure):
            publish_parts(g, 9, b, state, save)
        with self.assertRaisesRegex(Failure, "WRITE_NEEDS_REVIEW"):
            publish_parts(g, 9, b, state, save)
        assert g.request.call_count == 1

    def test_index_ambiguous_reconciles(self) -> None:
        """Verify ambiguous index uploads reconcile to one index."""
        b = self.bundle()
        state = {
            "done": {p["marker"]: "url" for p in b["parts"]},
            "index_pending": True,
        }
        g = Mock()
        g.comments.return_value = [
            {
                "user": {"login": "renamed-socrat[bot]", "type": "Bot"},
                "performed_via_github_app": {"id": 5569869},
                "body": index_marker(b),
            }
        ]
        publish_parts(g, 9, b, state, Mock())
        g.request.assert_not_called()

    def test_rate_limit_is_retryable_without_ambiguous_intent(self) -> None:
        """Verify rate limits retry without double-declaring intent."""
        g = Mock()
        g.comments.return_value = []
        g.request.side_effect = Failure("HTTP_429")
        progress = {}
        with self.assertRaises(Failure):
            publish_parts(g, 9, self.bundle(), progress, Mock())
        assert "pending" not in progress

    def test_untrusted_marker_cannot_hide_missing_artifact(self) -> None:
        """Verify untrusted markers cannot mask missing artifacts."""
        b = self.bundle()
        g = Mock()
        g.comments.return_value = [{"body": b["parts"][0]["marker"], "user": {"login": "unknown"}}]
        g.request.return_value = {}
        publish_parts(g, 9, b, {}, Mock())
        assert g.request.call_count == len(b["parts"]) + 1

    def test_fence_injection_remains_data(self) -> None:
        """Verify injected code fences stay inert data."""
        b = self.bundle("```\nmalicious\n````")
        g = Mock()
        g.comments.return_value = []
        g.request.return_value = {}
        publish_parts(g, 9, b, {}, Mock())
        assert "````text" in g.request.call_args_list[1].args[2]["body"]
        assert "\\u0060" in g.request.call_args_list[1].args[2]["body"]


class TelemetryTests(unittest.TestCase):
    """Tests for evidence upload telemetry."""

    def response(self, method: str, url: str, *args: object, **kw: object) -> dict[str, object]:
        """Script the Grafana API responses and record calls."""
        if "/api/search?" in url:
            return {"traces": [{"traceID": "a" * 32}]}
        if "/api/traces/" in url:
            return {
                "resourceSpans": [
                    {
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "traceId": "a" * 32,
                                        "spanId": "b" * 16,
                                        "name": "request",
                                        "status": {"code": 2},
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        if "/query_range?" in url:
            return {
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {
                            "stream": {"pod": "test"},
                            "values": [["1793710800000000000", "error trace_id=" + "a" * 32]],
                        }
                    ],
                },
            }
        return {"data": {"result": []}}

    def collect(self, labels: dict[str, str] | None = None) -> tuple[Mock, TelemetryResult]:
        """Run discovery with the given labels and return host and result."""
        h = Mock()
        h.request.side_effect = self.response
        e = event()
        e["labels"].update(labels or {})
        with patch("telemetry.time.time", return_value=1793711400):
            r = TelemetryCollector(h, "http://grafana", "fake").collect(e, {})
        return h, r

    def test_log_trace_discovery_and_bounds(self) -> None:
        """Verify log and trace discovery stays within bounds."""
        h, r = self.collect({"pod": "test-pod", "service": "test"})
        assert any("tempo-trace" in a["name"] for a in r["artifacts"])
        assert h.request.call_count <= 10
        assert r["links"]

    def test_unsafe_pod_does_not_widen(self) -> None:
        """Verify unsafe label values cannot widen discovery."""
        h, r = self.collect({"pod": 'bad"} |= "secret'})
        assert not any("/query_range?" in x.args[1] for x in h.request.call_args_list)
        assert any(x["reason"] == "UNSAFE_LABEL" for x in r["missing"])

    def test_links_absolute_decodable(self) -> None:
        """Verify generated links are absolute and round-trip decodable."""
        url = grafana_explore_url(
            "https://grafana.socrat.alchemmist.xyz",
            "prometheus",
            'up{job="x"}',
            10,
            20,
            "expr",
        )
        q = parse_qs(urlsplit(url).query)
        pane = json.loads(q["panes"][0])["spi"]
        assert pane["range"] == {"from": "10000", "to": "20000"}
        assert pane["queries"][0]["expr"] == 'up{job="x"}'

    def test_window_capping(self) -> None:
        """Verify the absolute time window is capped at the maximum."""
        w = absolute_window("2026-11-03T00:00:00Z", None, 1793711400)
        assert w["end"] - w["start"] <= 3600
        assert w["span_capped"]

    def test_failed_source_not_empty_success(self) -> None:
        """Verify a failed source is reported, not treated as success."""
        h = Mock()
        h.request.side_effect = Failure("HTTP_403")
        with patch("telemetry.time.time", return_value=1793711400):
            r = TelemetryCollector(h, "http://grafana", "fake").collect(event(), {})
        assert any(x["reason"] == "HTTP_403" for x in r["missing"])

    def test_trace_exception_events_and_resource_version(self) -> None:
        """Verify trace projection events and resource versions."""
        from telemetry import _project_trace

        raw = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [{"key": "service.version", "value": {"stringValue": "v1.2"}}]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "a" * 32,
                                    "events": [
                                        {
                                            "name": "exception",
                                            "attributes": [
                                                {
                                                    "key": "exception.stacktrace",
                                                    "value": {
                                                        "stringValue": "Traceback: real error"
                                                    },
                                                },
                                                {
                                                    "key": "password",
                                                    "value": {"stringValue": "hidden"},
                                                },
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        value = _project_trace(raw, "a" * 32)
        assert value["spans"][0]["resource_context"]["service.version"] == "v1.2"
        assert "Traceback: real error" in json.dumps(value)
        assert "hidden" not in json.dumps(value)

    def test_no_data_explicit(self) -> None:
        """Verify absent telemetry is reported explicitly."""
        h = Mock()
        h.request.return_value = {
            "status": "success",
            "data": {"resultType": "streams", "result": []},
        }
        with patch("telemetry.time.time", return_value=1793711400):
            r = TelemetryCollector(h, "http://grafana", "fake").collect(event(), {})
        assert any(x["reason"] == "NO_MATCHING_LINES" for x in r["missing"])


class ProvenanceTests(unittest.TestCase):
    """Tests for evidence provenance boundaries."""

    def test_project_does_not_export_env_or_secret(self) -> None:
        """Verify the projection exports no environment or secret values."""
        obj = {
            "kind": "Pod",
            "metadata": {"name": "test", "annotations": {"secret": "hidden"}},
            "spec": {
                "containers": [
                    {
                        "name": "app",
                        "image": "image:tag",
                        "env": [{"name": "PASSWORD", "value": "hidden"}],
                    }
                ]
            },
            "status": {
                "containerStatuses": [
                    {
                        "name": "app",
                        "imageID": "containerd://sha256:" + "a" * 64,
                        "state": {"terminated": {"exitCode": 1, "message": "hidden"}},
                    }
                ]
            },
        }
        data = DeploymentCollector.project(obj)
        assert "hidden" not in json.dumps(data)
        assert "imageID" in json.dumps(data)

    def test_owner_chain_and_digest(self) -> None:
        """Verify owner chains and digests are computed correctly."""
        reader = Mock()
        reader.side_effect = [
            {
                "kind": "Pod",
                "metadata": {
                    "name": "pod",
                    "ownerReferences": [{"kind": "ReplicaSet", "name": "rs"}],
                },
                "status": {"containerStatuses": [{"name": "app", "imageID": "digest"}]},
                "spec": {"containers": [{"name": "app", "image": "img"}]},
            },
            {
                "kind": "ReplicaSet",
                "metadata": {
                    "name": "rs",
                    "ownerReferences": [{"kind": "Deployment", "name": "dep"}],
                },
            },
            {
                "kind": "Deployment",
                "metadata": {
                    "name": "dep",
                    "annotations": {"deployment.kubernetes.io/revision": "3"},
                },
            },
        ]
        e = event()
        e["labels"]["pod"] = "pod"
        r = DeploymentCollector(reader=reader).collect(e)
        assert reader.call_count == 3
        assert len(r["artifacts"][0]["content"]["workloads"][0]["owner_chain"]) == 2

    def test_invalid_scope_no_read(self) -> None:
        """Verify invalid scopes never issue reads."""
        reader = Mock()
        e = event()
        e["labels"]["namespace"] = "../secrets"
        r = DeploymentCollector(reader=reader).collect(e)
        reader.assert_not_called()
        assert r["missing"][0]["reason"] == "INVALID_WORKLOAD_SCOPE"

    def test_systemd_not_exporter_pod(self) -> None:
        """Verify systemd units are never misread as exporter pods."""
        reader = Mock()
        e = event()
        e["labels"]["name"] = "otel.service"
        DeploymentCollector(reader=reader).collect(e)
        reader.assert_not_called()

    def test_immutable_gitops_digest_mapping(self) -> None:
        """Verify the gitops digest mapping is immutable."""
        import base64

        digest = "sha256:" + "b" * 64
        revision = "c" * 40
        ref = "d" * 40
        text = (
            "image:\n  repository: harbor.socrat.alchemmist.xyz/homelab/socrat-bot\n  tag: "
            + revision
            + "\n  digest: "
            + digest
            + "\n"
        )
        g = Mock()
        g.request.side_effect = [
            [{"sha": ref}],
            {
                "encoding": "base64",
                "size": len(text),
                "content": base64.b64encode(text.encode()).decode(),
            },
        ]
        h = Mock()
        h.request.return_value = {"sha": revision}
        r = DeploymentCollector(h, g).gitops_source(
            "homelab/socrat-bot",
            {
                "image": "harbor.socrat.alchemmist.xyz/homelab/socrat-bot@" + digest,
                "imageID": "child-digest",
            },
        )
        assert r["content"]["declared_source_revision"] == revision
        assert not r["content"]["source_equivalence_proven"]
        assert ref in r["content"]["release_manifest_url"]

    def test_different_digest_cannot_claim_main_is_deployed(self) -> None:
        """Verify a differing digest cannot claim main is deployed."""
        import base64

        text = (
            "image:\n  repository: harbor.socrat.alchemmist.xyz/homelab/socrat-bot\n  tag: "
            + "c" * 40
            + "\n  digest: sha256:"
            + "d" * 64
            + "\n"
        )
        g = Mock()
        g.request.side_effect = [
            [{"sha": "e" * 40}],
            {
                "encoding": "base64",
                "size": len(text),
                "content": base64.b64encode(text.encode()).decode(),
            },
        ]
        h = Mock()
        r = DeploymentCollector(h, g).gitops_source(
            "homelab/socrat-bot",
            {"image": "harbor.socrat.alchemmist.xyz/homelab/socrat-bot@sha256:" + "b" * 64},
        )
        assert r is None
        h.request.assert_not_called()

    def test_source_excerpt_is_pinned_and_traversal_rejected(self) -> None:
        """Verify source excerpts are pinned and traversals are rejected."""
        import base64

        ref = "c" * 40
        h = Mock()
        h.request.return_value = {
            "encoding": "base64",
            "size": 20,
            "content": base64.b64encode(b"line one\nline two").decode(),
            "sha": "blob",
        }
        proof = {
            "artifacts": [
                {
                    "name": "deployed-source-gitops.json",
                    "content": {
                        "declared_source_revision": ref,
                        "source_commit_url": "https://github.com/alchemmist/socrat-bot/tree/" + ref,
                    },
                }
            ]
        }
        r = DeploymentCollector(h).source_fragments(
            proof,
            {
                "artifacts": [
                    {"content": "File /app/socrat_bot/main.py, line 2; socrat_bot/../secret.py"}
                ]
            },
        )
        assert h.request.call_count == 1
        assert "?ref=" + ref in h.request.call_args.args[1]
        assert "line two" in r["artifacts"][0]["content"]["excerpt"]

    def test_absent_identity_explicit(self) -> None:
        """Verify absent identities are reported explicitly."""
        e = event()
        e["labels"]["pod"] = "app"
        with patch("provenance.ROOT", Path("/nonexistent")):
            r = DeploymentCollector().collect(e)
        assert r["missing"][0]["reason"] == "KUBERNETES_READ_IDENTITY_MISSING"


class EngineArtifactTests(unittest.TestCase):
    """Tests for engine artifact timeout handling."""

    def test_primary_is_not_repeated_after_artifact_timeout(self) -> None:
        """Verify primaries are not repeated after an artifact timeout."""
        import tempfile

        from core import Store
        from service import Engine
        from test_triage import report

        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "db")
            g = Mock()
            g.snapshot.return_value = []
            g.open_signature.return_value = digest([])
            g.comments.return_value = []
            g.request.side_effect = [{"number": 9}, Failure("UPSTREAM_TIMEOUT")]
            model = Mock()
            model.match.return_value = {"candidates": []}
            model.analyze.return_value = report()
            evidence = Mock()
            e = event()
            bundle = prepare_bundle(
                e,
                {},
                [{"name": "test.json", "content": {"observation": "real fixture"}}],
            )
            evidence.collect.return_value = {"bundle": bundle}
            engine = Engine(store, g, model, evidence, write=True)
            store.enqueue(e)
            key = store.claim()["job_id"]
            for stage in ("match", "collect", "analyze"):
                engine.run(stage, key)
            with self.assertRaises(Failure):
                engine.run("publish", key)
            saved = store.get(key)
            marker = saved["result"]["artifact_publication"]["pending"]
            assert json.loads(saved["intent"])["primary_done"]
            g.comments.return_value = [
                {
                    "body": marker,
                    "user": {"login": "renamed-socrat[bot]", "type": "Bot"},
                    "performed_via_github_app": {"id": 5569869},
                    "html_url": "https://github.com/comment",
                }
            ]
            g.request.side_effect = None
            g.request.return_value = {"html_url": "https://github.com/comment"}
            with store.db() as c:
                c.execute("UPDATE jobs SET available=0,lease=0")
            store.claim()
            engine.run("publish", key)
            assert store.get(key)["state"] == "complete"
            g.reconcile.assert_not_called()
            assert sum(x.args[1] == "/issues" for x in g.request.call_args_list) == 1


class DownloadTests(unittest.TestCase):
    """Tests for evidence downloads and checksums."""

    def test_roundtrip_and_checksum(self) -> None:
        """Verify content round-trips with a matching checksum."""
        import importlib.util

        path = Path(__file__).resolve().parents[2] / "scripts/n8n/download_spi_evidence.py"
        spec = importlib.util.spec_from_file_location("spi_download", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        e = event()
        bundle = prepare_bundle(
            e, {}, [{"name": "logs.json", "content": "line one\nline two ` data"}]
        )
        g = Mock()
        g.comments.return_value = []
        g.request.return_value = {"html_url": "https://github.com/comment"}
        publish_parts(g, 9, bundle, {}, Mock())
        comments = [
            {
                "body": x.args[2]["body"],
                "user": {"login": "renamed-socrat[bot]", "type": "Bot"},
                "performed_via_github_app": {"id": 5569869},
            }
            for x in g.request.call_args_list
        ]
        files = module.reconstruct(comments, e["event_key"])
        assert json.loads(files["E001-logs.json"]) == "line one\nline two ` data"
        comments[1]["body"] = comments[1]["body"].replace("line one", "tampered")
        with self.assertRaisesRegex(ValueError, "CHECKSUM"):
            module.reconstruct(comments, e["event_key"])

    def test_primary_and_all_parts_have_bounded_bodies(self) -> None:
        """Verify primaries and parts keep bounded bodies."""
        bundle = prepare_bundle(event(), {}, [{"name": "test.json", "content": "`" * 100000}])
        g = Mock()
        g.comments.return_value = []
        g.request.return_value = {}
        publish_parts(g, 9, bundle, {}, Mock())
        assert all(len(x.args[2]["body"]) < 65536 for x in g.request.call_args_list)


class ModelEvidenceTests(unittest.TestCase):
    """Tests for model evidence fact validation."""

    def test_facts_require_valid_existing_evidence_ids(self) -> None:
        """Verify facts must reference valid existing evidence ids."""
        import time

        from core import REPORT_SCHEMA
        from integrations import Model
        from test_triage import report

        bad = report()
        bad["facts"] = ["A guessed fact [E999]"]
        good = report()
        good["facts"] = ["An alert fired [E001]"]
        h = Mock()
        h.request.side_effect = [
            {"choices": [{"message": {"content": json.dumps(bad)}}]},
            {"choices": [{"message": {"content": json.dumps(good)}}]},
        ]
        result = Model(h, "fake", min_interval=0, store=Mock()).call(
            "analyze",
            {"evidence": {"artifact_context": {"index": [{"id": "E001"}]}}},
            REPORT_SCHEMA,
            time.monotonic() + 20,
        )
        assert result == good
        assert h.request.call_count == 2


class PrimaryReconciliationTests(unittest.TestCase):
    """Tests for primary issue reconciliation."""

    def test_issue_without_app_metadata_uses_immutable_bot_id(self) -> None:
        """Verify issues lacking app metadata fall back to the bot id."""
        from evidence_bundle import trusted_comment

        assert trusted_comment({"user": {"id": 351189559, "type": "Bot", "login": "renamed"}})
        assert not trusted_comment({"user": {"id": 123, "type": "Bot", "login": "socrat-bot[bot]"}})

    def test_primary_marker_requires_actual_app_author(self) -> None:
        """Verify primary markers require the actual app author."""
        from integrations import GitHub

        g = GitHub(Mock(), "/unused")
        g.comments = Mock(return_value=[{"body": "marker", "user": {"type": "User"}}])
        assert g.reconcile("marker", 9) == 0
        g.comments.return_value = [
            {
                "body": "marker",
                "user": {"type": "Bot"},
                "performed_via_github_app": {"id": 5569869},
            }
        ]
        assert g.reconcile("marker", 9) == 9


class SQLiteTempStoreTests(unittest.TestCase):
    """Tests that SQLite uses an in-memory temp store."""

    def test_all_connections_use_memory_temp_store(self) -> None:
        """Verify every connection uses an in-memory temp store."""
        import tempfile

        from core import Store

        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "db")
            with store.db() as c:
                assert c.execute("pragma temp_store").fetchone()[0] == 2
            store.enqueue(event())
            store.claim()
            assert store.recover_on_start() == 1
            assert store.health()["counts"].get("retry") == 1


if __name__ == "__main__":
    unittest.main()


class GrafanaLoginLinkTests(unittest.TestCase):
    """Tests for generated Grafana login links."""

    def test_generator_requests_native_login_and_keeps_absolute_state(self) -> None:
        """Verify the login generator keeps absolute state per identity."""
        for uid, field, query in [
            ("prometheus", "expr", 'up{job="x"}'),
            ("loki", "expr", '{unit="a.service"} |= "error"'),
            ("tempo", "query", '{resource.service.name="socrat-bot"}'),
        ]:
            url = grafana_explore_url(
                "https://grafana.socrat.alchemmist.xyz", uid, query, 10, 20, field
            )
            params = parse_qs(urlsplit(url).query)
            assert params["forceLogin"] == ["true"]
            assert url.endswith("&forceLogin=true")
            pane = json.loads(params["panes"][0])["spi"]
            assert pane["queries"][0][field] == query
            assert pane["range"] == {"from": "10000", "to": "20000"}

    def test_cached_manifest_is_not_mutated(self) -> None:
        """Verify cached manifests are never mutated."""
        b = ArtifactTests().bundle()
        old = grafana_explore_url(
            "https://grafana.socrat.alchemmist.xyz", "tempo", "a" * 32, 10, 20, "query"
        ).replace("&forceLogin=true", "")
        b["manifest"]["links"] = [{"title": "Trace", "url": old}]
        from copy import deepcopy

        snapshot = deepcopy(b)
        assert "forceLogin=true" in index_markdown(b)
        assert b == snapshot

    def test_repair_is_idempotent_and_does_not_touch_artifact_json(self) -> None:
        """Verify link repair is idempotent and leaves artifact JSON alone."""
        from grafana_links import repair_markdown_links

        url = grafana_explore_url(
            "https://grafana.socrat.alchemmist.xyz",
            "loki",
            '{pod="test"}',
            10,
            20,
            "expr",
        ).replace("&forceLogin=true", "")
        body = "[Logs](" + url + ")\n```json\n" + json.dumps({"original_url": url}) + "\n```"
        repaired = repair_markdown_links(body)
        assert repaired == repair_markdown_links(repaired)
        assert json.dumps({"original_url": url}) in repaired
        assert "[Logs](" + url + "&forceLogin=true)" in repaired

    def test_external_origin_unchanged_and_duplicate_flags_removed(self) -> None:
        """Verify external origins stay unchanged and duplicate flags drop."""
        from grafana_links import require_explore_login

        evil = "https://grafana.socrat.alchemmist.xyz.evil.example/explore?forceLogin=false"
        assert require_explore_login(evil) == evil
        url = (
            "https://grafana.socrat.alchemmist.xyz/explore?orgId=1&forceLogin=false&forceLogin=true"
        )
        assert parse_qs(urlsplit(require_explore_login(url)).query)["forceLogin"] == ["true"]
