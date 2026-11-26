"""Guard the NL watch/RBAC boundary against undeclared rendered Ingress hosts."""

import re

import pytest
import yaml

from ci.quality.charts import ManifestLoader, argocd_targets, render
from ci.quality.public_web import CATALOG, ROOT, VALUES, namespace_block

CAT = yaml.load(CATALOG.read_text(), Loader=ManifestLoader)
WATCH = set(yaml.safe_load(VALUES.read_text())["watchNamespaces"])


def check_ingress(doc: dict, fallback: str) -> None:
    """Reject unknown hosts, catch-all routes and unscoped TLS in catalog namespaces."""
    if doc.get("kind") != "Ingress":
        return
    ns = doc["metadata"].get("namespace", fallback)
    if ns not in WATCH and ns not in CAT:
        return
    spec = doc["spec"]
    allowed = {
        host
        for host, p in CAT[ns].items()
        if (p["entrances"] or p.get("nlException"))
        and (ns not in WATCH or "nl" in p["entrances"] or p.get("nlException"))
    }
    assert "defaultBackend" not in spec and spec.get("rules"), (ns, doc["metadata"])
    for rule in spec["rules"]:
        assert rule.get("host") in allowed, (ns, rule.get("host"))
    for tls in spec.get("tls", []):
        assert tls.get("hosts") and set(tls["hosts"]) <= allowed, (ns, tls.get("hosts"))


def test_catalog_scope() -> None:
    """Retain separate VPN ownership, the external school zone and exact hostnames."""
    assert (
        yaml.safe_load(namespace_block())["watchNamespaces"]
        == yaml.safe_load(VALUES.read_text())["watchNamespaces"]
    )
    for ns, hosts in CAT.items():
        for host, policy in hosts.items():
            assert re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
            assert set(policy["entrances"]) <= {"home", "moscow", "nl"}
            assert policy["dns"] in {"static", "managed", "external"}
            if "nlException" in policy:
                assert (ns, policy["nlException"]) in {
                    ("monori", "moscow-transit"),
                    ("traefik-edge", "vpn-transit"),
                }
    assert not CAT["traefik-edge"]["vpn.alchemmist.xyz"]["entrances"]
    assert CAT["schoolbot"]["bot.sch1357.ru"]["dns"] == "external"
    assert not WATCH.intersection(
        {"postgres", "redis", "schoolbot", "rustfs", "netbird-pilot"}
    )


def test_public_ingresses() -> None:
    """Inspect local Argo charts with their actual release names and production values."""
    targets, _ = argocd_targets()
    for target in targets:
        docs = render(target)
        assert docs is not None, target["id"]
        for doc in docs:
            check_ingress(doc, target["namespace"])
    for app in (ROOT / "deploy/argocd/apps").glob("*.yaml"):
        spec = yaml.safe_load(app.read_text())["spec"]
        for src in spec.get("sources", [spec.get("source", {})]):
            if not src.get("path"):
                continue
            path = ROOT / src["path"]
            if (path / "Chart.yaml").exists():
                continue
            for file in path.glob("*.yaml"):
                for doc in yaml.safe_load_all(file.read_text()):
                    if doc:
                        check_ingress(doc, spec["destination"]["namespace"])


@pytest.mark.parametrize("host", ["*.alchemmist.xyz", "private.alchemmist.xyz", None])
def test_unlisted_hosts_fail(host: str | None) -> None:
    """A namespace watch is not permission to serve arbitrary names."""
    with pytest.raises(AssertionError):
        check_ingress(
            {"kind": "Ingress", "metadata": {}, "spec": {"rules": [{"host": host}]}},
            "blog",
        )
