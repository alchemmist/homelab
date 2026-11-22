"""Native auth/storage-preserving VM105 application-only placement contracts."""

import ast
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.portable_placement import home_affinity

R = Path(__file__).resolve().parents[1]
LITELLM_GRACE_PERIOD_SECONDS = 7260


def load(p):
    return yaml.safe_load((R / p).read_text())


def render(chart, values, release, ns):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as f:
        yaml.safe_dump(values, f)
        f.flush()
        raw = subprocess.check_output(
            [
                "helm",
                "template",
                release,
                str(R / chart),
                "--namespace",
                ns,
                "--kube-version",
                "1.36.5",
                "-f",
                f.name,
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    return {(o["kind"], o["metadata"]["name"]): o for o in yaml.safe_load_all(raw) if o}


class MigrationTests(unittest.TestCase):
    """Tests for MigrationTests."""

    def test_renderer_retry_after_transport_repair_preserves_grafana_and_adapter_placement(self):
        v = load("charts/grafana/alert-graphs.runtime.values.yaml")
        assert v["grafana"]["imageRenderer"]["nodeSelector"] == {
            "kubernetes.io/hostname": "socrat-5"
        }
        assert v["alertGraphs"]["nodeSelector"] == {"kubernetes.io/os": "linux"}
        assert v["alertGraphs"]["affinity"] == home_affinity()
        assert v["grafana"]["imageRenderer"]["existingSecret"] == "socrat-grafana-renderer"

    def test_lms_single_worker_and_migrated_database_and_identity(self):
        v = load("charts/lms/values.yaml")
        v.update(load("deploy/lms/values.yaml"))
        docs = render("charts/lms", v, "lms", "lms")
        d = docs[("Deployment", "lms")]
        old = dict(v)
        old["webNodes"] = ["socrat-0", "socrat-1", "socrat-3"]
        old.pop("preferredWebNode", None)
        old["hostAliases"] = []
        baseline = render("charts/lms", old, "lms", "lms")
        assert [k for k in docs if docs[k] != baseline[k]] == [("Deployment", "lms")]
        assert d["spec"]["strategy"] == {"type": "Recreate"}
        assert d["spec"]["replicas"] == 1
        s = d["spec"]["template"]["spec"]
        assert s["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"][
            "nodeSelectorTerms"
        ][0]["matchExpressions"][0]["values"] == ["socrat-5", "socrat-0", "socrat-1"]
        preference = s["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"]
        assert preference == [{"weight": 100, "preference": {"matchExpressions": [
            {"key": "kubernetes.io/hostname", "operator": "In", "values": ["socrat-5"]}
        ]}}]
        assert s["hostAliases"] == [
            {"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}
        ]
        assert not any("persistentVolumeClaim" in x for x in s["volumes"])
        env = {e["name"]: e for e in s["containers"][0]["env"]}
        assert env["LMS_DATABASE_URL"]["valueFrom"]["secretKeyRef"] == {
            "name": "lms-pg-common", "key": "LMS_DATABASE_URL",
        }
        assert (
            env["LMS_OIDC_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]["name"]
            == "socrat-authentik-lms"
        )

    def test_vendor_preserves_every_upstream_file_after_reversing_local_extensions(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "litellm"
        shutil.copytree(R / "charts/litellm", root)
        patch = R / "deploy/platform/litellm/fork/helm-tests-and-namespace.patch"
        subprocess.run(["git", "apply", "-R", "-p3", str(patch)], cwd=root, check=True)
        manifest = json.loads((root / "upstream-file-sha256.json").read_text())
        for name, digest in manifest.items():
            s = (root / name).read_bytes()
            if name == "templates/deployment.yaml":
                s = s.replace(
                    b"      {{- with .Values.hostAliases }}\n      hostAliases:\n        {{- toYaml . | nindent 8 }}\n      {{- end }}\n",
                    b"",
                )
            if name == "templates/migrations-job.yaml":
                s = s[s.index(b"{{- if .Values.migrationJob.enabled }}") :]
            assert hashlib.sha256(s).hexdigest() == digest, name

    def test_litellm_only_deployment_changes_no_migration_job_or_config_or_secrets(self):
        v = load("deploy/platform/litellm/values.yaml")
        after = render("charts/litellm", v, "litellm", "llm")
        old = dict(v)
        old["nodeSelector"] = {"kubernetes.io/hostname": "socrat-0"}
        old["hostAliases"] = []
        old["migrationJob"] = dict(old["migrationJob"])
        old["migrationJob"].pop("placementOnlyImage", None)
        old["migrationJob"]["enabled"] = True
        old["envVars"] = dict(old["envVars"])
        old["envVars"].pop("DISABLE_SCHEMA_UPDATE", None)
        before = render("charts/litellm", old, "litellm", "llm")
        changed = [k for k in before if k in after and before[k] != after[k]]
        assert changed == [("Deployment", "litellm")]
        d = after[("Deployment", "litellm")]
        assert d["spec"]["replicas"] == 1
        assert (
            d["spec"]["template"]["spec"]["terminationGracePeriodSeconds"]
            == LITELLM_GRACE_PERIOD_SECONDS
        )
        s = d["spec"]["template"]["spec"]
        assert s["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
        assert s["hostAliases"] == [
            {"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}
        ]
        assert any(k[0] == "Job" for k in before)
        assert not any(k[0] == "Job" for k in after)
        broken = dict(v)
        broken["image"] = dict(v["image"])
        broken["image"]["tag"] = "not-reviewed-next-version"
        with self.assertRaises(subprocess.CalledProcessError):
            render("charts/litellm", broken, "litellm", "llm")
        assert v["envVars"]["DISABLE_SCHEMA_UPDATE"].lower() == "true"
        assert re.search(
            r"^eb6e7f61e4fa0fa1425461e4e92145c8eab73bef@sha256:[a-f0-9]{64}$", v["image"]["tag"]
        )
        assert v["masterkeySecretName"] == "litellm-env"

    def test_app_source_keeps_version_and_selective_sync_safety(self):
        a = load("deploy/argocd/apps/litellm.yaml")["spec"]
        assert a["sources"][0]["path"] == "charts/litellm"
        assert not a["syncPolicy"]["automated"]["prune"]
        assert "ApplyOutOfSyncOnly=true" in a["syncPolicy"]["syncOptions"]
        assert load("charts/litellm/Chart.yaml")["version"] == "1.105.1"

    def test_ansible_cannot_silently_revert_to_old_node_or_oci_chart(self):
        s = (R / "ansible/playbooks/litellm.yml").read_text()
        p = yaml.safe_load(s)
        assert len(p) == 1
        assert len(p[0]["tasks"]) == 1
        assert "ansible.builtin.fail" in p[0]["tasks"][0]
        assert "helm upgrade" not in s
        assert "deploy/platform/litellm/values.yaml" in s
        g = ast.unparse(
            ast.parse(
                (R / "ansible/roles/monitoring_llm_gateway/files/configure_gateway.py").read_text()
            )
        )
        assert "s.get('path') == 'charts/litellm'" in g
        assert "['upgrade'" not in g
        assert "/key/generate" not in g
