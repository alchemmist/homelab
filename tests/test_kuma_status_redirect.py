"""Source contracts for the read-only Gatus proxy that preserves legacy Kuma URLs."""

import pytest

from tests.public_entry_contract import assert_read_only_status_policy, render


@pytest.fixture(scope="module")
def rendered_policy() -> str:
    """Inspect the ConfigMap actually emitted by the owner chart, without a cluster."""
    [config] = [d for d in render("uptime-kuma") if d["kind"] == "ConfigMap"]
    return config["data"]["nginx.conf"]


def test_public_read_only_status_and_legacy_https_redirect(
    rendered_policy: str,
) -> None:
    """The only proxy pass is inside the allowlist; socket, push and admin paths default to 404."""
    assert_read_only_status_policy(rendered_policy)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "upstream kuma {",
            "upstream kuma { server dummy.invalid:80; }\nupstream unused {",
        ),
        ("gatus.uptime-kuma.svc.cluster.local:80", "dummy.invalid:80"),
        ("^(GET|HEAD)$", "^(GET|HEAD|POST)$"),
        ("endpoints/|suites/|favicon", "socket.io|endpoints/|suites/|favicon"),
        ("return 302 /;", "return 302 http://gatus:8080/;"),
        ("location / { return 404; }", "location / { proxy_pass http://kuma; }"),
    ],
)
def test_proxy_rejects_unsafe_mutations(
    rendered_policy: str, old: str, new: str
) -> None:
    """Mutate the real policy only after passing the positive control."""
    assert_read_only_status_policy(rendered_policy)
    assert old in rendered_policy
    with pytest.raises(AssertionError):
        assert_read_only_status_policy(rendered_policy.replace(old, new))


def test_exact_status_owner_label_preserves_readonly_proxy_and_legacy_redirect():
    import subprocess

    import yaml

    from tests.public_entry_contract import ROOT

    app = yaml.safe_load((ROOT / "deploy/argocd/apps/uptime-kuma.yaml").read_text())[
        "spec"
    ]
    src = app["source"]
    helm = src["helm"]
    base = [
        "helm",
        "template",
        helm["releaseName"],
        str(ROOT / src["path"]),
        "-n",
        app["destination"]["namespace"],
    ]
    def parameters(*, omit=()):
        options = []
        for p in helm["parameters"]:
            if p["name"] in omit:
                continue
            flag = "--set-string" if p.get("forceString", False) else "--set"
            options.extend([flag, p["name"] + "=" + p["value"]])
        return options

    options = parameters()

    def docs(args):
        return list(yaml.safe_load_all(subprocess.check_output(base + args, text=True)))

    def reader(objects):
        (obj,) = [
            d
            for d in objects
            if d and d["kind"] == "Ingress" and d["metadata"]["name"] == "uptime-kuma"
        ]
        return obj

    key = "homelab.alchemmist.xyz/public-web"
    expected = docs(parameters(omit={"publicStatusHost"}))
    labels = reader(expected)["metadata"].setdefault("labels", {})
    assert key not in labels
    labels[key] = "true"
    current = docs(options)
    assert expected == current
    (rule,) = reader(current)["spec"]["rules"]
    assert rule["host"] == "status.alchemmist.xyz"
    (route,) = rule["http"]["paths"]
    assert route["backend"]["service"] == {
        "name": "public-web-kuma-proxy",
        "port": {"number": 80},
    }
    retained = [p for p in helm["parameters"] if p["name"] != "host"]
    assert [p["value"] for p in retained if p["name"] == "publicStatusHost"] == [rule["host"]]
    mismatched = parameters(omit={"host"})
    changed = reader(docs([*mismatched, "--set-string", "host=other.invalid"]))
    assert changed["spec"]["rules"][0][
        "host"
    ] == "other.invalid" and key not in changed["metadata"].get("labels", {})
    invalid = subprocess.run(
        [*base, *options, "--set", "publicEntry.kumaPolicyProxy.enabled=false"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode and "read-only policy proxy" in invalid.stderr
