from pathlib import Path

import yaml


def test_only_group_gateway_is_routable() -> None:
    path = Path(__file__).resolve().parents[1] / "deploy/platform/redisinsight/resources"
    docs = {
        r["kind"]: r["spec"]
        for manifest in path.glob("*.yaml")
        for r in yaml.safe_load_all(manifest.read_text())
    }
    ui, proxy = docs["Deployment"]["template"]["spec"]["containers"]
    assert {"name": "RI_APP_HOST", "value": "127.0.0.1"} in ui["env"]
    assert "--upstream=http://127.0.0.1:5540/" in proxy["args"]
    assert {a for a in proxy["args"] if a.startswith("--allowed-group=")} == {
        "--allowed-group=homelab-owner",
        "--allowed-group=redisinsight-readers",
    }
    assert not any(x.startswith("--skip-auth-") for x in proxy["args"])
    assert docs["Service"]["ports"][0]["targetPort"] == proxy["ports"][0]["name"]
    (rule,) = docs["Ingress"]["rules"]
    assert rule["host"] == "redis.socrat.alchemmist.xyz"
    assert rule["http"]["paths"][0]["backend"]["service"]["port"]["number"] == 4180
