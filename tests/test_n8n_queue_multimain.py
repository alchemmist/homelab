"""Offline checks for the queue-mode / multi-main n8n rollout."""

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CHART = REPO / "charts" / "n8n"
VALUES = REPO / "deploy" / "n8n" / "values.yaml"
ONBOARD = REPO / "deploy" / "redis-common" / "onboard-n8n.py"
if not ONBOARD.exists():
    ONBOARD = REPO / "deploy" / "platform" / "redis-common" / "onboard-n8n.py"
CONSUMER_NET = REPO / "deploy" / "platform" / "redis-common" / "resources" / "consumer-net.yaml"


def render(extra: list[str]) -> list[dict]:
    out = subprocess.run(
        ["helm", "template", "n8n", str(CHART), "-n", "automation", "-f", str(VALUES), *extra],
        capture_output=True,
        text=True,
        check=True,
    )
    return [d for d in yaml.safe_load_all(out.stdout) if d]


class N8nQueueMultimain(unittest.TestCase):
    def test_worker_and_queue_envs_render_only_when_enabled(self) -> None:
        legacy = render(["--set", "queue.enabled=false"])
        assert not any(d["metadata"].get("name") == "n8n-worker" for d in legacy)
        legacy_text = yaml.safe_dump(legacy)
        for needle in (
            "N8N_EXECUTIONS_MODE",
            "QUEUE_BULL_REDIS_HOST",
            "N8N_MULTI_MAIN_SETUP_ENABLED",
            "redis-common-n8n",
            "node-ca-bundle",
        ):
            assert needle not in legacy_text, needle

        enabled = render([])
        worker = next(d for d in enabled if d["metadata"].get("name") == "n8n-worker")
        main = next(
            d for d in enabled if d["kind"] == "Deployment" and d["metadata"]["name"] == "n8n"
        )
        main_env = {
            e["name"]: e.get("value")
            for e in main["spec"]["template"]["spec"]["containers"][0]["env"]
        }
        assert main_env["N8N_EXECUTIONS_MODE"] == "queue"
        assert main_env["N8N_MULTI_MAIN_SETUP_ENABLED"] == "true"
        worker_env = {
            e["name"]: e.get("value")
            for e in worker["spec"]["template"]["spec"]["containers"][0]["env"]
        }
        assert worker_env["N8N_EXECUTIONS_MODE"] == "queue"
        assert "N8N_MULTI_MAIN_SETUP_ENABLED" not in worker_env
        for env in (main_env, worker_env):
            assert env["QUEUE_BULL_REDIS_HOST"] == "redis-common-haproxy.redis.svc.cluster.local"
            assert env["QUEUE_BULL_REDIS_TLS"] == "true"

    def test_worker_healthcheck_and_command(self) -> None:
        enabled = render([])
        worker = next(d for d in enabled if d["metadata"].get("name") == "n8n-worker")
        c = worker["spec"]["template"]["spec"]["containers"][0]
        assert c["command"] == ["n8n", "worker"]
        assert c["args"] == ["--concurrency=10"], "worker concurrency from values"
        env = {e["name"]: e.get("value") for e in c["env"]}
        assert env["QUEUE_HEALTH_CHECK_ACTIVE"] == "true"
        assert env["QUEUE_HEALTH_CHECK_PORT"] == "9230"
        for probe in ("readinessProbe", "livenessProbe"):
            assert c[probe]["httpGet"]["port"] == "healthcheck"

    def test_multimain_topology(self) -> None:
        enabled = render([])
        main = next(
            d for d in enabled if d["kind"] == "Deployment" and d["metadata"]["name"] == "n8n"
        )
        assert main["spec"]["replicas"] == 2
        assert main["spec"]["strategy"]["type"] == "RollingUpdate"
        spec = main["spec"]["template"]["spec"]
        anti = spec["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
        assert anti[0]["topologyKey"] == "kubernetes.io/hostname"
        assert anti[0]["labelSelector"]["matchLabels"] == {"app": "n8n"}
        node_aff = spec["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]
        expr = node_aff["nodeSelectorTerms"][0]["matchExpressions"][0]
        assert expr["operator"] == "In"
        assert sorted(expr["values"]) == ["socrat-0", "socrat-5"]
        # node-local PVC cannot host two mains; queue mode drops it for emptyDir.
        vols = {v["name"]: v for v in spec["volumes"]}
        assert "emptyDir" in vols["data"]
        assert "persistentVolumeClaim" not in vols["data"]
        assert vols["redis-common-n8n"]["secret"]["secretName"] == "redis-common-n8n"
        worker = next(d for d in enabled if d["metadata"].get("name") == "n8n-worker")
        wspec = worker["spec"]["template"]["spec"]
        assert wspec["nodeSelector"]["kubernetes.io/hostname"] == "socrat-1"

    def test_main_bundles_cas_for_redis_tls(self) -> None:
        enabled = render([])
        main = next(
            d for d in enabled if d["kind"] == "Deployment" and d["metadata"]["name"] == "n8n"
        )
        spec = main["spec"]["template"]["spec"]
        bundle = next(c for c in spec["initContainers"] if c["name"] == "node-ca-bundle")
        assert "cat /etc/pg-common/ca.crt /etc/redis-common/ca.crt" in " ".join(bundle["args"])
        mounts = [m["name"] for m in bundle["volumeMounts"]]
        assert "redis-common-n8n" in mounts
        env = {e["name"]: e.get("value") for e in spec["containers"][0]["env"]}
        assert env["NODE_EXTRA_CA_CERTS"] == "/etc/node-ca/bundle.pem"

    def test_worker_joins_service_vpn_and_extensions(self) -> None:
        enabled = render([])
        worker = next(d for d in enabled if d["metadata"].get("name") == "n8n-worker")
        spec = worker["spec"]["template"]["spec"]
        names = [c["name"] for c in spec["containers"]]
        assert "service-vpn" in names, "Google-facing nodes execute on workers"
        env = {e["name"]: e for e in spec["containers"][0]["env"]}
        assert env["N8N_CUSTOM_EXTENSIONS"]["value"] == "/opt/n8n/yandex-extension"
        assert env["N8N_ENCRYPTION_KEY"]["valueFrom"]["secretKeyRef"]["name"] == "n8n-secrets"
        assert (
            env["N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY"]["valueFrom"]["secretKeyRef"]["name"]
            == "n8n-s3-storage"
        )

    def test_onboard_script_is_explicit_and_scoped(self) -> None:
        source = ONBOARD.read_text()
        assert 'sys.argv[1:] != ["--create-missing"]' in source
        assert "~n8n:*" in source and "&n8n:*" in source
        assert "litellm" in source, "must not disturb the existing litellm ACL"
        script = textwrap.dedent(
            f"""
            import base64, json
            import importlib.util
            spec = importlib.util.spec_from_file_location("onboard", {str(ONBOARD)!r})
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            assert "xadd" in m.COMMANDS and "xreadgroup" in m.COMMANDS
            assert "flushall" not in m.COMMANDS and "shutdown" not in m.COMMANDS
            assert "eval" in m.COMMANDS and "script|load" in m.COMMANDS
            """
        )
        subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)

    def test_consumer_net_admits_n8n_pods_only_from_automation(self) -> None:
        doc = yaml.safe_load(CONSUMER_NET.read_text().replace("---\n", "").replace("...\n", ""))
        entries = doc["spec"]["ingress"][0]["from"]
        n8n_entries = [
            e
            for e in entries
            if e.get("podSelector", {}).get("matchLabels", {}).get("app") in ("n8n", "n8n-worker")
        ]
        assert len(n8n_entries) == 2
        for e in n8n_entries:
            assert (
                e["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "automation"
            )
