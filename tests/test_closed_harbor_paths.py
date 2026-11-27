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
