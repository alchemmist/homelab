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


def _release_tls_records(app):
    import subprocess

    import yaml

    from ci.quality.public_web import ROOT

    spec = yaml.safe_load((ROOT / "deploy/argocd/apps" / f"{app}.yaml").read_text())[
        "spec"
    ]
    src = spec["source"]
    helm = src["helm"]
    ns = spec["destination"]["namespace"]
    chart = ROOT / src["path"]
    assert set(helm) <= {"releaseName", "parameters", "valueFiles"}
    args = ["helm", "template", helm["releaseName"], str(chart), "-n", ns]
    for f in helm.get("valueFiles", []):
        args.extend(["-f", str(chart / f)])
    for p in helm.get("parameters", []):
        args.extend(
            [
                "--set-string" if p.get("forceString") else "--set",
                p["name"] + "=" + p["value"],
            ]
        )
    docs = yaml.safe_load_all(subprocess.check_output(args, text=True))
    observed = set()
    for d in docs:
        if not d or d["kind"] != "Ingress":
            continue
        for t in d["spec"].get("tls", []):
            assert (
                d["spec"]["ingressClassName"] == "traefik"
                and d["metadata"].get("namespace", ns) == ns
            )
            assert (
                d["metadata"]["annotations"]["cert-manager.io/cluster-issuer"]
                == "letsencrypt-http01"
            )
            for h in t["hosts"]:
                assert h in {rule["host"] for rule in d["spec"]["rules"]}
                observed.add((h, t["secretName"]))
    assert observed
    return {(ns, h, key) for h, key in observed}


def test_reviewed_tls_pins_agree_with_separately_rendered_releases():
    """Require bidirectional parity: neither an unpinned source nor an orphan pin."""
    import yaml

    from ci.quality.public_web import CATALOG

    apps = "blog cats format-quorum grafana-mcp img-proxy lms monori n8n pr-agent remark42 schoolbot socrat-bot socrat-home spi-triage syncthing umami uptime-kuma venice-api wiki-runtime wishlist".split()
    observed = set().union(*(_release_tls_records(app) for app in apps))
    policy = yaml.safe_load(CATALOG.read_text())["hosts"]
    pinned = {
        (ns, host, settings["tlsSourceName"])
        for ns, hosts in policy.items()
        for host, settings in hosts.items()
        if "tlsSourceName" in settings
    }
    assert observed == pinned
