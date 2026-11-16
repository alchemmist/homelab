"""Offline adversarial contracts for repository CI; no production commands."""

import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/quality"))
from common import finding, report, unique, failure
import charts
import contracts


def test_semantic_ids_survive_line_movement_and_do_not_store_source():
    a = finding("RULE", "tests/test_quality_system.py", 1, "message", "same semantic context")
    b = finding("RULE", "tests/test_quality_system.py", 2, "message", "same semantic context")
    assert a["id"] == b["id"]
    assert "same semantic context" not in json.dumps(a)
    assert len({f["id"] for f in unique([a, b])}) == 2


def test_escaping_finding_rejected():
    with pytest.raises(ValueError):
        finding("RULE", "../private", 1, "message", "context")


def test_failed_tools_are_not_quality_approvals(tmp_path):
    out = tmp_path / "result.json"
    failure(out, RuntimeError("DO NOT ECHO SECRET PAYLOAD"))
    value = json.loads(out.read_text())
    assert value["failureKind"] == "command"
    assert "SECRET PAYLOAD" not in out.read_text()


def test_ci_cannot_automatically_record_debt(tmp_path, monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(ValueError):
        report(
            "test",
            [],
            1,
            tmp_path / "report.json",
            record_reason="A sufficiently long review reason",
        )


def test_new_findings_fail_and_resolved_debt_does_not_hide_them(tmp_path):
    f = finding("RULE", "tests/test_quality_system.py", 1, "message", "new context")
    with patch("common.ROOT", tmp_path):
        assert report("test", [f], 1, tmp_path / "out.json")
        assert json.loads((tmp_path / "out.json").read_text())["failureKind"] == "quality"


def test_chart_registry_covers_all_local_roots_and_consumed_values():
    values = charts.targets()
    assert len(values) >= 58
    assert len({v["id"] for v in values}) == len(values)
    wishlist = next(v for v in values if v["id"] == "wishlist-0")
    assert wishlist["values"] == [ROOT / "deploy/wishlist/values.yaml"]
    for value in values:
        assert value["chart"].is_relative_to(ROOT)
        assert "kubectl" not in charts.arguments(value)


def test_unknown_helm_override_cannot_silently_disappear():
    with pytest.raises(ValueError):
        charts.local_path("../outside-repo")


def test_resource_security_rules_do_not_mutate_intent():
    workload = {
        "kind": "Deployment",
        "spec": {
            "template": {
                "spec": {
                    "hostNetwork": True,
                    "containers": [
                        {
                            "name": "test",
                            "image": "example:latest",
                            "securityContext": {"privileged": True},
                        }
                    ],
                }
            }
        },
    }
    before = json.dumps(workload)
    rules = {r for r, _ in charts.policies(workload)}
    assert "image-digest" in rules
    assert (
        "pv-retain",
        "Persistent data volume does not explicitly retain data",
    ) in charts.policies(
        {
            "kind": "PersistentVolume",
            "spec": {"persistentVolumeReclaimPolicy": "Delete"},
        }
    )
    assert json.dumps(workload) == before


def test_real_quality_integrity():
    contracts.check()


def test_duplicate_rendered_keys_are_rejected():
    import yaml

    with pytest.raises(yaml.YAMLError):
        yaml.load("metadata: {name: first, name: second}", Loader=charts.ManifestLoader)  # noqa: S506 -- subclass of SafeLoader, rejects duplicate keys


def test_scalar_equals_is_valid_kubernetes_yaml():
    import yaml

    assert yaml.load("expr: =", Loader=charts.ManifestLoader) == {"expr": "="}  # noqa: S506 -- SafeLoader subclass


def test_installer_rejects_escaping_binary_name(tmp_path):
    import install_tools

    with pytest.raises(ValueError):
        install_tools.install({"name": "../escape"}, tmp_path)


def test_native_producer_payload_matches_released_quality_graph_schema(tmp_path):
    import jsonschema
    from common import command

    output = tmp_path / "producer.json"
    report("fixture", [], 1, output)
    schema = json.loads(command(["qg", "result", "schema", "--producer"]).stdout)
    jsonschema.validate(json.loads(output.read_text()), schema)
    failure(output, ValueError("sensitive input must never be rendered"))
    jsonschema.validate(json.loads(output.read_text()), schema)


def test_manifest_validation_is_not_artificially_sharded():
    import inspect

    assert list(inspect.signature(charts.check).parameters) == ["validate"]


def test_helm_parameters_cannot_inject_a_post_renderer():
    target = {
        "release": "safe-release",
        "namespace": "default",
        "values": [],
        "parameters": [{"name": "--post-renderer", "value": "/unsafe"}],
    }
    with pytest.raises(ValueError):
        charts.arguments(target)


def test_network_namespace_preserves_locked_tool_path(tmp_path, monkeypatch):
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location(
        "quality_test_runner", ROOT / "scripts/quality/tests.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/test-suites.json").write_text(
        json.dumps({"suites": {"fixture": ["tests/test_fixture.py"]}})
    )
    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runner.getpass, "getuser", lambda: "runner")
    monkeypatch.setattr(sys, "argv", ["tests.py", "fixture", "--isolate-network"])
    monkeypatch.setenv("PATH", "/locked-venv/bin:/usr/bin")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/must-not-leak")
    calls = []
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda argv, **kw: calls.append((argv, kw)) or SimpleNamespace(returncode=0),
    )
    assert runner.main() == 0
    argv, kw = calls[0]
    assert "PATH=/locked-venv/bin:/usr/bin" in argv
    assert "SSH_AUTH_SOCK" not in kw["env"]
    assert argv[:4] == ["sudo", "-n", "unshare", "--net"]


@pytest.mark.parametrize(
    "image", ["example:latest", "example@sha256:short", "example@sha256:not-a-digest"]
)
def test_image_digest_must_be_real_sha256_shape(image):
    resource = {"kind": "Pod", "spec": {"containers": [{"name": "test", "image": image}]}}
    assert any(rule == "image-digest" for rule, _ in charts.policies(resource))
    resource["spec"]["containers"][0]["image"] = "example@sha256:" + "a" * 64
    assert not charts.policies(resource)


def test_dependency_audit_uses_installed_environment_and_deduplicates(monkeypatch):
    from types import SimpleNamespace
    import lint

    calls = []
    item = {"name": "fixture", "version": "1", "vulns": [{"id": "CVE-2026-1234"}]}

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=json.dumps({"dependencies": [item, item]}))

    monkeypatch.setattr(lint, "command", run)
    findings, _ = lint.check("dependencies")
    assert len(findings) == 1
    assert "--no-deps" not in calls[0]
    assert "--disable-pip" not in calls[0]
    assert "--local" in calls[0]


def test_nonsecret_tokenizer_exception_cannot_hide_other_values(tmp_path, monkeypatch):
    import lint

    p = tmp_path / "services/spi-tokenizer/Dockerfile"
    p.parent.mkdir(parents=True)
    p.write_text("ENV TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1 PYTHONPATH=/app")
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    item = {"code": "DL3064", "line": 1}
    assert lint.nonsecret_tokenizer_option("services/spi-tokenizer/Dockerfile", item)
    p.write_text("ENV TOKENIZERS_PARALLELISM=credential")
    assert not lint.nonsecret_tokenizer_option("services/spi-tokenizer/Dockerfile", item)


def test_graph_is_cost_layered_and_titles_are_semantic():
    import yaml

    graph = yaml.safe_load((ROOT / "qg.yaml").read_text())["nodes"]
    assert len({n["title"] for n in graph.values()}) == len(graph)
    cheap = {"python", "yaml", "shell", "workflow", "secrets", "docker", "javascript", "tests-fast"}
    for node in cheap:
        assert graph[node]["needs"] == ["graph"]
    for node in ("ownership", "manifests", "ansible", "tests-medium", "dependencies"):
        assert set(graph[node]["needs"]) == cheap
    assert set(graph["tests-cluster"]["needs"]) == {
        "ownership",
        "manifests",
        "ansible",
        "tests-medium",
        "dependencies",
    }
    assert not any("shard" in n for n in graph)
