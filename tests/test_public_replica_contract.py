"""Check replica equality against rendered resources, not names of known sites."""

import json
import subprocess

import pytest
import yaml
from jinja2 import Environment

from ci.quality.public_web import CATALOG, ROOT, replica_values


def test_every_replica_is_the_same_except_placement_and_local_a() -> None:
    """A new location with an unknown label must not require any routing code change."""
    catalog = yaml.safe_load(CATALOG.read_text())
    candidates = [
        *catalog["replicas"].values(),
        {"node": "example-worker", "publicIP": "192.0.2.10"},
    ]
    baseline = None
    for instance in candidates:
        values = replica_values(catalog, instance, 2026112601)
        text = subprocess.check_output(
            [
                "helm",
                "template",
                "entry",
                str(ROOT / "deploy/public-web/replica"),
                "-n",
                "public-entry",
                "-f",
                "-",
            ],
            input=json.dumps(values),
            text=True,
        )
        docs = [doc for doc in yaml.safe_load_all(text) if doc]
        (cm,) = [doc for doc in docs if doc["kind"] == "ConfigMap"]
        (dep,) = [doc for doc in docs if doc["kind"] == "Deployment"]
        pod = dep["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert [
            c["name"]
            for c in pod["containers"]
            if any(m["name"] == "api" for m in c.get("volumeMounts", []))
        ] == ["traefik"]
        (dns,) = [c for c in pod["containers"] if c["name"] == "coredns"]
        (service,) = [d["spec"] for d in docs if d["kind"] == "Service"]
        port = dns["readinessProbe"]["tcpSocket"]["port"]
        assert f":{port} {{" in cm["data"]["Corefile"]
        assert service["type"] == "ClusterIP"
        labels = dep["spec"]["template"]["metadata"]["labels"]
        assert service["selector"] == {"app.kubernetes.io/instance": "entry"}
        assert service["selector"].items() <= labels.items()
        assert labels["homelab.alchemmist.xyz/public-entry-controller"] == "true"
        assert {
            (p["protocol"], p["port"], p["targetPort"]) for p in service["ports"]
        } == {("TCP", 53, port), ("UDP", 53, port)}
        assert pod.pop("nodeSelector") == {"kubernetes.io/hostname": instance["node"]}
        dep["spec"]["template"]["metadata"].pop("annotations")
        expected = {
            host
            for names in catalog["hosts"].values()
            for host, policy in names.items()
            if policy.get("route", "web") == "web" and policy["dns"] == "managed"
        }
        normalized = []
        observed = []
        for line in cm["data"]["db.alchemmist.xyz"].splitlines():
            fields = line.split()
            host = (
                (
                    "alchemmist.xyz"
                    if fields[:1] == ["@"]
                    else fields[0] + ".alchemmist.xyz"
                )
                if fields
                else None
            )
            if host in expected and fields[1:3] == ["IN", "A"]:
                assert fields[3:] == [instance["publicIP"]]
                observed.append(host)
                normalized.append(f"{host} SELF")
            else:
                normalized.append(line)
        assert sorted(observed) == sorted(expected)
        cm["data"]["db.alchemmist.xyz"] = normalized
        assert any(line.startswith("vpn IN A ") for line in normalized)
        assert set(values["publications"]) == {
            d["metadata"]["namespace"] for d in docs if d["kind"] == "Role"
        }
        (controller,) = [c for c in pod["containers"] if c["name"] == "traefik"]
        assert (
            "--providers.kubernetesingress.labelselector=homelab.alchemmist.xyz/public-web in (true,reviewed)"
            in controller["args"]
        )
        prefix = "--providers.kubernetesingress.namespaces="
        (scope,) = [
            arg.removeprefix(prefix)
            for arg in controller["args"]
            if arg.startswith(prefix)
        ]
        assert set(scope.split(",")) == set(values["publications"])
        assert {
            d["metadata"]["namespace"] for d in docs if d["kind"] == "RoleBinding"
        } == set(scope.split(","))
        assert not {"postgres", "redis", "netbird-pilot"}.intersection(scope.split(","))
        assert "inform.sch1357.ru" in values["publications"]["schoolbot"]
        assert "bot.sch1357.ru" not in values["publications"]["schoolbot"]
        assert "monori.alchemmist.xyz" in values["publications"]["monori"]
        if baseline is None:
            baseline = docs, values["publications"]
        assert (docs, values["publications"]) == baseline


def test_replica_cannot_override_host_or_namespace_scope() -> None:
    """Inventory entries only supply placement and IP."""
    catalog = yaml.safe_load(CATALOG.read_text())
    with pytest.raises(ValueError, match="only node and publicIP"):
        replica_values(
            catalog, {**catalog["replicas"]["home"], "watchNamespaces": ["blog"]}, 1
        )


def test_route_gate_checks_every_owner_not_just_host_presence() -> None:
    """Reject missing owner opt-in, overlapping rules and accidental fixed relay selection."""
    from ci.quality.public_route_gate import LABEL, findings

    catalog = {
        "hosts": {"app": {"web.test": {}, "fixed.test": {"route": "fixed-relay"}}}
    }

    def ingress(name: str, host: str, path: str, selected: bool) -> dict:
        return {
            "metadata": {
                "namespace": "app",
                "name": name,
                "labels": {LABEL: str(selected).lower()},
            },
            "spec": {
                "ingressClassName": "traefik",
                "rules": [
                    {
                        "host": host,
                        "http": {"paths": [{"path": path, "pathType": "Exact"}]},
                    }
                ],
            },
        }

    root = ingress("root", "web.test", "/", True)
    extra = ingress("extra", "web.test", "/other", True)
    fixed = ingress("relay", "fixed.test", "/", False)
    assert not findings(catalog, [root, extra, fixed])
    extra["metadata"]["labels"] = {}
    fixed["metadata"]["labels"][LABEL] = "true"
    assert (
        len(
            findings(
                catalog, [root, extra, fixed, ingress("copy", "web.test", "/", True)]
            )
        )
        == 3
    )

    del root["spec"]["rules"][0]["http"]["paths"][0]["pathType"]
    assert findings(catalog, [root]) == ["invalid path or pathType: app/root web.test"]

    parent = ingress("parent", "web.test", "/foo", True)
    parent["spec"]["rules"][0]["http"]["paths"][0]["pathType"] = "Prefix"
    assert not findings(
        catalog, [parent, ingress("other", "web.test", "/foobar", True)]
    )
    assert findings(catalog, [parent, ingress("child", "web.test", "/foo/bar", True)])[
        0
    ].startswith("review intersecting paths:")

    stale = ingress("stale", "typo.test", "/", True)
    assert "unexpected selected host: app/stale typo.test" in findings(catalog, [stale])


def test_http01_selector_labels_only_catalogued_web_challenges() -> None:
    """Render the bootstrap issuer, retaining its unlabeled default solver."""
    plays = yaml.safe_load((ROOT / "ansible/playbooks/k3s.yml").read_text())
    (task,) = [
        t
        for play in plays
        for t in play.get("tasks", [])
        if t.get("name") == "Create Let's Encrypt ClusterIssuer"
    ]
    catalog = yaml.safe_load(CATALOG.read_text())
    env = Environment(autoescape=False)
    env.filters["to_json"] = json.dumps

    def render_issuer(inventory: dict) -> dict:
        name = "public-http01-issuer.yaml.j2"
        assert (
            task["ansible.builtin.command"]["stdin"]
            == "{{ lookup('ansible.builtin.template', '" + name + "') }}"
        )
        template = (ROOT / "ansible/playbooks/templates" / name).read_text()
        return yaml.safe_load(
            env.from_string(template).render(
                issuer_catalog=inventory, letsencrypt_email="test@example.org"
            )
        )

    issuer = render_issuer(catalog)
    scoped, fallback = issuer["spec"]["acme"]["solvers"]
    assert set(scoped["selector"]["dnsNames"]) == {
        host
        for hosts in catalog["hosts"].values()
        for host, policy in hosts.items()
        if policy.get("route", "web") == "web"
    }
    assert scoped["http01"]["ingress"]["ingressTemplate"]["metadata"]["labels"] == {
        "homelab.alchemmist.xyz/public-web": "true"
    }
    assert fallback == {"http01": {"ingress": {"ingressClassName": "traefik"}}}
    assert isinstance(scoped["selector"]["dnsNames"], list)
    assert render_issuer({"hosts": {}})["spec"]["acme"]["solvers"] == [fallback]


@pytest.mark.parametrize(
    "value,eligible",
    [("reviewed", True), ("true", True), ("false", False), ("", False)],
)
def test_existing_reviewed_owner_label(value: str, eligible: bool) -> None:
    """Respect both explicit owner markers, never just the label's presence."""
    from ci.quality.public_route_gate import LABEL, findings

    owner = {
        "metadata": {"namespace": "example", "name": "app", "labels": {LABEL: value}},
        "spec": {
            "ingressClassName": "traefik",
            "rules": [
                {
                    "host": "app.example",
                    "http": {"paths": [{"path": "/", "pathType": "Prefix"}]},
                }
            ],
        },
    }
    assert (
        not findings({"hosts": {"example": {"app.example": {}}}}, [owner])
    ) is eligible
