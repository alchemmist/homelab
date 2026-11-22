"""Platform contracts that do not require network, cluster access or a Helm repo."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "deploy/platform/redis-common"


def test_storage_class_is_backed_by_allowed_node_paths():
    sc = yaml.safe_load((PLATFORM / "resources/storage.yaml").read_text())
    assert (sc["reclaimPolicy"], sc["volumeBindingMode"]) == ("Retain", "WaitForFirstConsumer")
    configs = yaml.safe_load_all((ROOT / "deploy/storage/tiers/platform.yaml").read_text())
    provisioner = next(c for c in configs if c and c["metadata"]["name"] == "local-path-config")
    class_name = sc["metadata"]["name"]
    paths = json.loads(provisioner["data"]["config.json"])["storageClassConfigs"][class_name]["nodePathMap"]
    assert {p["node"] for p in paths if p["paths"]} == set(sc["allowedTopologies"][0]["matchLabelExpressions"][0]["values"])
    assert yaml.safe_load((PLATFORM / "values.yaml").read_text())["persistentVolume"]["storageClass"] == class_name


def test_staged_application_and_tls_quorum():
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/redis-common.yaml").read_text())["spec"]
    assert app["destination"]["namespace"] == "redis" and "automated" not in app["syncPolicy"]
    upstream, local = app["sources"]
    assert upstream["targetRevision"] == "4.39.0" and local["ref"] == "values"
    v = yaml.safe_load((ROOT / upstream["helm"]["valueFiles"][0].removeprefix("$values/")).read_text())
    assert v["replicas"] == 3 and v["hardAntiAffinity"] and v["sentinel"]["quorum"] == 2
    assert v["redis"]["port"] == v["sentinel"]["port"] == 0
    assert all(v[k]["tlsReplication"] for k in ("redis", "sentinel"))
    assert v["networkPolicy"]["enabled"] and v["haproxy"]["networkPolicy"] == {"enabled": True}
    assert "default_backend" not in v["haproxy"]["customConfig"]
    assert v["redis"]["config"]["maxmemory-policy"] == "noeviction"


def test_production_proxy_uses_only_external_coordination():
    v = yaml.safe_load((ROOT / 'deploy/platform/litellm/values.yaml').read_text())
    assert v['proxy_config']['general_settings']['coordination_redis'] == {
        'namespace': 'litellm', 'url': 'os.environ/COORDINATION_REDIS_URL'}
    assert not v['redis']['enabled'] and not v['proxy_config']['litellm_settings'].get('cache')
    assert v['replicaCount'] == v['numWorkers'] == 1
    assert not v['migrationJob']['enabled']
    assert v['migrationJob']['placementOnlyImage'] == v['image']['repository'] + ':' + v['image']['tag']
