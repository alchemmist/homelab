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
