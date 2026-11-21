"""Native auth/storage-preserving VM105 application-only placement contracts."""

import ast
from pathlib import Path
import hashlib, json, subprocess, tempfile, unittest, yaml

R = Path(__file__).resolve().parents[1]


def _mapping(value: object) -> dict[str, object]:
    """Narrow decoded document fields to mappings for typed test callers."""
    assert isinstance(value, dict)
    return value


def _sequence(value: object) -> list[object]:
    """Narrow decoded document fields to sequences for typed test callers."""
    assert isinstance(value, list)
    return list(value)


def _text(value: object) -> str:
    """Narrow decoded document fields to text for typed test callers."""
    assert isinstance(value, str)
    return value


def load(p: str) -> dict[str, object]:
    loaded = yaml.safe_load((R / p).read_text())
    return _mapping(loaded)


def render(
    chart: str, values: dict[str, object], release: str, ns: str
) -> dict[tuple[str, str], dict[str, object]]:
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
    def test_renderer_retry_after_transport_repair_preserves_grafana_and_adapter_placement(
        self,
    ) -> None:
        v = load("charts/grafana/alert-graphs.runtime.values.yaml")
        self.assertEqual(
            _mapping(_mapping(v["grafana"])["imageRenderer"])["nodeSelector"],
            {"kubernetes.io/hostname": "socrat-5"},
        )
        self.assertEqual(
            _mapping(v["alertGraphs"])["nodeSelector"], {"kubernetes.io/hostname": "socrat-1"}
        )
        self.assertEqual(
            _mapping(_mapping(v["grafana"])["imageRenderer"])["existingSecret"],
            "socrat-grafana-renderer",
        )

    def test_lms_single_worker_and_original_database_and_identity(self) -> None:
        v = load("charts/lms/values.yaml")
        v.update(load("deploy/lms/values.yaml"))
        docs = render("charts/lms", v, "lms", "lms")
        d = docs[("Deployment", "lms")]
        old = dict(v)
        old["webNodes"] = ["socrat-0", "socrat-1", "socrat-3"]
        old["hostAliases"] = []
        baseline = render("charts/lms", old, "lms", "lms")
        self.assertEqual([k for k in docs if docs[k] != baseline[k]], [("Deployment", "lms")])
        spec = _mapping(d["spec"])
        self.assertEqual(spec["strategy"], {"type": "Recreate"})
        self.assertEqual(spec["replicas"], 1)
        s = _mapping(_mapping(spec["template"])["spec"])
        affinity = _mapping(s["affinity"])
        node_affinity = _mapping(affinity["nodeAffinity"])
        required = _mapping(node_affinity["requiredDuringSchedulingIgnoredDuringExecution"])
        terms = _sequence(required["nodeSelectorTerms"])
        expression = _mapping(_mapping(_sequence(_mapping(terms[0])["matchExpressions"])[0]))
        self.assertEqual(expression["values"], ["socrat-5"])
        self.assertEqual(
            s["hostAliases"], [{"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}]
        )
        self.assertFalse(
            any("persistentVolumeClaim" in _mapping(x) for x in _sequence(s["volumes"]))
        )
        env: dict[str, object] = {}
        for entry in _sequence(_mapping(_sequence(s["containers"])[0])["env"]):
            env[_text(_mapping(entry)["name"])] = entry
        self.assertEqual(
            _mapping(_mapping(_mapping(env["LMS_DATABASE_URL"])["valueFrom"])["secretKeyRef"])[
                "name"
            ],
            "lms-db",
        )
        self.assertEqual(
            _mapping(
                _mapping(_mapping(env["LMS_OIDC_CLIENT_SECRET"])["valueFrom"])["secretKeyRef"]
            )["name"],
            "socrat-authentik-lms",
        )

    def test_vendor_preserves_every_upstream_file_except_two_minimal_extensions(self) -> None:
        root = R / "charts/litellm"
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
            self.assertEqual(hashlib.sha256(s).hexdigest(), digest, name)

    def test_litellm_only_deployment_changes_no_migration_job_or_config_or_secrets(self) -> None:
        v = load("deploy/platform/litellm/values.yaml")
        after = render("charts/litellm", v, "litellm", "llm")
        old = dict(v)
        old["nodeSelector"] = {"kubernetes.io/hostname": "socrat-0"}
        old["hostAliases"] = []
        migrationJob = dict(_mapping(old["migrationJob"]))
        migrationJob.pop("placementOnlyImage", None)
        migrationJob["enabled"] = True
        old["migrationJob"] = migrationJob
        envVars = dict(_mapping(old["envVars"]))
        envVars.pop("DISABLE_SCHEMA_UPDATE", None)
        old["envVars"] = envVars
        before = render("charts/litellm", old, "litellm", "llm")
        changed = [k for k in before if k in after and before[k] != after[k]]
        self.assertEqual(changed, [("Deployment", "litellm")])
        d = after[("Deployment", "litellm")]
        spec = _mapping(d["spec"])
        self.assertEqual(spec["replicas"], 1)
        self.assertEqual(
            _mapping(_mapping(spec["template"])["spec"])["terminationGracePeriodSeconds"], 7260
        )
        s = _mapping(_mapping(spec["template"])["spec"])
        self.assertEqual(s["nodeSelector"], {"kubernetes.io/hostname": "socrat-5"})
        self.assertEqual(
            s["hostAliases"], [{"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}]
        )
        self.assertTrue(any(k[0] == "Job" for k in before))
        self.assertFalse(any(k[0] == "Job" for k in after))
        broken = dict(v)
        broken["image"] = dict(_mapping(v["image"]))
        image = _mapping(broken["image"])
        image["tag"] = "not-reviewed-next-version"
        with self.assertRaises(subprocess.CalledProcessError):
            render("charts/litellm", broken, "litellm", "llm")
        self.assertEqual(_text(_mapping(v["envVars"])["DISABLE_SCHEMA_UPDATE"]).lower(), "true")
        self.assertRegex(
            _text(_mapping(v["image"])["tag"]),
            r"^a691e23abfac6dd0f2b69f9f5b4f714241f39ac4@sha256:[a-f0-9]{64}$",
        )
        self.assertEqual(v["masterkeySecretName"], "litellm-env")

    def test_app_source_keeps_version_and_selective_sync_safety(self) -> None:
        a = _mapping(load("deploy/argocd/apps/litellm.yaml")["spec"])
        self.assertEqual(_mapping(_sequence(a["sources"])[0])["path"], "charts/litellm")
        sync_policy = _mapping(a["syncPolicy"])
        self.assertFalse(_mapping(sync_policy["automated"])["prune"])
        self.assertIn("ApplyOutOfSyncOnly=true", _sequence(sync_policy["syncOptions"]))
        self.assertEqual(_mapping(load("charts/litellm/Chart.yaml"))["version"], "1.105.1")

    def test_ansible_cannot_silently_revert_to_old_node_or_oci_chart(self) -> None:
        s = (R / "ansible/playbooks/litellm.yml").read_text()
        p = yaml.safe_load(s)
        self.assertEqual(len(p), 1)
        self.assertEqual(len(p[0]["tasks"]), 1)
        self.assertIn("ansible.builtin.fail", p[0]["tasks"][0])
        self.assertNotIn("helm upgrade", s)
        self.assertIn("deploy/platform/litellm/values.yaml", s)
        g = ast.unparse(
            ast.parse(
                (R / "ansible/roles/monitoring_llm_gateway/files/configure_gateway.py").read_text()
            )
        )
        self.assertIn("s.get('path') == 'charts/litellm'", g)
        self.assertNotIn("['upgrade'", g)
        self.assertNotIn("/key/generate", g)
