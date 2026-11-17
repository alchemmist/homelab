"""Offline adversarial contracts for repository CI; no production commands."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
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


def test_recorded_debt_identity_cannot_mark_a_finding_passed(tmp_path):
    f = finding("RULE", "tests/test_quality_system.py", 1, "message", "visible context")
    debt = tmp_path / "quality/debt"
    debt.mkdir(parents=True)
    (debt / "python.json").write_text(
        json.dumps(
            {
                "version": 1,
                "acceptance": False,
                "reason": "Historical entries stay visible and cannot pass.",
                "findings": [
                    {
                        "id": f["id"],
                        "path": "tests/test_quality_system.py",
                        "rule": "RULE",
                    }
                ],
            }
        )
    )
    with patch("common.ROOT", tmp_path):
        assert report("python", [f], 1, tmp_path / "out.json")
        payload = json.loads((tmp_path / "out.json").read_text())
        assert payload["status"] == "failed"
        assert payload["findings"][0]["id"] == f["id"] + ".1"


def test_unmarked_debt_file_cannot_act_as_a_baseline(tmp_path):
    debt = tmp_path / "quality/debt"
    debt.mkdir(parents=True)
    (debt / "python.json").write_text(
        json.dumps({"version": 1, "reason": "x" * 20, "findings": []})
    )
    with patch("common.ROOT", tmp_path):
        with pytest.raises(ValueError, match="non-accepting"):
            report("python", [], 1, tmp_path / "out.json")


def test_suppression_guard_matches_markers_and_not_its_own_source():
    import strict_guard

    assert strict_guard.line_is_suppression("value  # " + "noqa: S101")
    assert strict_guard.line_is_suppression("shellcheck " + "disable=SC2086")
    assert not strict_guard.line_is_suppression("process_cpu:cpu:nanoseconds")
    text = Path(strict_guard.__file__).read_text().splitlines()
    assert not any(strict_guard.line_is_suppression(line) for line in text)


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
    assert set(graph["ownership"]["needs"]) == cheap
    for node in ("manifests", "ansible", "tests-medium", "dependencies"):
        assert graph[node]["needs"] == ["ownership"]
    assert set(graph["tests-cluster"]["needs"]) == {
        "manifests",
        "ansible",
        "tests-medium",
        "dependencies",
    }
    assert not any("shard" in n for n in graph)


def _load_checker(name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _infra_files():
    contract = json.loads((ROOT / "deploy/contracts/infrastructure.json").read_text())
    names = [
        "deploy/contracts/infrastructure.json",
        contract["meshRegistry"],
        contract["ansibleInventory"],
    ]
    relay = contract["relayContract"]
    for key in (
        "relayScript",
        "endpointScript",
        "frontHostVars",
        "targetHostVars",
        "serviceFile",
        "installPlaybook",
    ):
        names.append(relay[key])
    for consumer in contract["issuerTransport"]["consumers"]:
        names.append(consumer["file"])
    return names


def _copy_rels(tmp_path, names):
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)


def test_new_issuer_alias_is_invisible_to_the_registered_list(tmp_path):
    """A new alias must fail even when every previously registered consumer still matches."""
    import boundaries

    infra = _load_checker("check_infrastructure_contracts.py")
    _copy_rels(tmp_path, _infra_files())
    rogue = tmp_path / "deploy/new-issuer-consumer/values.yaml"
    rogue.parent.mkdir(parents=True)
    rogue.write_text(
        "hostAliases:\n  - ip: 10.43.218.222\n    hostnames: [auth.socrat.alchemmist.xyz]\n"
    )
    assert infra.check(tmp_path) == 9
    with pytest.raises(ValueError, match="Unregistered issuer transport consumer"):
        boundaries.check(tmp_path)


def test_mesh_address_drift_fails_the_inventory_contract(tmp_path):
    """Changing a mesh address without the inventory is a boundary failure."""
    import yaml

    infra = _load_checker("check_infrastructure_contracts.py")
    _copy_rels(tmp_path, _infra_files())
    contract = json.loads((tmp_path / "deploy/contracts/infrastructure.json").read_text())
    mesh_path = tmp_path / contract["meshRegistry"]
    text = mesh_path.read_text()
    mesh = yaml.safe_load(text)["wg_socrat_nodes"]
    reserved = set(contract["sshEndpointFromPublicPeer"]) | {
        contract["relayContract"][key] for key in ("frontNode", "clientNode", "targetNode")
    }
    name = next(node for node in mesh if node not in reserved and text.count(str(mesh[node]["address"])) == 1)
    old = str(mesh[name]["address"])
    mesh_path.write_text(text.replace(old, "203.0.113.10", 1))
    with pytest.raises(ValueError, match="drift"):
        infra.check(tmp_path)


def test_relay_lan_target_drift_fails(tmp_path):
    """The relay target must stay on the canonical mesh address, not a substituted LAN value."""
    import yaml

    infra = _load_checker("check_infrastructure_contracts.py")
    _copy_rels(tmp_path, _infra_files())
    contract = json.loads((tmp_path / "deploy/contracts/infrastructure.json").read_text())
    path = tmp_path / contract["relayContract"]["targetHostVars"]
    text = path.read_text()
    old = str(yaml.safe_load(text)["homelab_ssh_private_host"])
    assert text.count(old) == 1
    path.write_text(text.replace(old, "203.0.113.20", 1))
    with pytest.raises(ValueError, match="relay"):
        infra.check(tmp_path)


def test_duplicate_issuer_alias_fails(tmp_path):
    """A second issuer alias inside a registered consumer is still a scope failure."""
    import yaml

    infra = _load_checker("check_infrastructure_contracts.py")
    _copy_rels(tmp_path, _infra_files())
    path = tmp_path / "deploy/lms/values.yaml"
    value = yaml.safe_load(path.read_text())
    value["hostAliases"].append(dict(value["hostAliases"][0]))
    path.write_text(yaml.safe_dump(value))
    with pytest.raises(ValueError, match="issuer alias"):
        infra.check(tmp_path)


def _pointer_fixture(tmp_path, document):
    import yaml

    chart = tmp_path / "charts/demo"
    chart.mkdir(parents=True)
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: demo\nversion: 0.0.0\n")
    (chart / "values.yaml").write_text("image: demo-image-1\n")
    apps = tmp_path / "deploy/argocd/apps"
    apps.mkdir(parents=True)
    app = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": "demo", "namespace": "argocd"},
        "spec": {
            "source": {
                "repoURL": "https://example.invalid/repo.git",
                "path": "charts/demo",
                "targetRevision": "main",
            }
        },
    }
    (apps / "demo.yaml").write_text(yaml.safe_dump(app))
    root_app = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": "root", "namespace": "argocd"},
        "spec": {
            "source": {
                "repoURL": "https://example.invalid/repo.git",
                "path": "deploy/argocd/apps",
                "targetRevision": "main",
            }
        },
    }
    (tmp_path / "deploy/argocd/root.yaml").write_text(yaml.safe_dump(root_app))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/demo.md").write_text(document)
    contract = {
        "schemaVersion": 1,
        "repoURL": "https://example.invalid/repo.git",
        "applicationDirectory": "deploy/argocd/apps",
        "rootApplication": "deploy/argocd/root.yaml",
        "documents": ["docs/demo.md"],
        "currentValues": [
            {
                "source": "charts/demo/values.yaml",
                "application": "demo",
                "path": ["image"],
                "documents": ["docs/demo.md"],
            }
        ],
    }
    (tmp_path / "deploy/contracts").mkdir()
    (tmp_path / "deploy/contracts/source-pointers.json").write_text(json.dumps(contract))


def test_duplicate_application_owner_fails(tmp_path):
    """Two Application manifests with one identity are competing deployment owners."""
    import yaml

    pointers = _load_checker("check_source_pointers.py")
    _pointer_fixture(tmp_path, "Current image is `demo-image-1`.\n")
    first = yaml.safe_load((tmp_path / "deploy/argocd/apps/demo.yaml").read_text())
    (tmp_path / "deploy/argocd/apps/demo-copy.yaml").write_text(yaml.safe_dump(first))
    with pytest.raises(ValueError, match="Duplicate Application identity"):
        pointers.check(tmp_path)


def test_authoritative_claim_drift_fails(tmp_path):
    """Documentation that drops the current value is not an authoritative claim."""
    pointers = _load_checker("check_source_pointers.py")
    _pointer_fixture(tmp_path, "Current image is `demo-image-1`.\n")
    assert pointers.check(tmp_path)[0] == 1
    (tmp_path / "docs/demo.md").write_text("Current image was removed.\n")
    with pytest.raises(ValueError, match="Current documentation value drift"):
        pointers.check(tmp_path)


def _retired_play():
    return [
        {
            "name": "Refuse competing provisioning",
            "hosts": "localhost",
            "gather_facts": False,
            "become": False,
            "any_errors_fatal": True,
            "tasks": [
                {
                    "name": "Stop",
                    "ansible.builtin.fail": {"msg": "owned by deploy/argocd/apps/demo.yaml"},
                    "tags": ["always"],
                }
            ],
        }
    ]


def _entrypoint_fixture(tmp_path):
    import yaml

    app = tmp_path / "deploy/argocd/apps/demo.yaml"
    app.parent.mkdir(parents=True)
    app.write_text("kind: Application\n")
    play = tmp_path / "ansible/playbooks/retired.yml"
    play.parent.mkdir(parents=True)
    play.write_text(yaml.safe_dump(_retired_play()))
    contract = {
        "schemaVersion": 1,
        "entries": [
            {
                "path": "ansible/playbooks/retired.yml",
                "status": "retired",
                "reason": "fixture refuses competing provisioning",
                "owners": ["demo"],
            }
        ],
    }
    (tmp_path / "deploy/contracts").mkdir(parents=True)
    (tmp_path / "deploy/contracts/operational-entrypoints.json").write_text(json.dumps(contract))


def test_unclassified_helm_provisioning_fails(tmp_path):
    """A new literal Helm entrypoint is competing provisioning until it is classified."""
    ops = _load_checker("check_operational_entrypoints.py")
    _entrypoint_fixture(tmp_path)
    assert ops.check(tmp_path) == (1, 0)
    (tmp_path / "ansible/playbooks/rogue.yml").write_text("name: rogue\ncommand: helm upgrade demo chart\n")
    with pytest.raises(ValueError, match="Unclassified literal Helm entrypoints"):
        ops.check(tmp_path)


def test_retired_entrypoint_must_keep_refusing(tmp_path):
    """Removing the refusal task re-opens a retired provisioning path."""
    import yaml

    ops = _load_checker("check_operational_entrypoints.py")
    _entrypoint_fixture(tmp_path)
    play = _retired_play()
    play[0]["tasks"] = [{"name": "Continue", "ansible.builtin.debug": {"msg": "ran"}}]
    (tmp_path / "ansible/playbooks/retired.yml").write_text(yaml.safe_dump(play))
    with pytest.raises(ValueError, match="Retired entrypoint"):
        ops.check(tmp_path)


def test_vendor_byte_drift_fails(tmp_path):
    """A changed vendored byte is drift, not a silent member of the trusted set."""
    vendor = _load_checker("check_vendor_contracts.py")
    tree = tmp_path / "vendor/demo"
    tree.mkdir(parents=True)
    payload = b"reviewed-bytes"
    (tree / "file.txt").write_bytes(payload)
    contract = {
        "schemaVersion": 1,
        "trees": [
            {
                "path": "vendor/demo",
                "basis": "reviewed-git-baseline",
                "reviewedCommit": "a" * 40,
                "provenanceNote": "fixture only, not upstream trust",
                "files": {"file.txt": hashlib.sha256(payload).hexdigest()},
            }
        ],
        "links": {},
        "linkInventoryGlobs": [],
    }
    (tmp_path / "deploy/contracts").mkdir(parents=True)
    (tmp_path / "deploy/contracts/vendors.json").write_text(json.dumps(contract))
    assert vendor.check(tmp_path) == 1
    (tree / "file.txt").write_bytes(b"mutated")
    with pytest.raises(ValueError, match="Vendor drift"):
        vendor.check(tmp_path)


def test_mypy_syntax_error_does_not_hide_another_file(tmp_path, monkeypatch):
    """A syntax fatal must not erase type findings from the other owned file."""
    import common
    import lint

    common.use_project_tools()
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/mypy.ini").write_text((ROOT / "quality/mypy.ini").read_text())
    (tmp_path / "pkg_a").mkdir()
    (tmp_path / "pkg_b").mkdir()
    (tmp_path / "pkg_a/typed.py").write_text('value: int = "not-an-int"\n')
    (tmp_path / "pkg_b/broken.py").write_text("def (\n")
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    findings = lint.mypy_findings(["pkg_a/typed.py", "pkg_b/broken.py"])
    paths = {item["location"]["path"] for item in findings}
    rules = {item["ruleId"] for item in findings}
    assert "pkg_a/typed.py" in paths
    assert "pkg_b/broken.py" in paths
    assert "assignment" in rules
    assert "python-syntax" in rules


def test_generated_publisher_findings_are_not_waived():
    """Auditor findings on the generated publisher stay visible and untrusted."""
    from common import command, use_project_tools

    use_project_tools()
    policy = json.loads((ROOT / "quality/strict-policy.json").read_text())["generatedWorkflows"]
    assert policy["trusted"] is False
    assert policy["waiver"] is False
    process = command(
        [
            "zizmor",
            "--offline",
            "--persona",
            "auditor",
            "--format",
            "sarif",
            policy["publisher"],
        ],
        allowed=(0, 1),
        timeout=60,
    )
    data = json.loads(process.stdout)
    rules = {item["ruleId"] for run in data["runs"] for item in run.get("results", [])}
    assert set(policy["zizmor"]) <= rules
    lint_text = (ROOT / "scripts/quality/lint.py").read_text()
    assert "quality-graph-publish" not in lint_text
    for rule in policy["zizmor"]:
        assert rule not in lint_text


def test_new_suppression_marker_is_reported(tmp_path, monkeypatch):
    """A newly added suppression marker is a finding, not configuration success."""
    import strict_guard

    marker = strict_guard.marker("# ", "no", "qa: ANN001")
    (tmp_path / "owned.py").write_text("value = 1  " + marker + "\n")
    monkeypatch.setattr(strict_guard, "ROOT", tmp_path)
    assert strict_guard.suppression_hits(["owned.py"]) == ["owned.py:1"]


def test_strict_configuration_contract_holds():
    """The live policy, generated publisher surface, and tool pins still match."""
    import strict_guard

    strict_guard.verify_configuration()
