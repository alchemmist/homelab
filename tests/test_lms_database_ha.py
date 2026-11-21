import json
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]


def rendered(chart, *args) -> list[dict[str, object]]:
    docs: list[dict[str, object]] = [
        d
        for d in yaml.safe_load_all(
            subprocess.check_output(
                ["helm", "template", chart, str(ROOT / "charts" / chart), *args], text=True
            )
        )
        if d
    ]
    return docs


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of a parsed YAML value."""
    assert isinstance(value, dict)
    result: dict[str, object] = value
    return result


def _documents(value: object) -> list[dict[str, object]]:
    """Return the assert-verified list-of-documents view of a parsed YAML value."""
    assert isinstance(value, list)
    documents: list[dict[str, object]] = value
    return documents


def _mapping_path(document: dict[str, object], *keys: str) -> dict[str, object]:
    """Walk nested mappings of a parsed document and return the final mapping."""
    value: object = document
    for key in keys:
        value = _mapping(value)[key]
    return _mapping(value)


def _name(document: dict[str, object]) -> object:
    """Return the metadata name of a parsed Kubernetes document."""
    return _mapping(document["metadata"])["name"]


def _text(value: object) -> str:
    """Return the assert-verified string view of a parsed YAML value."""
    assert isinstance(value, str)
    return value


def test_database_has_three_separate_failure_domains_and_required_sync_quorum() -> None:
    docs = rendered("lms-database-ha")
    cluster = next(d for d in docs if d["kind"] == "Cluster")
    c = _mapping(cluster["spec"])
    postgresql = _mapping(c["postgresql"])
    affinity = _mapping(c["affinity"])
    storage = _mapping(c["storage"])
    assert c["instances"] == 3
    assert postgresql["synchronous"] == {
        "method": "any",
        "number": 1,
        "dataDurability": "required",
        "failoverQuorum": True,
    }
    assert _mapping(postgresql["parameters"])["synchronous_commit"] == "on"
    assert affinity["podAntiAffinityType"] == "required"
    node_selection = _mapping_path(
        affinity,
        "nodeAffinity",
        "requiredDuringSchedulingIgnoredDuringExecution",
    )
    terms = _documents(node_selection["nodeSelectorTerms"])
    expressions = _documents(terms[0]["matchExpressions"])
    assert expressions[0]["values"] == ["socrat-0", "socrat-1", "socrat-3"]
    assert storage["storageClass"] == "lms-db-retain"
    sc = next(d for d in docs if d["kind"] == "StorageClass")
    assert sc["reclaimPolicy"] == "Retain"
    assert "@sha256:" in _text(c["imageName"]) and ":17.11-" in _text(c["imageName"])
    assert c["enableSuperuserAccess"] is False


def test_backups_are_encrypted_and_not_shared_plaintext_files() -> None:
    docs = rendered("lms-database-ha", "--set", "backup.enabled=true")
    cron = next(d for d in docs if d["kind"] == "CronJob")
    assert _mapping_path(cron, "spec")["concurrencyPolicy"] == "Forbid"
    spec = _mapping_path(cron, "spec", "jobTemplate", "spec", "template", "spec")
    assert spec["automountServiceAccountToken"] is False
    affinity = _mapping_path(
        spec, "affinity", "nodeAffinity", "requiredDuringSchedulingIgnoredDuringExecution"
    )
    terms = _documents(affinity["nodeSelectorTerms"])
    expressions = _documents(terms[0]["matchExpressions"])
    assert expressions[0]["values"] == ["socrat-0", "socrat-1"]
    cmd = _text(_documents(_mapping(_documents(spec["containers"])[0])["args"])[0])
    assert "umask 077" in cmd and "--symmetric --cipher-algo AES256" in cmd
    assert "--passphrase-file /backup-key/passphrase" in cmd
    assert "PGSSLMODE=verify-full" in cmd
    assert "cmp /tmp/database.dump /tmp/checked.dump" in cmd
    assert "-name 'scheduled-*.dump.gpg'" in cmd
    tmp_volume = next(v for v in _documents(spec["volumes"]) if v["name"] == "tmp")
    assert _mapping(tmp_volume["emptyDir"])["medium"] == "Memory"


def test_single_worker_recreate_and_bounded_node_eviction_are_preserved() -> None:
    docs = rendered("lms", "--set", "database.ha.enabled=true")
    dep = next(d for d in docs if d["kind"] == "Deployment" and _name(d) == "lms")
    dep_spec = _mapping(dep["spec"])
    assert dep_spec["replicas"] == 1 and _mapping(dep_spec["strategy"])["type"] == "Recreate"
    pod = _mapping_path(dep, "spec", "template", "spec")
    assert {t["tolerationSeconds"] for t in _documents(pod["tolerations"])} == {60}
    secret_volume = next(v for v in _documents(pod["volumes"]) if v["name"] == "postgres-ca")
    ca = _mapping(secret_volume["secret"])
    assert ca["items"] == [{"key": "ca.crt", "path": "ca.crt"}]
    assert ca["defaultMode"] == 288


def test_copy_tool_refuses_live_ha_overwrite_and_final_restore_without_freeze() -> None:
    s = (ROOT / "scripts/lms-ha-copy.py").read_text()
    assert "application no longer uses legacy DB" in s
    assert "if dep['spec']['replicas']!=0 or pods['items']" in s
    assert "'backoffLimit':0" in s
    assert "shlex.join(['kubectl',*args])" in s
    copy = (ROOT / "scripts/lms-ha/copy-database.sh").read_text()
    assert "cmp /tmp/source.dump /tmp/recovered.dump" in copy
    assert "cmp /tmp/source.fingerprint /tmp/target.fingerprint" in copy
    assert "--single-transaction" in copy and "PGSSLMODE=verify-full" in copy
    assert 'COLLATE "C"' in copy
    assert "fingerprintMismatch=true; exit 1" in copy


def test_database_is_a_source_of_the_lms_application() -> None:
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/lms.yaml").read_text())
    assert "sources" not in app["spec"]
    assert app["spec"]["source"]["path"] == "charts/lms"
    assert app["spec"]["source"]["helm"]["releaseName"] == "lms"
    assert not (ROOT / "deploy/argocd/apps/lms-database-ha.yaml").exists()
    assert app["spec"]["syncPolicy"]["automated"]["prune"] is False
    ignored = [
        rule
        for rule in app["spec"]["ignoreDifferences"]
        if rule.get("kind")
        in {"Cluster", "CronJob", "PersistentVolumeClaim", "PrometheusRule", "StorageClass"}
    ]
    assert ignored == []
    values = yaml.safe_load((ROOT / "deploy/lms/values.yaml").read_text())
    assert (
        values["image"]["digest"]
        == "sha256:9890519389652cdd8c8436a76f81be6bc81131174a728144ab268c4150a80167"
    )
    assert values["database"]["ha"]["enabled"] is False
    assert values["database"]["ha"]["resources"] is True
    docs = rendered("lms", "-n", "lms", "-f", str(ROOT / "deploy/lms/values.yaml"))
    owned = {(d["kind"], _name(d), _mapping(d["metadata"]).get("namespace")) for d in docs}
    assert ("Cluster", "lms-ha", None) in owned
    assert ("CronJob", "lms-database-backup", None) in owned
    assert ("PersistentVolumeClaim", "lms-database-backups", None) in owned
    assert ("PrometheusRule", "lms-availability", "cattle-monitoring-system") in owned
    assert ("StorageClass", "lms-db-retain", None) in owned
    cluster = next(d for d in docs if d["kind"] == "Cluster")
    cluster_spec = _mapping(cluster["spec"])
    cluster_meta = _mapping(_mapping(cluster["metadata"])["annotations"])
    assert cluster_spec["instances"] == 3
    assert (
        cluster_spec["imageName"]
        == "ghcr.io/cloudnative-pg/postgresql:17.11-system-trixie@sha256:03a1c6a62b27e8ad31cae5c085131b5ac706b09403d6fcb6c58d16c8daa257cd"
    )
    assert (
        cluster_meta["argocd.argoproj.io/compare-options"]
        == "ServerSideDiff=true"
    )
    assert (
        cluster_meta["argocd.argoproj.io/sync-options"]
        == "ServerSideApply=true"
    )
    cron = next(
        d for d in docs if d["kind"] == "CronJob" and _name(d) == "lms-database-backup"
    )
    cron_spec = _mapping(cron["spec"])
    assert cron_spec["schedule"] == "0 */6 * * *"
    cron_pod = _mapping_path(cron, "spec", "jobTemplate", "spec", "template", "spec")
    assert (
        _mapping(_documents(cron_pod["containers"])[0])["image"]
        == "docker.io/library/postgres@sha256:839fbb5a4942a7758dd93e18b42ea5649807491a0545b5eeeb8f0b8bb11857a5"
    )
    web = next(d for d in docs if d["kind"] == "Deployment" and _name(d) == "lms")
    web_pod = _mapping_path(web, "spec", "template", "spec")
    assert (
        _mapping(_documents(web_pod["containers"])[0])["image"]
        == "ghcr.io/alchemmist/lms@sha256:9890519389652cdd8c8436a76f81be6bc81131174a728144ab268c4150a80167"
    )
    plain = rendered("lms", "-n", "lms")
    assert not any(d["kind"] == "Cluster" for d in plain)


def test_runtime_credentials_are_preserved_across_argo_sync() -> None:
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/lms.yaml").read_text())
    assert "RespectIgnoreDifferences=true" in app["spec"]["syncPolicy"]["syncOptions"]
    assert any(
        rule.get("kind") == "Secret"
        and rule.get("name") == "lms-db"
        and rule.get("jsonPointers") == ["/data"]
        for rule in app["spec"]["ignoreDifferences"]
    )
    secret = next(d for d in rendered("lms") if d["kind"] == "Secret" and _name(d) == "lms-db")
    assert "data" not in secret
    assert "lookup" not in (ROOT / "charts/lms/templates/database.yaml").read_text()


def test_production_web_does_not_depend_on_legacy_nfs_and_legacy_db_is_stopped() -> None:
    docs = rendered("lms", "-f", str(ROOT / "deploy/lms/values.yaml"))
    web = next(d for d in docs if d["kind"] == "Deployment" and _name(d) == "lms")
    web_pod = _mapping_path(web, "spec", "template", "spec")
    assert not any(
        "persistentVolumeClaim" in volume for volume in _documents(web_pod["volumes"])
    )
    assert any(
        d["kind"] == "PersistentVolumeClaim" and _name(d) == "lms-data" for d in docs
    )
    old = next(
        d for d in docs if d["kind"] == "Deployment" and _name(d) == "lms-postgres"
    )
    assert _mapping(old["spec"])["replicas"] == 1


def test_operator_canary_avoids_stale_ready_pod_on_unreachable_node() -> None:
    import importlib.util
    import pytest

    spec = importlib.util.spec_from_file_location(
        "verify", ROOT / "scripts/lms-observability-verify.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def pod(name, node, deleting=False):
        return {
            "metadata": {"name": name, **({"deletionTimestamp": "now"} if deleting else {})},
            "spec": {"nodeName": node},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        }

    nodes = {
        "items": [
            {
                "metadata": {"name": n},
                "status": {"conditions": [{"type": "Ready", "status": ready}]},
            }
            for n, ready in [("socrat-3", "Unknown"), ("socrat-1", "True")]
        ]
    }
    assert (
        module.ready_canary_pod(
            {"items": [pod("old", "socrat-3", True), pod("new", "socrat-1")]}, nodes
        )
        == "new"
    )
    with pytest.raises(RuntimeError):
        module.ready_canary_pod({"items": [pod("old", "socrat-3")]}, nodes)


def test_remote_canary_programs_are_valid_python_including_finally_cleanup() -> None:
    import ast

    for filename in ["lms-cpu-profile-verify.py", "lms-observability-verify.py"]:
        tree = ast.parse((ROOT / "scripts" / filename).read_text())
        snippets = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.JoinedStr)
            and any(
                isinstance(v, ast.Constant) and "from app.config import Settings" in str(v.value)
                for v in n.values
            )
        ]
        assert snippets
        for node in snippets:
            program = "".join(
                v.value if isinstance(v, ast.Constant) else repr("synthetic-canary")
                for v in node.values
            )
            ast.parse(program)


def test_copy_refuses_live_ha_or_unknown_endpoint_before_creating_job(monkeypatch) -> None:
    import base64
    import importlib.util
    import json
    from types import SimpleNamespace
    import pytest

    spec = importlib.util.spec_from_file_location("ha_copy", ROOT / "scripts/lms-ha-copy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for data in [
        {
            "LMS_DATABASE_URL": base64.b64encode(
                b"postgresql://example@lms-ha-rw.lms.svc.cluster.local/lms"
            ).decode()
        },
        {},
        {"LMS_DATABASE_URL": "invalid-base64!"},
        {"LMS_DATABASE_URL": base64.b64encode(b"").decode()},
    ]:
        calls = []

        def kube(*args, **kwargs):
            calls.append(args)
            assert args == ("-n", "lms", "get", "secret", "lms-db", "-o", "json")
            return json.dumps({"data": data})

        monkeypatch.setattr(module, "kube", kube)
        with pytest.raises(ValueError, match="Refusing"):
            module.run(SimpleNamespace(rehearsal=True, confirm_web_stopped=True))
        assert len(calls) == 1
