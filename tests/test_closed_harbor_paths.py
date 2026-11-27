import subprocess
from copy import deepcopy

import pytest
import yaml

from ci.quality.closed_harbor_paths import CATALOG, HOST, compile_fixture, owner_command


@pytest.fixture(scope="module")
def inputs():
    return [
        d for d in yaml.safe_load_all(subprocess.check_output(owner_command())) if d
    ], yaml.safe_load(CATALOG.read_text())


def test_literal_prefix_and_native_tls_only(inputs):
    http = compile_fixture(*inputs, source_strict=False)["http"]
    routers = http["routers"]
    assert len(routers) == 5 and set(http["services"]) == {
        "harbor-portal",
        "harbor-core",
    }
    for path in ["/api/", "/service/", "/v2/", "/c/", "/"]:
        rule = f"Host(`{HOST}`) && PathPrefix(`{path}`)"
        assert routers["harbor-" + (path.strip("/") or "portal")] == {
            "entryPoints": ["closedsecure"],
            "tls": {},
            "priority": len(rule),
            "rule": rule,
            "service": "harbor-" + ("portal" if path == "/" else "core"),
        }
    for mode in (None, True, 0):
        with pytest.raises(ValueError):
            compile_fixture(*inputs, source_strict=mode)


@pytest.mark.parametrize(
    "drift",
    [
        "neighbor",
        "no-prefix",
        "lost-slash",
        "http",
        "opt-out",
        "middleware",
        "service",
        "namespace",
        "catalog",
    ],
)
def test_no_partial_portal_fallback(inputs, drift):
    docs, catalog = deepcopy(inputs)
    ing = next(d for d in docs if d["kind"] == "Ingress")
    paths = ing["spec"]["rules"][0]["http"]["paths"]
    svc = next(
        d
        for d in docs
        if d["kind"] == "Service" and d["metadata"]["name"] == "harbor-core"
    )
    meta = ing["metadata"]
    if drift == "neighbor":
        docs.append(deepcopy(ing))
    elif drift == "no-prefix":
        paths.pop(0)
    elif drift == "lost-slash":
        paths[2]["path"] = "/v2"
    elif drift == "http":
        meta["annotations"]["traefik.ingress.kubernetes.io/router.entrypoints"] = "web"
    elif drift == "opt-out":
        meta["labels"].pop("homelab.alchemmist.xyz/public-web")
    elif drift == "middleware":
        meta["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"] = "auth"
    elif drift == "service":
        svc["spec"]["ports"][0]["targetPort"] = 5000
    elif drift == "namespace":
        svc["metadata"]["namespace"] = "other"
    else:
        catalog["hosts"]["harbor"].pop(HOST)
    with pytest.raises(ValueError):
        compile_fixture(docs, catalog, source_strict=False)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "broader-root",
        "callback-prefix",
        "extra-path",
        "port",
        "selector",
        "backend",
        "annotation",
        "no-opt-in",
        "mode",
        "tls",
    ],
)
def test_socrat_bot_exact_set_or_no_fixture(fault):
    from ci.quality import closed_socrat_bot_paths as bot

    docs = bot.render()
    catalog = yaml.safe_load(bot.CATALOG.read_text())
    (ing,) = [d for d in docs if d["kind"] == "Ingress"]
    (svc,) = [
        d for d in docs if d["kind"] == "Service" and d["metadata"]["name"] == bot.NS
    ]
    paths = ing["spec"]["rules"][0]["http"]["paths"]
    if fault == "broader-root":
        paths[1]["pathType"] = "Prefix"
    elif fault == "callback-prefix":
        paths[2]["pathType"] = "Prefix"
    elif fault == "extra-path":
        paths.append(paths[-1])
    elif fault == "port":
        svc["spec"]["ports"][0]["targetPort"] = 8080
    elif fault == "selector":
        del svc["spec"]["selector"]["app.kubernetes.io/component"]
    elif fault == "backend":
        paths[0]["backend"]["service"]["name"] = "socrat-telegram-relay"
    elif fault == "annotation":
        ing["metadata"]["annotations"][
            "traefik.ingress.kubernetes.io/router.priority"
        ] = "1"
    elif fault == "no-opt-in":
        ing["metadata"]["labels"]["homelab.alchemmist.xyz/public-web"] = "false"
    elif fault == "tls":
        ing["spec"]["tls"][0]["secretName"] = "other"
    if fault:
        with pytest.raises(ValueError):
            bot.fixture(docs, catalog, strict=fault == "mode")
        return
    config = bot.fixture(docs, catalog, strict=False)["http"]
    assert len(config["routers"]) == 5 and set(config["services"]) == {"bot"}
    assert config["routers"]["bot-root"]["rule"].endswith(" && Path(`/`)")
    assert config["routers"]["bot-telegram"]["rule"].endswith(
        " && PathPrefix(`/telegram`)"
    )
    assert config["routers"]["bot-oauth-callback"]["rule"].endswith(
        " && Path(`/oauth/callback`)"
    )
