"""Guard the NL watch/RBAC boundary against undeclared rendered Ingress hosts."""

import re

import pytest
import yaml

from ci.quality.charts import ManifestLoader, argocd_targets, render
from ci.quality.public_web import CATALOG, ROOT, VALUES

REGISTRY = yaml.load(CATALOG.read_text(), Loader=ManifestLoader)
CAT = REGISTRY["hosts"]
WATCH = set(yaml.safe_load(VALUES.read_text())["watchNamespaces"])


def check_ingress(doc: dict, fallback: str) -> None:
    """Reject unknown hosts, catch-all routes and unscoped TLS in catalog namespaces."""
    if doc.get("kind") != "Ingress":
        return
    ns = doc["metadata"].get("namespace", fallback)
    spec = doc["spec"]
    if ns not in CAT:
        # These private application routes exist on HOME; never grant an NL watch.
        private = {
            ("postgres", "pgadmin"): "pg.socrat.alchemmist.xyz",
            ("redis", "redisinsight"): "redis.socrat.alchemmist.xyz",
        }
        key = (ns, doc["metadata"].get("name"))
        assert ns not in WATCH and key in private, ("undeclared ingress", key)
        allowed = {private[key]}
    else:
        allowed = {
            host
            for host, p in CAT[ns].items()
            if p.get("route", "web") in {"web", "vpn-transit", "fixed-relay"}
        }
    assert "defaultBackend" not in spec and spec.get("rules"), (ns, doc["metadata"])
    for rule in spec["rules"]:
        assert rule.get("host") in allowed, (ns, rule.get("host"))
    for tls in spec.get("tls", []):
        assert tls.get("hosts") and set(tls["hosts"]) <= allowed, (ns, tls.get("hosts"))


def test_catalog_scope() -> None:
    """Retain separate VPN ownership, the external school zone and exact hostnames."""
    assert WATCH <= CAT.keys()
    for ns, hosts in CAT.items():
        for host, policy in hosts.items():
            assert re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
            assert set(policy) <= {"dns", "route"}
            assert policy.get("route", "web") in {
                "web",
                "reserved",
                "vpn-transit",
                "fixed-relay",
            }
            assert policy["dns"] in {"static", "managed", "external"}
    assert CAT["traefik-edge"]["vpn.alchemmist.xyz"]["route"] == "vpn-transit"
    assert CAT["schoolbot"]["bot.sch1357.ru"]["dns"] == "external"
    assert not WATCH.intersection(
        {"postgres", "redis", "schoolbot", "rustfs", "netbird-pilot"}
    )


def test_effective_nl_discovery_scope() -> None:
    """Check production Helm overrides cannot widen the watch or namespace RBAC."""
    targets, _ = argocd_targets()
    nl_targets = [
        target for target in targets if target["chart"] == ROOT / "charts/traefik-edge"
    ]
    assert nl_targets
    for target in nl_targets:
        docs = render(target)
        assert docs is not None
        release = target["release"]
        approved = WATCH
        for kind in ("Role", "RoleBinding"):
            assert {
                d["metadata"]["namespace"]
                for d in docs
                if d["kind"] == kind and d["metadata"]["name"] == release
            } == approved
        (deployment,) = [
            d
            for d in docs
            if d["kind"] == "Deployment" and d["metadata"]["name"] == release
        ]
        (controller,) = [
            c
            for c in deployment["spec"]["template"]["spec"]["containers"]
            if c["name"] == "traefik"
        ]
        prefix = "--providers.kubernetesingress.namespaces="
        (scope,) = [
            arg.removeprefix(prefix)
            for arg in controller["args"]
            if arg.startswith(prefix)
        ]
        assert set(scope.split(",")) == approved


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


def test_unknown_namespace_fails() -> None:
    """A renamed or new namespace must not silently bypass host validation."""
    with pytest.raises(AssertionError, match="undeclared ingress"):
        check_ingress(
            {
                "kind": "Ingress",
                "metadata": {},
                "spec": {"rules": [{"host": "alchemmist.xyz"}]},
            },
            "blog-extra",
        )
