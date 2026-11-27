"""Test exact TLS ownership independently of controller placement and selected probe sites."""

import copy

import pytest

from ci.quality.public_tls_sources import inventory

CAT = {
    "hosts": {
        "site": {"app.test": {"dns": "managed"}},
        "files": {"app.test": {"dns": "managed"}},
        "transit": {"vpn.test": {"route": "vpn-transit"}},
    }
}
ING = {
    "kind": "Ingress",
    "metadata": {"namespace": "site"},
    "spec": {
        "ingressClassName": "traefik",
        "rules": [{"host": "app.test"}],
        "tls": [{"hosts": ["app.test"], "secretName": "site-tls"}],
    },
}
PATH = {
    "kind": "Ingress",
    "metadata": {"namespace": "files"},
    "spec": {"ingressClassName": "traefik", "rules": [{"host": "app.test"}]},
}
CERT = {
    "kind": "Certificate",
    "metadata": {"namespace": "site", "generation": 1},
    "spec": {"secretName": "site-tls", "dnsNames": ["app.test"]},
    "status": {
        "conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1}]
    },
}


def test_shared_path_owner_does_not_grant_secret_access() -> None:
    report = inventory(CAT, [ING, PATH, CERT])
    assert report["errors"] == []
    assert report["hostSources"] == {"app.test": "site/site-tls"}
    assert report["namedGetRules"] == {
        "site": {
            "apiGroups": [""],
            "verbs": ["get"],
            "resources": ["secrets"],
            "resourceNames": ["site-tls"],
        }
    }


@pytest.mark.parametrize(
    "case",
    [
        "competing-source",
        "duplicate-writer",
        "unready",
        "no-dns-name",
        "missing-owner",
        "wrong-class",
    ],
)
def test_invalid_inventory_emits_no_candidate_rules(case: str) -> None:
    items = copy.deepcopy([ING, PATH, CERT])
    if case == "competing-source":
        items[1]["spec"]["tls"] = ING["spec"]["tls"]
    elif case == "duplicate-writer":
        items.append(CERT)
    elif case == "unready":
        del items[2]["status"]
    elif case == "no-dns-name":
        items[2]["spec"]["dnsNames"] = ["another.test"]
    elif case == "missing-owner":
        items.pop(1)
    else:
        items[0]["spec"]["ingressClassName"] = "other"
    report = inventory(CAT, items)
    assert report["errors"] and not report["namedGetRules"]


def test_two_ingresses_can_share_one_multiname_certificate() -> None:
    catalog = copy.deepcopy(CAT)
    catalog["hosts"]["site"]["alias.test"] = {"dns": "managed"}
    owner, cert = copy.deepcopy([ING, CERT])
    owner["spec"]["tls"][0]["hosts"].append("alias.test")
    cert["spec"]["dnsNames"].append("alias.test")
    alias = {
        "kind": "Ingress",
        "metadata": {"namespace": "site"},
        "spec": {"ingressClassName": "traefik", "rules": [{"host": "alias.test"}]},
    }
    report = inventory(catalog, [owner, cert, PATH, alias])
    assert (
        not report["errors"] and report["hostSources"]["alias.test"] == "site/site-tls"
    )
    cert["spec"]["dnsNames"].append("private.test")
    assert not inventory(catalog, [owner, cert, PATH, alias])["namedGetRules"]


def test_mixed_route_reports_conflict_and_withholds_rules() -> None:
    mixed = copy.deepcopy(ING)
    mixed["metadata"]["name"] = "mixed"
    mixed["spec"]["rules"].append({"host": "unknown.test"})
    report = inventory(CAT, [mixed, PATH, CERT])
    assert "site/mixed: mixed ordinary and undeclared hosts" in report["errors"]
    assert report["hostSources"] == {"app.test": "site/site-tls"}
    assert report["errors"] == ["site/mixed: mixed ordinary and undeclared hosts"]
    assert not any(e.startswith("missing route owner") for e in report["errors"])
    assert not report["namedGetRules"]


def test_duplicate_certificate_writer_is_an_independent_blocker() -> None:
    second = copy.deepcopy(CERT)
    second["metadata"]["name"] = "other-writer"
    report = inventory(CAT, [ING, PATH, CERT, second])
    assert report["errors"] == ["app.test: expected one Certificate writer, found 2"]
    assert not report["namedGetRules"]


def test_healthy_observed_alias_cannot_redirect_a_reviewed_secret_pin():
    from ci.quality.public_tls_pins import compare

    catalog = copy.deepcopy(CAT)
    catalog["hosts"]["site"]["app.test"]["tlsSourceName"] = "site-tls"
    items = copy.deepcopy([ING, PATH, CERT])
    assert compare(catalog, items) == {
        "sources": {"site/site-tls": ["app.test"]},
        "errors": [],
    }
    items[0]["spec"]["tls"][0]["secretName"] = "unreviewed"
    items[2]["spec"]["secretName"] = "unreviewed"
    assert not inventory(catalog, items)[
        "errors"
    ]  # Internally consistent, not independently approved.
    assert compare(catalog, items) == {
        "sources": {},
        "errors": ["app.test: observed source differs from reviewed pin"],
    }


@pytest.mark.parametrize(
    "change", ["missing", "ambiguous", "non-web", "namespace-path"]
)
def test_no_partial_or_cross_namespace_reader_plan(change):
    from ci.quality.public_tls_pins import compare

    catalog = copy.deepcopy(CAT)
    site = catalog["hosts"]["site"]["app.test"]
    site["tlsSourceName"] = "site-tls"
    if change == "missing":
        del site["tlsSourceName"]
    elif change == "ambiguous":
        catalog["hosts"]["files"]["app.test"]["tlsSourceName"] = "another"
    elif change == "non-web":
        catalog["hosts"]["transit"]["vpn.test"]["tlsSourceName"] = "nope"
    else:
        site["tlsSourceName"] = "other/site-tls"
    report = compare(catalog, [ING, PATH, CERT])
    assert report["errors"] and not report["sources"]


def _release_tls_objects(app):
    import subprocess

    import yaml

    from ci.quality.public_web import ROOT

    spec = yaml.safe_load((ROOT / "deploy/argocd/apps" / f"{app}.yaml").read_text())[
        "spec"
    ]
    sources = spec.get("sources") or [spec["source"]]
    repo = "https://github.com/alchemmist/homelab.git"
    ns = spec["destination"]["namespace"]
    for src in sources:
        assert src["repoURL"] == repo and src["targetRevision"] == "main"
        if "ref" in src:
            assert src["ref"] == "values" and "path" not in src
            continue
        chart = ROOT / src["path"]
        if not (chart / "Chart.yaml").is_file():
            assert src["path"] == "deploy/storage/grafana-socrat5"
            assert all(
                d["kind"] in {"PersistentVolume", "PersistentVolumeClaim"}
                for d in yaml.safe_load_all((chart / "volume.yaml").read_text())
                if d
            )
            continue
        helm = src.get("helm", {})
        assert set(helm) <= {"releaseName", "parameters", "valueFiles"}
        args = ["helm", "template", helm.get("releaseName", app), str(chart), "-n", ns]
        if chart.name == "rancher":
            defaults = yaml.safe_load(
                (ROOT / "ansible/roles/k3s_ha/defaults/main.yml").read_text()
            )
            args.extend(
                [
                    "--kube-version",
                    defaults["k3s_ha_version"].removeprefix("v").split("+")[0],
                ]
            )
        for f in helm.get("valueFiles", []):
            if f.startswith("$values/"):
                assert any(
                    s.get("ref") == "values" and s["repoURL"] == repo for s in sources
                )
                file = ROOT / f.removeprefix("$values/")
            else:
                file = chart / f
            args.extend(["-f", str(file)])
        for p in helm.get("parameters", []):
            args.extend(
                [
                    "--set-string" if p.get("forceString") else "--set",
                    p["name"] + "=" + p["value"],
                ]
            )
        for d in yaml.safe_load_all(subprocess.check_output(args, text=True)):
            if d and d["kind"] in {"Ingress", "Certificate"}:
                yield d["metadata"].get("namespace", ns), d


def test_reviewed_tls_pins_agree_with_separately_rendered_releases():
    """Verify each reference, route owner and unique issuance request independently."""
    from collections import defaultdict

    import yaml

    from ci.quality.public_web import CATALOG

    apps = "blog cats format-quorum grafana-mcp img-proxy lms monori n8n pr-agent remark42 schoolbot socrat-bot socrat-home spi-triage syncthing umami uptime-kuma venice-api wiki-runtime wishlist litellm litellm-infra open-webui searxng harbor authentik grafana openhands netbird rustfs rancher".split()
    policy = yaml.safe_load(CATALOG.read_text())["hosts"]
    pinned = {
        (ns, host, settings["tlsSourceName"])
        for ns, hosts in policy.items()
        for host, settings in hosts.items()
        if "tlsSourceName" in settings
    }
    routes = set()
    refs = set()
    writers = defaultdict(list)
    for app in apps:
        for ns, d in _release_tls_objects(app):
            spec = d["spec"]
            meta = d["metadata"]
            if d["kind"] == "Certificate":
                writers[ns, spec["secretName"]].append(
                    (
                        spec["issuerRef"]["kind"],
                        spec["issuerRef"]["name"],
                        frozenset(spec["dnsNames"]),
                    )
                )
                continue
            if spec.get("ingressClassName") != "traefik":
                continue
            routes.update((ns, r["host"]) for r in spec["rules"])
            for tls in spec.get("tls", []):
                for host in tls["hosts"]:
                    if policy.get(ns, {}).get(host, {}).get("route", "web") == "web":
                        refs.add((ns, host, tls["secretName"]))
                issuer = meta.get("annotations", {}).get(
                    "cert-manager.io/cluster-issuer"
                )
                if issuer:
                    writers[ns, tls["secretName"]].append(
                        ("ClusterIssuer", issuer, frozenset(tls["hosts"]))
                    )
    from ci.quality.public_argocd_tls import owner

    # The external archive render is independently repeatable, not fetched by CI.
    external = owner()
    assert refs | {external} == pinned
    ordinary = {
        h
        for hosts in policy.values()
        for h, p in hosts.items()
        if p.get("route", "web") == "web"
    }
    assert {h for _, h, _ in pinned} == ordinary and len(pinned) == len(ordinary)
    pinned = refs
    assert {(ns, host) for ns, host, _ in pinned} <= routes
    for ns, key in {(ns, key) for ns, _, key in pinned}:
        sans = frozenset(h for n, h, k in pinned if (n, k) == (ns, key))
        assert writers[ns, key] == [("ClusterIssuer", "letsencrypt-http01", sans)]


def test_unreviewed_external_chart_is_rejected_before_helm(tmp_path):
    from ci.quality.public_argocd_tls import verify

    wrong = tmp_path / "not-chart.tgz"
    wrong.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="unreviewed Argo CD chart"):
        verify(wrong)


@pytest.mark.parametrize("payload", ["[]", "{}", '{"items":null}', '{"items":[{}]}', "invalid"])
def test_pin_cli_rejects_malformed_input_without_dump(payload,monkeypatch,capsys):
    import io
    import json
    from ci.quality import public_tls_pins as pins
    monkeypatch.setattr(pins.sys,"stdin",io.StringIO(payload))
    assert pins.main()==1
    assert json.loads(capsys.readouterr().out)=={"sources":{},"errors":["invalid catalog or Kubernetes List input"]}
