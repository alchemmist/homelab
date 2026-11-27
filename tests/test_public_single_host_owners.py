"""A release opts in one existing ordinary route, never its replacement hostname."""

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LABEL = "homelab.alchemmist.xyz/public-web"


@pytest.mark.parametrize(
    ("app", "field", "replacement"),
    [
        ("schoolbot", "ingress.host", "bot.sch1357.ru"),
        ("monori", "host", "private.invalid"),
    ],
)
def test_owner_opt_in_changes_only_one_ingress_label(app, field, replacement):
    def render(*options, release=True):
        args = ["helm", "template", app, str(ROOT / "charts" / app), "-n", app]
        if release:
            args += ["-f", str(ROOT / "deploy" / app / "values.yaml")]
        return list(
            yaml.safe_load_all(subprocess.check_output([*args, *options], text=True))
        )

    def ingress(docs):
        (row,) = [r for r in docs if r and r["kind"] == "Ingress"]
        return row

    active = render()
    owner = ingress(active)
    (host,) = [r["host"] for r in owner["spec"]["rules"]]
    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())[
        "hosts"
    ][app]
    release_values = yaml.safe_load((ROOT / "deploy" / app / "values.yaml").read_text())
    assert release_values["publicWebHost"] == host
    assert catalog[host].get("route", "web") == "web"
    assert owner["spec"]["tls"][0]["hosts"] == [host]
    expected = render("--set-string", "publicWebHost=")
    labels = ingress(expected)["metadata"].setdefault("labels", {})
    assert LABEL not in labels
    labels[LABEL] = "true"
    assert active == expected
    replaced = render("--set-string", f"{field}={replacement}")
    changed = ingress(replaced)["spec"]
    assert [r["host"] for r in changed["rules"]] == [replacement]
    assert changed["tls"][0]["hosts"] == [replacement]
    for docs in [replaced, render(release=False)]:
        assert LABEL not in ingress(docs)["metadata"].get("labels", {})


def test_openhands_selects_the_oidc_proxy_not_the_native_ingress():
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/openhands.yaml").read_text())[
        "spec"
    ]
    src = app["source"]
    chart = ROOT / src["path"]
    helm = src["helm"]
    args = [
        "helm",
        "template",
        helm["releaseName"],
        str(chart),
        "-n",
        app["destination"]["namespace"],
    ]
    for file in helm["valueFiles"]:
        args.extend(["-f", str(chart / file)])

    def run(*opts):
        return subprocess.run(
            args + list(opts), capture_output=True, text=True, check=False
        )

    def render(*opts):
        result = run(*opts)
        assert result.returncode == 0
        return [r for r in yaml.safe_load_all(result.stdout) if r]

    def owner(docs):
        (ing,) = [r for r in docs if r["kind"] == "Ingress"]
        return ing

    selected = render()
    ing = owner(selected)
    assert (
        ing["metadata"]["namespace"] == "identity"
        and ing["metadata"]["name"] == "openhands-oidc"
    )
    host = "openhands.socrat.alchemmist.xyz"
    (rule,) = ing["spec"]["rules"]
    (route,) = rule["http"]["paths"]
    assert rule["host"] == host and route == {
        "path": "/",
        "pathType": "Prefix",
        "backend": {"service": {"name": "openhands-oidc", "port": {"number": 4180}}},
    }
    assert ing["metadata"].pop("labels") == {LABEL: "true"}
    ann = ing["metadata"]["annotations"]
    assert all(
        ann["traefik.ingress.kubernetes.io/router.observability." + field] == "false"
        for field in ("accesslogs", "tracing")
    )
    for pin in ["", "other.invalid"]:
        assert render("--set-string", "oidc.publicWebHost=" + pin) == selected
    invalid = run("--set", "ingress.enabled=true")
    assert invalid.returncode and "native unprotected ingress" in invalid.stderr

    peer_opts = ("--set", "oidc.allowPublicEntryPeer=true")
    assert render("--set", "oidc.allowPublicEntryPeer=false") == render()
    permitted = render(*peer_opts)
    (policy,) = [
        d
        for d in permitted
        if d["kind"] == "NetworkPolicy"
        and d["metadata"].get("namespace") == "identity"
        and d["metadata"]["name"] == "openhands-oidc-public-entry"
    ]
    assert policy["spec"]["podSelector"] == {"matchLabels": {"app": "openhands-oidc"}}
    (incoming,) = policy["spec"]["ingress"]
    assert incoming["ports"] == [{"port": 4180, "protocol": "TCP"}]
    assert policy["spec"]["policyTypes"] == ["Ingress"]
    (peer,) = incoming["from"]
    assert peer == {
        "namespaceSelector": {
            "matchLabels": {"kubernetes.io/metadata.name": "public-entry"}
        },
        "podSelector": {
            "matchLabels": {"homelab.alchemmist.xyz/public-entry-controller": "true"}
        },
    }
    policy["spec"]["ingress"] = []
    assert permitted == render()
    # With prune disabled, even turning off OIDC must overwrite the previous grant.
    refused = run(*peer_opts, "--set", "oidc.enabled=false")
    assert refused.returncode and "requires the protected OIDC frontdoor" in refused.stderr
    disabled = render(*peer_opts, "--set", "oidc.enabled=false", "--set-json", "config.extraEnv=[]")
    assert policy in disabled
    assert not any(d["kind"] == "Ingress" for d in disabled)
    for value in ("true", "false"):
        bad = run("--set-string", "oidc.allowPublicEntryPeer=" + value)
        assert bad.returncode and "must be boolean" in bad.stderr
    wrong = run(*peer_opts, "--set-string", "oidc.publicWebHost=other.invalid")
    assert wrong.returncode and "requires the selected OIDC hostname" in wrong.stderr
