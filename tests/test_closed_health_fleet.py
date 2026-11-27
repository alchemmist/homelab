"""Guard the Argo-rendered loopback listener boundary."""

import subprocess
from copy import deepcopy
from pathlib import Path
from typing import NamedTuple, Self

import pytest
import yaml

from ci.quality.closed_root_backend import Obj, entries, plain, view
from ci.quality.closed_root_owners import eligible, owner_render

ROOT = Path(__file__).resolve().parents[1]

FLEET_OWNERS = frozenset(
    {
        "closed-health-argocd",
        "closed-health-img",
        "closed-health-umami",
        "closed-health-remark42",
        "closed-health-venice-api",
    }
)
# Index of the format-quorum egress rule inside the rendered policy.
QUORUM_EGRESS_POSITION = 2
# Socket timeout the phase probe must apply to every phase.
PROBE_TIMEOUT_SECONDS = 6
# The closed chart renders exactly one loopback Deployment per entrance.
HEALTH_DEPLOYMENT_COUNT = 3


def _other_objects(raw: bytes) -> list[Obj]:
    # Verified HTTPS has its own policy/file and independent transition test.
    return [
        doc
        for doc in yaml.safe_load_all(raw)
        if plain(view(view(doc).get("metadata", {})).get("name", "")) not in FLEET_OWNERS
    ]


class Fleet(NamedTuple):
    """The per-group policies, the shared config map and the loopback Deployments."""

    policy: Obj
    wiki_policy: Obj
    monori_policy: Obj
    lms_policy: Obj
    wishlist_policy: Obj
    status_policy: Obj
    config: Obj
    deployments: list[Obj]


def _render_fleet(args: list[str]) -> Fleet:
    (
        policy,
        wiki_policy,
        monori_policy,
        lms_policy,
        wishlist_policy,
        status_policy,
        config,
        *deployments,
    ) = _other_objects(subprocess.check_output(args))
    return Fleet(
        policy,
        wiki_policy,
        monori_policy,
        lms_policy,
        wishlist_policy,
        status_policy,
        config,
        deployments,
    )


def _http_of(cm: Obj) -> Obj:
    data = view(cm["data"])
    return view(view(yaml.safe_load(plain(data["dynamic.yaml"])))["http"])


def _assert_peer_egress(fleet: Fleet) -> list[tuple[object, object, object]]:
    """Enumerate every egress peer with its exact port contract."""
    pspec = view(fleet.policy["spec"])
    assert fleet.policy["kind"] == "NetworkPolicy"
    assert pspec["ingress"] == []
    wspec = view(fleet.wiki_policy["spec"])
    assert wspec["podSelector"] == pspec["podSelector"]
    assert wspec["policyTypes"] == ["Egress"]
    assert len(entries(wspec["egress"])) == 1
    peers = []
    for rule in [
        *entries(pspec["egress"])[:-1],
        *entries(wspec["egress"]),
        entries(pspec["egress"])[-1],
    ]:
        vrule = view(rule)
        (peer,) = entries(vrule["to"])
        vpeer = view(peer)
        peers.append(
            (
                view(vpeer["namespaceSelector"])["matchLabels"],
                view(vpeer["podSelector"])["matchLabels"],
                vrule["ports"],
            )
        )
    assert peers == [
        (
            {"kubernetes.io/metadata.name": "schoolbot"},
            {
                "app.kubernetes.io/instance": "schoolbot",
                "app.kubernetes.io/name": "schoolbot",
            },
            [{"port": 8000, "protocol": "TCP"}],
        ),
        (
            {"kubernetes.io/metadata.name": "blog"},
            {"app.kubernetes.io/instance": "blog", "app.kubernetes.io/name": "blog"},
            [{"port": 8080, "protocol": "TCP"}],
        ),
        (
            {"kubernetes.io/metadata.name": "format-quorum"},
            {
                "app.kubernetes.io/instance": "format-quorum",
                "app.kubernetes.io/name": "format-quorum",
            },
            [{"port": 3000, "protocol": "TCP"}],
        ),
        (
            {"kubernetes.io/metadata.name": "wiki"},
            {
                "app.kubernetes.io/name": "hugo-docs-wiki",
                "app.kubernetes.io/instance": "wiki-runtime",
            },
            [{"port": 8080, "protocol": "TCP"}],
        ),
        (
            {"kubernetes.io/metadata.name": "kube-system"},
            {"k8s-app": "kube-dns"},
            [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
        ),
    ]
    return peers


def _assert_dynamic_routing(fleet: Fleet, http: Obj) -> None:
    """Check the single ConfigMap for exactly the reviewed routers and services."""
    assert fleet.config["kind"] == "ConfigMap"
    assert http["routers"] == {
        **{
            a: {
                "entryPoints": ["closed"],
                "rule": f"Host(`{a}.alchemmist.xyz`) && PathPrefix(`/`)",
                "service": a,
            }
            for a in ("lms", "wishlist")
        },
        **{
            k: {
                "entryPoints": ["closed"],
                "rule": f"Host(`{host}`) && PathPrefix(`/`)",
                "service": "status-policy",
            }
            for k, host in [
                ("status", "status.alchemmist.xyz"),
                ("status-redirect", "kuma.socrat.alchemmist.xyz"),
            ]
        },
        "monori": {
            "entryPoints": ["closed"],
            "rule": "Host(`monori.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "monori",
        },
        "wiki": {
            "entryPoints": ["closed"],
            "rule": "Host(`wiki.socrat.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "wiki",
        },
        "format-quorum": {
            "entryPoints": ["closed"],
            "rule": "Host(`fq.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "format-quorum",
        },
        "www-blog": {
            "entryPoints": ["closed"],
            "rule": "Host(`www.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "www-blog",
        },
        "health": {
            "entryPoints": ["closed"],
            "rule": "Host(`inform.sch1357.ru`) && Method(`GET`) && Path(`/api/health`)",
            "service": "schoolbot",
        },
    }
    services = view(http["services"])
    assert view(view(services["schoolbot"])["loadBalancer"])["servers"] == [
        {"url": "http://schoolbot.schoolbot.svc.cluster.local:80"}
    ]
    assert view(view(services["www-blog"])["loadBalancer"])["servers"] == [
        {"url": "http://blog.blog.svc.cluster.local:80"}
    ]


def _assert_owner_release(
    chart: Path, blog: str, peers: list[tuple[object, object, object]]
) -> None:
    """Compare the actual owner's release, not merely our own duplicate rule."""
    spec = view(yaml.safe_load((ROOT / "deploy/argocd/apps/blog.yaml").read_text()))
    source = view(spec["spec"])
    src_section = view(source["source"])
    helm = view(src_section["helm"])
    chart_path = ROOT / plain(src_section["path"])
    assert not helm["parameters"]
    assert plain(view(source["destination"])["namespace"]) == "blog"
    (release_values,) = [plain(v) for v in entries(helm["valueFiles"])]
    assert (chart_path / release_values).resolve() == (chart / blog).resolve()
    owner = _other_objects(
        subprocess.check_output(
            [
                "helm",
                "template",
                plain(helm["releaseName"]),
                str(chart_path),
                "-n",
                "blog",
                "-f",
                str(chart_path / release_values),
            ]
        )
    )
    (ing,) = [d for d in owner if d and d["kind"] == "Ingress"]
    (svc,) = [d for d in owner if d and d["kind"] == "Service"]
    ispec = view(ing["spec"])
    imeta = view(ing["metadata"])
    assert ispec["ingressClassName"] == "traefik"
    assert view(imeta["labels"])["homelab.alchemmist.xyz/public-web"] == "true"
    assert set(view(imeta["annotations"])) == {"cert-manager.io/cluster-issuer"}
    (www,) = [
        rule for rule in entries(ispec["rules"]) if view(rule)["host"] == "www.alchemmist.xyz"
    ]
    assert view(view(www)["http"])["paths"] == [
        {
            "path": "/",
            "pathType": "Prefix",
            "backend": {"service": {"name": "blog", "port": {"number": 80}}},
        }
    ]
    ssvc = view(svc["spec"])
    assert view(svc["metadata"])["name"] == "blog"
    assert ssvc["selector"] == peers[1][1]
    assert ssvc["ports"] == [{"name": "http", "port": 80, "targetPort": 8080}]


def _assert_owner_opt_outs(args: list[str], fleet: Fleet, http: Obj) -> None:
    """Check that owner opt-out flags withdraw only the blog routes."""
    pspec = view(fleet.policy["spec"])
    for overrides in (
        ("--set", "closedBlog=false"),
        ("--set-string", "closedBlog=true"),
        ("--set", "ingress.publicWeb=false"),
        ("--set-string", "ingress.publicWeb=true"),
        ("--set", "ingress.className=private"),
        ("--set-json", 'ingress.hosts=["alchemmist.xyz"]'),
        ("--set", "service.targetPort=9999"),
    ):
        egress = entries(pspec["egress"])
        (
            blocked_policy,
            still_wiki,
            still_monori,
            lm,
            wl,
            _st,
            blocked_config,
            *unchanged,
        ) = _other_objects(subprocess.check_output([*args, *overrides]))
        assert (lm, wl) == (fleet.lms_policy, fleet.wishlist_policy)
        assert still_monori == fleet.monori_policy
        assert still_wiki == fleet.wiki_policy
        assert unchanged == fleet.deployments
        assert view(blocked_policy["spec"])["egress"] == [
            egress[0],
            *egress[2:],
        ]
        restricted = _http_of(blocked_config)
        assert restricted == {
            "routers": {k: v for k, v in view(http["routers"]).items() if k != "www-blog"},
            "services": {k: v for k, v in view(http["services"]).items() if k != "www-blog"},
        }


def _assert_quorum_withdrawal(args: list[str], fleet: Fleet, http: Obj) -> None:
    """Assert that enabling the quorum keeps every other reviewed shape byte-identical."""
    policy_off, _wiki, _monori, _lm, _wl, _st, config_off, *unchanged = _other_objects(
        subprocess.check_output(
            [
                *args[:-2],
                "--set",
                "closedWiki=true,closedMonori=true,closedLms=true,closedWishlist=true,"
                "closedStatus=true,closedStatusRedirect=true",
                "--set-string",
                "closedFormatQuorum=true",
            ]
        )
    )
    assert unchanged == fleet.deployments
    egress = entries(view(fleet.policy["spec"])["egress"])
    assert view(policy_off["spec"])["egress"] == [
        r for i, r in enumerate(egress) if i != QUORUM_EGRESS_POSITION
    ]
    after = _http_of(config_off)
    for section in ("routers", "services"):
        section_map = view(http[section])
        assert view(after[section]) == {
            k: v for k, v in section_map.items() if k != "format-quorum"
        }


def _assert_wiki_withdrawal(args: list[str], fleet: Fleet, http: Obj) -> None:
    """Assert that turning the wiki off removes only its own policy and route."""
    policy_off, _wiki, _monori, _lm, _wl, _st, config_off, *unchanged = _other_objects(
        subprocess.check_output([*args, "--set", "closedWiki=false"])
    )
    assert unchanged == fleet.deployments
    assert policy_off == fleet.policy
    assert view(_wiki["spec"]) == {**view(fleet.wiki_policy["spec"]), "egress": []}
    off = _http_of(config_off)
    for section in ("routers", "services"):
        section_map = view(http[section])
        assert view(off[section]) == {k: v for k, v in section_map.items() if k != "wiki"}


def _assert_monori_withdrawal(args: list[str], fleet: Fleet, http: Obj) -> None:
    """Verify the monori grant is one exact peer; opting out leaves everything else."""
    pspec = view(fleet.policy["spec"])
    assert view(fleet.monori_policy["spec"]) == {
        "podSelector": pspec["podSelector"],
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "monori"}
                        },
                        "podSelector": {"matchLabels": {"app": "monori"}},
                    }
                ],
                "ports": [{"port": 8000, "protocol": "TCP"}],
            }
        ],
    }
    assert view(http["services"])["monori"] == {
        "loadBalancer": {"servers": [{"url": "http://monori.monori.svc.cluster.local:80"}]}
    }
    pol, wp, _mp, _lm, _wl, _st, cm, *ds = _other_objects(
        subprocess.check_output([*args, "--set", "closedMonori=false"])
    )
    assert (pol, wp, ds) == (fleet.policy, fleet.wiki_policy, fleet.deployments)
    assert view(_mp["spec"]) == {**view(fleet.monori_policy["spec"]), "egress": []}
    assert _http_of(cm) == {
        section: {k: v for k, v in view(http[section]).items() if k != "monori"}
        for section in ("routers", "services")
    }


def _assert_grants_and_opt_outs(args: list[str], fleet: Fleet, http: Obj) -> None:
    """Verify that LMS and wishlist own one exact peer each and opt-outs stay local."""
    pspec = view(fleet.policy["spec"])
    for a, bit, grant in [
        ("lms", "closedLms", fleet.lms_policy),
        ("wishlist", "closedWishlist", fleet.wishlist_policy),
    ]:
        assert view(grant["spec"]) == {
            "podSelector": pspec["podSelector"],
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": a}
                            },
                            "podSelector": {
                                "matchLabels": {
                                    "app.kubernetes.io/name": a,
                                    "app.kubernetes.io/instance": a,
                                }
                            },
                        }
                    ],
                    "ports": [{"port": 8000, "protocol": "TCP"}],
                }
            ],
        }
        assert view(view(http["services"])[a]) == {
            "loadBalancer": {"servers": [{"url": f"http://{a}.{a}.svc.cluster.local:80"}]}
        }
        (*policies, cm) = [
            d
            for d in _other_objects(subprocess.check_output([*args, "--set", bit + "=false"]))
            if d["kind"] != "Deployment"
        ]
        for off, on in zip(
            policies,
            [
                fleet.policy,
                fleet.wiki_policy,
                fleet.monori_policy,
                fleet.lms_policy,
                fleet.wishlist_policy,
                fleet.status_policy,
            ],
            strict=True,
        ):
            ospec = view(on["spec"])
            assert off == ({**on, "spec": {**ospec, "egress": []}} if on == grant else on)
        assert _http_of(cm) == {
            section: {k: v for k, v in view(http[section]).items() if k != a}
            for section in ("routers", "services")
        }


def _assert_status_matrix(args: list[str], fleet: Fleet, http: Obj) -> None:
    """Verify the status grant and its redirect route follow the two flags exactly."""
    pspec = view(fleet.policy["spec"])
    sspec = view(fleet.status_policy["spec"])
    assert sspec == {
        "podSelector": pspec["podSelector"],
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "uptime-kuma"}
                        },
                        "podSelector": {"matchLabels": {"app": "public-web-kuma-proxy"}},
                    }
                ],
                "ports": [{"port": 8080, "protocol": "TCP"}],
            }
        ],
    }
    assert view(http["services"])["status-policy"] == {
        "loadBalancer": {
            "passHostHeader": True,
            "servers": [{"url": "http://public-web-kuma-proxy.uptime-kuma.svc.cluster.local:80"}],
        }
    }
    for status, redirect in [(False, True), (True, False), (False, False)]:
        opts = f"closedStatus={str(status).lower()},closedStatusRedirect={str(redirect).lower()}"
        (*policies, sp, cm) = [
            d
            for d in _other_objects(subprocess.check_output([*args, "--set", opts]))
            if d["kind"] != "Deployment"
        ]
        assert policies == [
            fleet.policy,
            fleet.wiki_policy,
            fleet.monori_policy,
            fleet.lms_policy,
            fleet.wishlist_policy,
        ]
        assert view(sp)["spec"] == (sspec if status or redirect else {**sspec, "egress": []})
        after = _http_of(cm)
        remove = set()
        if not status:
            remove.add("status")
        if not redirect:
            remove.add("status-redirect")
        assert view(after)["routers"] == {
            k: v for k, v in view(http["routers"]).items() if k not in remove
        }
        assert view(after)["services"] == {
            k: v
            for k, v in view(http["services"]).items()
            if k != "status-policy" or status or redirect
        }


def _assert_deployments(fleet: Fleet, catalog: Obj) -> None:
    """Assert every loopback Deployment is a node-pinned, port-less Traefik pod."""
    placement = {}
    for deployment in fleet.deployments:
        assert deployment["kind"] == "Deployment"
        template = view(view(deployment["spec"])["template"])
        spec = view(template["spec"])
        labels = view(view(template["metadata"])["labels"])
        assert labels["app"] == "closed-health"
        placement[plain(labels["entrance"])] = plain(
            view(view(spec)["nodeSelector"])["kubernetes.io/hostname"]
        )
        assert not spec.get("hostNetwork")
        assert not spec["automountServiceAccountToken"]
        assert spec["volumes"] == [{"name": "routes", "configMap": {"name": "closed-health"}}]
        (container,) = entries(spec["containers"])
        cview = view(container)
        assert not cview.get("ports")
        cargs = [plain(a) for a in entries(cview["args"])]
        assert [a for a in cargs if a.startswith("--entrypoints")] == [
            "--entrypoints.closed.address=127.0.0.1:8181",
            "--entrypoints.pulse.address=127.0.0.1:8182",
        ]
        assert [a for a in cargs if a.startswith("--providers")] == [
            "--providers.file.directory=/route"
        ]
    assert placement == {k: plain(view(v)["node"]) for k, v in view(catalog["replicas"]).items()}


def test_effective_health_fleet() -> None:
    spec = view(yaml.safe_load((ROOT / "deploy/argocd/apps/closed-health.yaml").read_text()))
    app = view(spec["spec"])
    source = view(app["source"])
    chart = ROOT / plain(source["path"])
    helm = view(source["helm"])
    blog, fq, values = (plain(item) for item in entries(helm["valueFiles"]))
    catalog = view(yaml.safe_load((chart / values).read_text()))
    args = [
        "helm",
        "template",
        "closed-health",
        str(chart),
        "-f",
        str(chart / blog),
        "-f",
        str(chart / fq),
        "-f",
        str(chart / values),
        # exercise enabled and withdrawn shapes even after an owner opt-out
        "--set",
        "closedFormatQuorum=true,closedWiki=true,closedMonori=true,"
        "closedLms=true,closedWishlist=true,closedStatus=true,"
        "closedStatusRedirect=true",
    ]
    assert view(app["destination"])["namespace"] == "public-health-staging"
    fleet = _render_fleet(args)
    http = _http_of(fleet.config)
    peers = _assert_peer_egress(fleet)
    _assert_dynamic_routing(fleet, http)
    _assert_owner_release(chart, blog, peers)
    _assert_owner_opt_outs(args, fleet, http)
    _assert_quorum_withdrawal(args, fleet, http)
    _assert_wiki_withdrawal(args, fleet, http)
    _assert_monori_withdrawal(args, fleet, http)
    _assert_grants_and_opt_outs(args, fleet, http)
    _assert_status_matrix(args, fleet, http)
    _assert_deployments(fleet, catalog)


def test_format_quorum_admission_matches_owner_release() -> None:
    from ci.quality.closed_root_owners import OUTPUT, render

    assert OUTPUT.read_text() == render()


def _clear_ingress_labels(row: Obj) -> None:
    view(view(row["metadata"])["labels"]).clear()


def _add_auth_middleware(row: Obj) -> None:
    view(view(row["metadata"])["annotations"]).update(
        {"traefik.ingress.kubernetes.io/router.middlewares": "auth"}
    )


def _clear_ingress_paths(row: Obj) -> None:
    rules = entries(view(row["spec"])["rules"])
    http = view(view(rules[0])["http"])
    entries(view(http)["paths"]).clear()


def _make_service_external_name(row: Obj) -> None:
    view(row["spec"]).update({"type": "ExternalName"})


def _retarget_service_port(row: Obj) -> None:
    ports = entries(view(row["spec"])["ports"])
    view(ports[0]).update({"targetPort": 80})


def test_format_quorum_withdraws_unreviewed_owner_changes() -> None:
    from ci.quality.closed_root_owners import APP, eligible
    from ci.quality.public_web import CATALOG

    command = [
        "helm",
        "template",
        APP,
        str(ROOT / "charts" / APP),
        "-n",
        APP,
        "-f",
        str(ROOT / "deploy" / APP / "values.yaml"),
        "--set",
        "ingress.publicWeb=true",
    ]
    rows = [r for r in yaml.safe_load_all(subprocess.check_output(command)) if r]
    catalog = yaml.safe_load(CATALOG.read_text())
    assert eligible(rows, catalog)
    for kind, mutate in [
        ("Ingress", _clear_ingress_labels),
        ("Ingress", _add_auth_middleware),
        ("Ingress", _clear_ingress_paths),
        ("Service", _make_service_external_name),
        ("Service", _retarget_service_port),
    ]:
        changed = deepcopy(rows)
        mutate(next(r for r in changed if view(r)["kind"] == kind))
        assert not eligible(changed, catalog)
    assert not eligible([*rows, {"kind": "HTTPRoute"}], catalog)


def _flip_wiki_public_env(row: Obj) -> None:
    template = view(view(row["spec"])["template"])
    spec = view(template["spec"])
    container = entries(view(spec)["containers"])[0]
    envs = entries(view(container)["env"])
    target = next(x for x in envs if view(x)["name"] == "WIKI_PUBLIC")
    view(target).update(value="false")


def _widen_wiki_container_port(row: Obj) -> None:
    template = view(view(row["spec"])["template"])
    spec = view(template["spec"])
    container = entries(view(spec)["containers"])[0]
    ports_entry = entries(view(container)["ports"])[0]
    view(ports_entry).update(containerPort=9999)


def _privatize_wiki_service(row: Obj) -> None:
    view(row["metadata"]).update(namespace="private")


def test_wiki_requires_public_runtime_and_unmodified_named_backend() -> None:
    from ci.quality.closed_root_owners import eligible, owner_render
    from ci.quality.public_web import CATALOG

    rows = owner_render(owner="wiki-runtime")
    catalog = yaml.safe_load(CATALOG.read_text())
    for kind, change in [
        ("Deployment", _flip_wiki_public_env),
        ("Deployment", _widen_wiki_container_port),
        ("Service", _privatize_wiki_service),
        ("Ingress", _clear_ingress_labels),
        ("Ingress", _add_auth_middleware),
    ]:
        changed = deepcopy(rows)
        change(next(d for d in changed if view(d)["kind"] == kind))
        assert not eligible(changed, catalog, owner="wiki-runtime")
    chart = ROOT / "deploy/wiki-runtime/chart"
    raw = subprocess.check_output(
        [
            "helm",
            "template",
            "wiki-runtime",
            str(chart),
            "-n",
            "wiki",
            "-f",
            str(chart / "../values.yaml"),
            "--set",
            "visibility=private",
        ]
    )
    assert not eligible([r for r in yaml.safe_load_all(raw) if r], catalog, owner="wiki-runtime")


def _rename_workload_label(row: Obj) -> None:
    template = view(view(row["spec"])["template"])
    meta = view(template["metadata"])
    view(meta["labels"]).update(app="monori")


def _retarget_selector_to_monori_back(row: Obj) -> None:
    view(view(row["spec"])["selector"]).update(app="monori-back")


def _rename_ingress_backend_service(row: Obj) -> None:
    rule_zero = entries(view(row["spec"])["rules"])[0]
    http = view(view(rule_zero)["http"])
    path_zero = view(entries(view(http)["paths"])[0])
    backend = view(path_zero["backend"])
    view(backend["service"]).update(name="monori-sync")


def _widen_monori_container_port(row: Obj) -> None:
    template = view(view(row["spec"])["template"])
    spec = view(template["spec"])
    container = entries(view(spec)["containers"])[0]
    ports_entry = entries(view(container)["ports"])[0]
    view(ports_entry).update(containerPort=8010)


def _drop_ingress_labels(row: Obj) -> None:
    view(row["metadata"]).pop("labels", None)


def test_monori_front_only_no_shared_port_authorization() -> None:
    from ci.quality.closed_root_owners import eligible, owner_render
    from ci.quality.public_web import CATALOG

    rows = owner_render(owner="monori")
    catalog = yaml.safe_load(CATALOG.read_text())
    for kind, name, change in [
        ("Deployment", "monori-back", _rename_workload_label),
        ("Service", "monori", _retarget_selector_to_monori_back),
        ("Ingress", "monori", _rename_ingress_backend_service),
        ("Deployment", "monori", _widen_monori_container_port),
        ("Ingress", "monori", _drop_ingress_labels),
    ]:
        changed = deepcopy(rows)
        target = next(
            d
            for d in changed
            if view(d)["kind"] == kind and view(view(d)["metadata"])["name"] == name
        )
        change(target)
        assert not eligible(changed, catalog, owner="monori")


def _drop_public_web_opt_in(row: Obj) -> None:
    view(view(row["metadata"])["labels"]).pop("homelab.alchemmist.xyz/public-web", None)


def _add_oidc_middleware(row: Obj) -> None:
    view(view(row["metadata"])["annotations"]).update(
        {"traefik.ingress.kubernetes.io/router.middlewares": "oidc"}
    )


def _set_service_target_metrics(row: Obj) -> None:
    ports = entries(view(row["spec"])["ports"])
    view(ports[0]).update({"targetPort": "metrics"})


def _broaden_wishlist_image_selector(row: Obj) -> None:
    view(view(row["spec"])["selector"]).update(
        {"app.kubernetes.io/name": "wishlist-image-optimizer"}
    )


def _widen_health_container_port(row: Obj) -> None:
    template = view(view(row["spec"])["template"])
    spec = view(template["spec"])
    container = entries(view(spec)["containers"])[0]
    ports_entry = entries(view(container)["ports"])[0]
    view(ports_entry).update(containerPort=8001)


def test_lms_and_wishlist_reject_side_channels_and_unselected_routes() -> None:
    from ci.quality.closed_root_owners import eligible, owner_render
    from ci.quality.public_web import CATALOG

    catalog = yaml.safe_load(CATALOG.read_text())
    for app in ("lms", "wishlist"):
        rows = owner_render(owner=app)
        for kind, mutate in [
            ("Ingress", _drop_public_web_opt_in),
            ("Ingress", _add_oidc_middleware),
            ("Service", _set_service_target_metrics),
            ("Service", _broaden_wishlist_image_selector),
            ("Deployment", _widen_health_container_port),
        ]:
            changed = deepcopy(rows)
            target = next(
                d
                for d in changed
                if view(d)["kind"] == kind and view(view(d)["metadata"])["name"] == app
            )
            mutate(target)
            assert not eligible(changed, catalog, owner=app)


def test_argo_uses_only_the_verified_https_upstream_or_withdraws_completely() -> None:
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/closed-health.yaml").read_text())["spec"]
    src = app["source"]
    chart = ROOT / src["path"]
    args = [
        "helm",
        "template",
        "closed-health",
        str(chart),
        "-n",
        app["destination"]["namespace"],
    ]
    for f in src["helm"]["valueFiles"]:
        args += ["-f", str(chart / f)]

    def render(flag: str, value: str) -> dict[tuple[object, object], Obj]:
        return {
            (o["kind"], o["metadata"]["name"]): o
            for o in yaml.safe_load_all(
                subprocess.check_output([*args, flag, "closedArgo=" + value])
            )
            if o
        }

    active = render("--set", "true")
    policy = view(active["NetworkPolicy", "closed-health-argocd"]["spec"])
    assert policy["egress"] == [
        {
            "to": [
                {
                    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "argocd"}},
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "argocd-server",
                            "app.kubernetes.io/instance": "argo-cd",
                        }
                    },
                }
            ],
            "ports": [{"port": 8080, "protocol": "TCP"}],
        }
    ]
    assert policy["policyTypes"] == ["Egress"]
    assert policy["podSelector"] == {"matchLabels": {"app": "closed-health"}}
    content = yaml.safe_load(
        plain(view(active["ConfigMap", "closed-health"]["data"]).pop("argocd.yaml"))
    )
    assert content == {
        "http": {
            "routers": {
                "argocd": {
                    "entryPoints": ["closed"],
                    "rule": "Host(`argocd.socrat.alchemmist.xyz`) && PathPrefix(`/`)",
                    "service": "argocd",
                }
            },
            "services": {
                "argocd": {
                    "loadBalancer": {
                        "passHostHeader": True,
                        "serversTransport": "argocd-verified-tls",
                        "servers": [
                            {"url": "https://argo-cd-argocd-server.argocd.svc.cluster.local:443"}
                        ],
                    }
                }
            },
            "serversTransports": {
                "argocd-verified-tls": {
                    "serverName": "argocd.socrat.alchemmist.xyz",
                    "insecureSkipVerify": False,
                }
            },
        }
    }
    policy["egress"] = []
    assert active == render("--set", "false") == render("--set-string", "true")


def _mark_row_changed(row: Obj) -> None:
    view(row["metadata"])["labels"] = {"changed": "true"}


def test_img_only_reaches_the_reviewed_nginx_listener() -> None:
    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())
    docs = owner_render(owner="img-proxy")

    def admit(rows: list[Obj]) -> bool:
        return eligible(rows, catalog, owner="img-proxy")

    assert admit(docs)
    for kind, name in [
        ("Deployment", "img-proxy"),
        ("ConfigMap", "img-proxy-nginx"),
        ("ConfigMap", "img-proxy-service-vpn"),
    ]:
        rows = deepcopy(docs)
        target = next(d for d in rows if (d["kind"], view(d["metadata"])["name"]) == (kind, name))
        _mark_row_changed(target)
        assert not admit(rows)
    assert not admit([*docs, deepcopy(docs[-1])])
    args = [
        "helm",
        "template",
        "closed-health",
        str(ROOT / "deploy/public-web/closed-health"),
        "-n",
        "public-health-staging",
        "-f",
        str(ROOT / "deploy/public-web/entrances.yaml"),
    ]

    def render(flag: str, val: str) -> dict[tuple[object, object], Obj]:
        return {
            (d["kind"], d["metadata"]["name"]): d
            for d in yaml.safe_load_all(subprocess.check_output([*args, flag, "closedImg=" + val]))
            if d
        }

    active = render("--set", "true")
    pol = view(active["NetworkPolicy", "closed-health-img"]["spec"])
    assert pol["egress"] == [
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "img-proxy"}
                    },
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "img-proxy",
                            "app.kubernetes.io/instance": "img-proxy",
                        }
                    },
                }
            ],
            "ports": [{"port": 8080, "protocol": "TCP"}],
        }
    ]
    dynamic = view(
        view(
            yaml.safe_load(
                plain(view(active["ConfigMap", "closed-health"]["data"]).pop("img.yaml"))
            )
        )["http"]
    )
    assert view(dynamic)["routers"] == {
        "img": {
            "entryPoints": ["closed"],
            "rule": "Host(`img.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "img",
        }
    }
    assert view(dynamic)["services"] == {
        "img": {
            "loadBalancer": {
                "passHostHeader": True,
                "servers": [{"url": "http://img-proxy.img-proxy.svc.cluster.local:80"}],
            }
        }
    }
    pol["egress"] = []
    assert active == render("--set", "false") == render("--set-string", "true")


@pytest.mark.parametrize(
    ("app", "bit", "port"),
    [
        ("umami", "closedUmami", 3000),
        ("remark42", "closedRemark", 8080),
        ("venice-api", "closedVenice", 8080),
    ],
)
def test_selected_app_only_reaches_its_reviewed_http_listener(
    app: str, bit: str, port: int
) -> None:
    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())
    docs = owner_render(owner=app)

    def admit(rows: list[Obj]) -> bool:
        return eligible(rows, catalog, owner=app)

    assert admit(docs)
    venice = app == "venice-api"
    peer = "venice-browser-candidate" if venice else app
    host = "venice.socrat.alchemmist.xyz" if venice else f"{app}.alchemmist.xyz"
    rows = deepcopy(docs)
    deployment = next(
        d for d in rows if d["kind"] == "Deployment" and view(d["metadata"])["name"] == peer
    )
    template = view(view(deployment["spec"])["template"])
    pod_spec = view(template["spec"])
    runner = next(
        c
        for c in entries(pod_spec["containers"])
        if view(c)["name"] == ("bridge" if venice else app)
    )
    (runner_port,) = entries(view(runner)["ports"])
    view(runner_port)["containerPort"] = 3001
    assert not admit(rows)
    assert not admit([*docs, deepcopy(docs[-1])])
    args = [
        "helm",
        "template",
        "closed-health",
        str(ROOT / "deploy/public-web/closed-health"),
        "-n",
        "public-health-staging",
        "-f",
        str(ROOT / "deploy/public-web/entrances.yaml"),
    ]

    def render(flag: str, val: str) -> dict[tuple[object, object], Obj]:
        return {
            (d["kind"], d["metadata"]["name"]): d
            for d in yaml.safe_load_all(subprocess.check_output([*args, flag, bit + "=" + val]))
            if d
        }

    active = render("--set", "true")
    pol = view(active["NetworkPolicy", f"closed-health-{app}"]["spec"])
    assert pol["egress"] == [
        {
            "to": [
                {
                    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": app}},
                    "podSelector": {
                        "matchLabels": {
                            "app": peer,
                        }
                    },
                }
            ],
            "ports": [{"port": port, "protocol": "TCP"}],
        }
    ]
    dynamic = view(
        view(
            yaml.safe_load(
                plain(view(active["ConfigMap", "closed-health"]["data"]).pop(f"{app}.yaml"))
            )
        )["http"]
    )
    assert view(dynamic)["routers"] == {
        app: {
            "entryPoints": ["closed"],
            "rule": f"Host(`{host}`) && PathPrefix(`/`)",
            "service": app,
        }
    }
    assert view(dynamic)["services"] == {
        app: {
            "loadBalancer": {
                "passHostHeader": True,
                "servers": [
                    {"url": f"http://{app}.{app}.svc.cluster.local:{8080 if venice else 80}"}
                ],
            }
        }
    }
    pol["egress"] = []
    assert active == render("--set", "false") == render("--set-string", "true")


def test_schoolbot_sample_requires_complete_json_http_response() -> None:
    from ci.quality.closed_schoolbot_samples import classify

    raw = (
        b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n"
        b'Content-Length: 11\r\n\r\n{"ok":true}'
    )
    assert classify(raw) == "healthy"
    for bad in (
        b"",
        raw[:-1],
        raw.replace(b"200 OK", b"504 Gateway Timeout"),
        raw.replace(b"application/json", b"text/html"),
        raw.replace(b"true", b"null"),
        b"x" * 8193,
    ):
        assert classify(bad) != "healthy"


@pytest.mark.parametrize(
    ("mode", "query"),
    [
        ("named", "schoolbot.schoolbot.svc.cluster.local"),
        ("absolute", "schoolbot.schoolbot.svc.cluster.local."),
        ("numeric", None),
        ("listener", None),
    ],
)
def test_schoolbot_phases_report_only_fixed_target_timing(
    monkeypatch: pytest.MonkeyPatch, mode: str, query: None | str
) -> None:
    import io
    import socket

    from ci.quality import schoolbot_phase_probe as probe

    vip = "10.43.0.1"
    expected = ("127.0.0.1", 8181) if mode == "listener" else (vip, 80)
    lookups: list[str] = []

    def resolve(name: str, *_args: object) -> list[tuple[None, None, None, None, tuple[str, int]]]:
        lookups.append(name)
        return [(None, None, None, None, (vip, 80))]

    class Sock:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def settimeout(self, t: int) -> None:
            assert t == PROBE_TIMEOUT_SECONDS

        def connect(self, address: tuple[str, int]) -> None:
            assert address == expected

        def sendall(self, data: bytes) -> None:
            assert (
                data == b"GET /api/health HTTP/1.0\r\nHost: inform.sch1357.ru\r\n"
                b"Connection: close\r\n\r\n"
            )

        def makefile(self, *_args: object) -> io.BytesIO:
            return io.BytesIO(
                b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n"
                b'Content-Length: 11\r\n\r\n{"ok":true}'
            )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "socket", lambda *_args: Sock())
    r = probe.sample(mode, vip)
    assert r.pop("outcome") == "healthy"
    assert lookups == ([query] if query else [])
    assert set(r) == {"tcp_ms", "headers_ms", "body_ms"} | ({"dns_ms"} if query else set())
    assert all(isinstance(v, (int, float)) and v >= 0 for v in r.values())
    if query:
        monkeypatch.setattr(socket, "getaddrinfo", lambda *_args: [])
        assert probe.sample(mode, vip)["outcome"] == "unexpected-dns"
    with pytest.raises(ValueError, match="unexpected probe destination"):
        probe.sample(mode, "127.0.0.1")


@pytest.mark.parametrize(
    "drift",
    [
        "narrow",
        "middleware",
        "alias",
        "no-opt-in",
        "selector",
        "port",
        "second-container",
        "second-workload",
    ],
)
def test_blog_render_drift_withholds_www(drift: str) -> None:
    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())
    docs = owner_render(owner="blog")
    assert eligible(docs, catalog, owner="blog")
    ing = view(next(d for d in docs if d["kind"] == "Ingress"))
    svc = view(next(d for d in docs if d["kind"] == "Service"))
    dep = view(next(d for d in docs if d["kind"] == "Deployment"))
    template = view(view(dep["spec"])["template"])
    pod_spec = view(template["spec"])
    containers = entries(pod_spec["containers"])
    if drift == "narrow":
        rules = entries(view(ing["spec"])["rules"])
        http = view(view(rules[1])["http"])
        paths = entries(view(http)["paths"])
        view(paths[0])["path"] = "/articles"
    elif drift == "middleware":
        view(view(ing["metadata"])["annotations"])[
            "traefik.ingress.kubernetes.io/router.middlewares"
        ] = "blog-login"
    elif drift == "alias":
        rules = entries(view(ing["spec"])["rules"])
        view(rules[0])["host"] = "other.alchemmist.xyz"
    elif drift == "no-opt-in":
        view(view(ing["metadata"])["labels"]).clear()
    elif drift == "selector":
        view(view(svc["spec"])["selector"]).pop("app.kubernetes.io/instance")
    elif drift == "port":
        port_zero = view(entries(view(containers[0])["ports"])[0])
        view(port_zero)["containerPort"] = 9000
    elif drift == "second-container":
        containers.append({"name": "sidecar"})
    else:
        docs.append(deepcopy(dep))
    assert not eligible(docs, catalog, owner="blog")


def test_tcp_resolver_changes_only_closed_pod_resolver_options() -> None:
    chart = ROOT / "deploy/public-web/closed-health"
    args = [
        "helm",
        "template",
        "closed-health",
        str(chart),
        "-n",
        "public-health-staging",
    ]
    for f in (
        "deploy/blog/values.yaml",
        "deploy/public-web/closed-root-owners.yaml",
        "deploy/public-web/entrances.yaml",
    ):
        args += ["-f", str(ROOT / f)]

    def render(*opts: str) -> list[Obj]:
        return [d for d in yaml.safe_load_all(subprocess.check_output([*args, *opts])) if d]

    default = render()
    assert default == render("--set", "useTcpResolver=false")
    candidate = render("--set", "useTcpResolver=true")
    deploys = [d for d in candidate if d["kind"] == "Deployment"]
    assert len(deploys) == HEALTH_DEPLOYMENT_COUNT
    for d in deploys:
        pod_spec = view(view(view(d["spec"])["template"])["spec"])
        assert pod_spec.pop("dnsConfig") == {"options": [{"name": "use-vc"}]}
    assert candidate == default
    bad = subprocess.run(
        [*args, "--set-string", "useTcpResolver=true"], capture_output=True, check=False
    )
    assert bad.returncode
    assert b"useTcpResolver must be a boolean" in bad.stderr
