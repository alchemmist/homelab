"""Guard the Argo-rendered loopback listener boundary."""

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from ci.quality.closed_root_owners import eligible, owner_render

ROOT = Path(__file__).resolve().parents[1]


def test_effective_health_fleet():
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/closed-health.yaml").read_text())[
        "spec"
    ]
    chart = ROOT / app["source"]["path"]
    blog, fq, values = app["source"]["helm"]["valueFiles"]
    catalog = yaml.safe_load((chart / values).read_text())
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
        "--set",
        "closedFormatQuorum=true,closedWiki=true,closedMonori=true,closedLms=true,closedWishlist=true,closedStatus=true,closedStatusRedirect=true",  # exercise enabled and withdrawn shapes even after an owner opt-out
    ]

    def other_objects(raw):
        # Verified HTTPS has its own policy/file and independent transition test.
        return [
            d
            for d in yaml.safe_load_all(raw)
            if d.get("metadata", {}).get("name")
            not in {
                "closed-health-argocd",
                "closed-health-img",
                "closed-health-umami",
                "closed-health-remark42",
            }
        ]

    assert app["destination"]["namespace"] == "public-health-staging"
    (
        policy,
        wiki_policy,
        monori_policy,
        lms_policy,
        wishlist_policy,
        status_policy,
        config,
        *deployments,
    ) = other_objects(subprocess.check_output(args))
    assert policy["kind"] == "NetworkPolicy" and policy["spec"]["ingress"] == []
    peers = []
    assert wiki_policy["spec"]["podSelector"] == policy["spec"]["podSelector"]
    assert wiki_policy["spec"]["policyTypes"] == ["Egress"]
    assert len(wiki_policy["spec"]["egress"]) == 1
    for rule in [
        *policy["spec"]["egress"][:-1],
        *wiki_policy["spec"]["egress"],
        policy["spec"]["egress"][-1],
    ]:
        (peer,) = rule["to"]
        peers.append(
            (
                peer["namespaceSelector"]["matchLabels"],
                peer["podSelector"]["matchLabels"],
                rule["ports"],
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
    assert config["kind"] == "ConfigMap"
    http = yaml.safe_load(config["data"]["dynamic.yaml"])["http"]
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
    assert http["services"]["schoolbot"]["loadBalancer"]["servers"] == [
        {"url": "http://schoolbot.schoolbot.svc.cluster.local:80"}
    ]
    assert http["services"]["www-blog"]["loadBalancer"]["servers"] == [
        {"url": "http://blog.blog.svc.cluster.local:80"}
    ]
    # Compare the actual owner's release, not merely our own duplicate rule.
    source = yaml.safe_load((ROOT / "deploy/argocd/apps/blog.yaml").read_text())["spec"]
    chart_path = ROOT / source["source"]["path"]
    helm = source["source"]["helm"]
    assert not helm["parameters"] and source["destination"]["namespace"] == "blog"
    (release_values,) = helm["valueFiles"]
    assert (chart_path / release_values).resolve() == (chart / blog).resolve()
    owner = list(
        other_objects(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    helm["releaseName"],
                    str(chart_path),
                    "-n",
                    "blog",
                    "-f",
                    str(chart_path / release_values),
                ]
            )
        )
    )
    (ing,) = [d for d in owner if d and d["kind"] == "Ingress"]
    (svc,) = [d for d in owner if d and d["kind"] == "Service"]
    assert ing["spec"]["ingressClassName"] == "traefik"
    assert ing["metadata"]["labels"]["homelab.alchemmist.xyz/public-web"] == "true"
    assert set(ing["metadata"]["annotations"]) == {"cert-manager.io/cluster-issuer"}
    (www,) = [
        rule for rule in ing["spec"]["rules"] if rule["host"] == "www.alchemmist.xyz"
    ]
    assert www["http"]["paths"] == [
        {
            "path": "/",
            "pathType": "Prefix",
            "backend": {"service": {"name": "blog", "port": {"number": 80}}},
        }
    ]
    assert svc["metadata"]["name"] == "blog" and svc["spec"]["selector"] == peers[1][1]
    assert svc["spec"]["ports"] == [{"name": "http", "port": 80, "targetPort": 8080}]
    for overrides in (
        ("--set", "closedBlog=false"),
        ("--set-string", "closedBlog=true"),
        ("--set", "ingress.publicWeb=false"),
        ("--set-string", "ingress.publicWeb=true"),
        ("--set", "ingress.className=private"),
        ("--set-json", 'ingress.hosts=["alchemmist.xyz"]'),
        ("--set", "service.targetPort=9999"),
    ):
        (
            blocked_policy,
            still_wiki,
            still_monori,
            lm,
            wl,
            st,
            blocked_config,
            *unchanged,
        ) = other_objects(subprocess.check_output([*args, *overrides]))
        assert (lm, wl) == (lms_policy, wishlist_policy)
        assert still_monori == monori_policy
        assert still_wiki == wiki_policy
        assert unchanged == deployments
        assert blocked_policy["spec"]["egress"] == [
            policy["spec"]["egress"][0],
            *policy["spec"]["egress"][2:],
        ]
        restricted = yaml.safe_load(blocked_config["data"]["dynamic.yaml"])["http"]
        assert restricted == {
            "routers": {k: v for k, v in http["routers"].items() if k != "www-blog"},
            "services": {k: v for k, v in http["services"].items() if k != "www-blog"},
        }
    policy_off, separate_wiki, separate_monori, lm, wl, st, config_off, *unchanged = (
        other_objects(
            subprocess.check_output(
                [
                    *args[:-2],
                    "--set",
                    "closedWiki=true,closedMonori=true,closedLms=true,closedWishlist=true,closedStatus=true,closedStatusRedirect=true",
                    "--set-string",
                    "closedFormatQuorum=true",
                ]
            )
        )
    )
    assert unchanged == deployments
    assert policy_off["spec"]["egress"] == [
        r for i, r in enumerate(policy["spec"]["egress"]) if i != 2
    ]
    after = yaml.safe_load(config_off["data"]["dynamic.yaml"])["http"]
    for section in ("routers", "services"):
        assert after[section] == {
            k: v for k, v in http[section].items() if k != "format-quorum"
        }
    policy_off, separate_wiki, separate_monori, lm, wl, st, config_off, *unchanged = (
        other_objects(subprocess.check_output([*args, "--set", "closedWiki=false"]))
    )
    assert unchanged == deployments and policy_off == policy
    assert separate_wiki["spec"] == {**wiki_policy["spec"], "egress": []}
    off = yaml.safe_load(config_off["data"]["dynamic.yaml"])["http"]
    for section in ("routers", "services"):
        assert off[section] == {k: v for k, v in http[section].items() if k != "wiki"}
    assert monori_policy["spec"] == {
        "podSelector": policy["spec"]["podSelector"],
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
    assert http["services"]["monori"] == {
        "loadBalancer": {
            "servers": [{"url": "http://monori.monori.svc.cluster.local:80"}]
        }
    }
    pol, wp, mp, lm, wl, st, cm, *ds = other_objects(
        subprocess.check_output([*args, "--set", "closedMonori=false"])
    )
    assert (pol, wp, ds) == (policy, wiki_policy, deployments) and mp["spec"] == {
        **monori_policy["spec"],
        "egress": [],
    }
    assert yaml.safe_load(cm["data"]["dynamic.yaml"])["http"] == {
        section: {k: v for k, v in http[section].items() if k != "monori"}
        for section in ("routers", "services")
    }
    for a, bit, grant in [
        ("lms", "closedLms", lms_policy),
        ("wishlist", "closedWishlist", wishlist_policy),
    ]:
        assert grant["spec"] == {
            "podSelector": policy["spec"]["podSelector"],
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
        assert http["services"][a] == {
            "loadBalancer": {
                "servers": [{"url": f"http://{a}.{a}.svc.cluster.local:80"}]
            }
        }
        (
            *policies,
            cm,
        ) = [
            d
            for d in other_objects(
                subprocess.check_output([*args, "--set", bit + "=false"])
            )
            if d["kind"] != "Deployment"
        ]
        for off, on in zip(
            policies,
            [
                policy,
                wiki_policy,
                monori_policy,
                lms_policy,
                wishlist_policy,
                status_policy,
            ],
            strict=True,
        ):
            assert off == (
                {**on, "spec": {**on["spec"], "egress": []}} if on == grant else on
            )
        assert yaml.safe_load(cm["data"]["dynamic.yaml"])["http"] == {
            section: {k: v for k, v in http[section].items() if k != a}
            for section in ("routers", "services")
        }
    assert status_policy["spec"] == {
        "podSelector": policy["spec"]["podSelector"],
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {
                                "kubernetes.io/metadata.name": "uptime-kuma"
                            }
                        },
                        "podSelector": {
                            "matchLabels": {"app": "public-web-kuma-proxy"}
                        },
                    }
                ],
                "ports": [{"port": 8080, "protocol": "TCP"}],
            }
        ],
    }
    assert http["services"]["status-policy"] == {
        "loadBalancer": {
            "passHostHeader": True,
            "servers": [
                {"url": "http://public-web-kuma-proxy.uptime-kuma.svc.cluster.local:80"}
            ],
        }
    }
    for status, redirect in [(False, True), (True, False), (False, False)]:
        opts = f"closedStatus={str(status).lower()},closedStatusRedirect={str(redirect).lower()}"
        (
            *policies,
            sp,
            cm,
        ) = [
            d
            for d in other_objects(subprocess.check_output([*args, "--set", opts]))
            if d["kind"] != "Deployment"
        ]
        assert policies == [
            policy,
            wiki_policy,
            monori_policy,
            lms_policy,
            wishlist_policy,
        ]
        assert sp["spec"] == (
            status_policy["spec"]
            if status or redirect
            else {**status_policy["spec"], "egress": []}
        )
        after = yaml.safe_load(cm["data"]["dynamic.yaml"])["http"]
        remove = set()
        if not status:
            remove.add("status")
        if not redirect:
            remove.add("status-redirect")
        assert after["routers"] == {
            k: v for k, v in http["routers"].items() if k not in remove
        }
        assert after["services"] == {
            k: v
            for k, v in http["services"].items()
            if k != "status-policy" or status or redirect
        }
    placement = {}
    for deployment in deployments:
        assert deployment["kind"] == "Deployment"
        template = deployment["spec"]["template"]
        spec = template["spec"]
        assert template["metadata"]["labels"]["app"] == "closed-health"
        placement[template["metadata"]["labels"]["entrance"]] = spec["nodeSelector"][
            "kubernetes.io/hostname"
        ]
        assert not spec.get("hostNetwork") and not spec["automountServiceAccountToken"]
        assert spec["volumes"] == [
            {"name": "routes", "configMap": {"name": "closed-health"}}
        ]
        (container,) = spec["containers"]
        assert not container.get("ports")
        assert [a for a in container["args"] if a.startswith("--entrypoints")] == [
            "--entrypoints.closed.address=127.0.0.1:8181",
            "--entrypoints.pulse.address=127.0.0.1:8182",
        ]
        assert [a for a in container["args"] if a.startswith("--providers")] == [
            "--providers.file.directory=/route"
        ]
    assert placement == {k: v["node"] for k, v in catalog["replicas"].items()}


def test_format_quorum_admission_matches_owner_release():
    from ci.quality.closed_root_owners import OUTPUT, render

    assert OUTPUT.read_text() == render()


def test_format_quorum_withdraws_unreviewed_owner_changes():

    from ci.quality.closed_root_owners import APP, CATALOG, eligible

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
        ("Ingress", lambda i: i["metadata"]["labels"].clear()),
        (
            "Ingress",
            lambda i: i["metadata"]["annotations"].update(
                {"traefik.ingress.kubernetes.io/router.middlewares": "auth"}
            ),
        ),
        ("Ingress", lambda i: i["spec"]["rules"][0]["http"]["paths"].clear()),
        ("Service", lambda s: s["spec"].update({"type": "ExternalName"})),
        ("Service", lambda s: s["spec"]["ports"][0].update({"targetPort": 80})),
    ]:
        changed = deepcopy(rows)
        mutate(next(r for r in changed if r["kind"] == kind))
        assert not eligible(changed, catalog)
    assert not eligible([*rows, {"kind": "HTTPRoute"}], catalog)


def test_wiki_requires_public_runtime_and_unmodified_named_backend():

    from ci.quality.closed_root_owners import CATALOG, eligible, owner_render

    rows = owner_render(owner="wiki-runtime")
    catalog = yaml.safe_load(CATALOG.read_text())
    for kind, change in [
        (
            "Deployment",
            lambda r: next(
                x
                for x in r["spec"]["template"]["spec"]["containers"][0]["env"]
                if x["name"] == "WIKI_PUBLIC"
            ).update(value="false"),
        ),
        (
            "Deployment",
            lambda r: r["spec"]["template"]["spec"]["containers"][0]["ports"][0].update(
                containerPort=9999
            ),
        ),
        ("Service", lambda r: r["metadata"].update(namespace="private")),
        ("Ingress", lambda r: r["metadata"]["labels"].clear()),
        (
            "Ingress",
            lambda r: r["metadata"]["annotations"].update(
                {"traefik.ingress.kubernetes.io/router.middlewares": "auth"}
            ),
        ),
    ]:
        changed = deepcopy(rows)
        change(next(d for d in changed if d["kind"] == kind))
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
    assert not eligible(
        [r for r in yaml.safe_load_all(raw) if r], catalog, owner="wiki-runtime"
    )


def test_monori_front_only_no_shared_port_authorization():

    from ci.quality.closed_root_owners import CATALOG, eligible, owner_render

    rows = owner_render(owner="monori")
    catalog = yaml.safe_load(CATALOG.read_text())
    for kind, name, change in [
        (
            "Deployment",
            "monori-back",
            lambda d: d["spec"]["template"]["metadata"]["labels"].update(app="monori"),
        ),
        (
            "Service",
            "monori",
            lambda d: d["spec"]["selector"].update(app="monori-back"),
        ),
        (
            "Ingress",
            "monori",
            lambda d: d["spec"]["rules"][0]["http"]["paths"][0]["backend"][
                "service"
            ].update(name="monori-sync"),
        ),
        (
            "Deployment",
            "monori",
            lambda d: d["spec"]["template"]["spec"]["containers"][0]["ports"][0].update(
                containerPort=8010
            ),
        ),
        ("Ingress", "monori", lambda d: d["metadata"].pop("labels", None)),
    ]:
        changed = deepcopy(rows)
        change(
            next(
                d
                for d in changed
                if d["kind"] == kind and d["metadata"]["name"] == name
            )
        )
        assert not eligible(changed, catalog, owner="monori")


def test_lms_and_wishlist_reject_side_channels_and_unselected_routes():

    from ci.quality.closed_root_owners import CATALOG, eligible, owner_render

    catalog = yaml.safe_load(CATALOG.read_text())
    for app in ("lms", "wishlist"):
        rows = owner_render(owner=app)
        for kind, mutate in [
            (
                "Ingress",
                lambda d: d["metadata"]["labels"].pop(
                    "homelab.alchemmist.xyz/public-web", None
                ),
            ),
            (
                "Ingress",
                lambda d: d["metadata"]["annotations"].update(
                    {"traefik.ingress.kubernetes.io/router.middlewares": "oidc"}
                ),
            ),
            ("Service", lambda d: d["spec"]["ports"][0].update(targetPort="metrics")),
            (
                "Service",
                lambda d: d["spec"]["selector"].update(
                    {"app.kubernetes.io/name": "wishlist-image-optimizer"}
                ),
            ),
            (
                "Deployment",
                lambda d: d["spec"]["template"]["spec"]["containers"][0]["ports"][
                    0
                ].update(containerPort=8001),
            ),
        ]:
            changed = deepcopy(rows)
            mutate(
                next(
                    d
                    for d in changed
                    if d["kind"] == kind and d["metadata"]["name"] == app
                )
            )
            assert not eligible(changed, catalog, owner=app)


def test_argo_uses_only_the_verified_https_upstream_or_withdraws_completely():
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/closed-health.yaml").read_text())[
        "spec"
    ]
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

    def render(flag, value):
        return {
            (o["kind"], o["metadata"]["name"]): o
            for o in yaml.safe_load_all(
                subprocess.check_output([*args, flag, "closedArgo=" + value])
            )
            if o
        }

    active = render("--set", "true")
    policy = active["NetworkPolicy", "closed-health-argocd"]["spec"]
    assert policy["egress"] == [
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "argocd"}
                    },
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
    assert policy["policyTypes"] == ["Egress"] and policy["podSelector"] == {
        "matchLabels": {"app": "closed-health"}
    }
    content = yaml.safe_load(
        active["ConfigMap", "closed-health"]["data"].pop("argocd.yaml")
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
                            {
                                "url": "https://argo-cd-argocd-server.argocd.svc.cluster.local:443"
                            }
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


def test_img_only_reaches_the_reviewed_nginx_listener():

    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())
    docs = owner_render(owner="img-proxy")
    admit = lambda rows: eligible(rows, catalog, owner="img-proxy")
    assert admit(docs)
    for kind, name in [
        ("Deployment", "img-proxy"),
        ("ConfigMap", "img-proxy-nginx"),
        ("ConfigMap", "img-proxy-service-vpn"),
    ]:
        rows = deepcopy(docs)
        next(d for d in rows if (d["kind"], d["metadata"]["name"]) == (kind, name))[
            "metadata"
        ]["labels"] = {"changed": "true"}
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

    def render(flag, val):
        return {
            (d["kind"], d["metadata"]["name"]): d
            for d in yaml.safe_load_all(
                subprocess.check_output([*args, flag, "closedImg=" + val])
            )
            if d
        }

    active = render("--set", "true")
    pol = active["NetworkPolicy", "closed-health-img"]["spec"]
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
    dynamic = yaml.safe_load(
        active["ConfigMap", "closed-health"]["data"].pop("img.yaml")
    )["http"]
    assert dynamic["routers"] == {
        "img": {
            "entryPoints": ["closed"],
            "rule": "Host(`img.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "img",
        }
    } and dynamic["services"] == {
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
    [("umami", "closedUmami", 3000), ("remark42", "closedRemark", 8080)],
)
def test_selected_app_only_reaches_its_reviewed_http_listener(app, bit, port):

    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())
    docs = owner_render(owner=app)
    admit = lambda rows: eligible(rows, catalog, owner=app)
    assert admit(docs)
    rows = deepcopy(docs)
    deployment = next(d for d in rows if d["kind"] == "Deployment")
    next(
        c
        for c in deployment["spec"]["template"]["spec"]["containers"]
        if c["name"] == app
    )["ports"][0]["containerPort"] = 3001
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

    def render(flag, val):
        return {
            (d["kind"], d["metadata"]["name"]): d
            for d in yaml.safe_load_all(
                subprocess.check_output([*args, flag, bit + "=" + val])
            )
            if d
        }

    active = render("--set", "true")
    pol = active["NetworkPolicy", f"closed-health-{app}"]["spec"]
    assert pol["egress"] == [
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": app}
                    },
                    "podSelector": {
                        "matchLabels": {
                            "app": app,
                        }
                    },
                }
            ],
            "ports": [{"port": port, "protocol": "TCP"}],
        }
    ]
    dynamic = yaml.safe_load(
        active["ConfigMap", "closed-health"]["data"].pop(f"{app}.yaml")
    )["http"]
    assert dynamic["routers"] == {
        app: {
            "entryPoints": ["closed"],
            "rule": f"Host(`{app}.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": app,
        }
    } and dynamic["services"] == {
        app: {
            "loadBalancer": {
                "passHostHeader": True,
                "servers": [{"url": f"http://{app}.{app}.svc.cluster.local:80"}],
            }
        }
    }
    pol["egress"] = []
    assert active == render("--set", "false") == render("--set-string", "true")


def test_schoolbot_sample_requires_complete_json_http_response():
    from ci.quality.closed_schoolbot_samples import classify

    raw = b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\n\r\n{"ok":true}'
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
    "mode,query",
    [
        ("named", "schoolbot.schoolbot.svc.cluster.local"),
        ("absolute", "schoolbot.schoolbot.svc.cluster.local."),
        ("numeric", None),
        ("listener", None),
    ],
)
def test_schoolbot_phases_report_only_fixed_target_timing(monkeypatch, mode, query):
    import io

    from ci.quality import schoolbot_phase_probe as probe

    vip = "10.43.0.1"
    expected = ("127.0.0.1", 8181) if mode == "listener" else (vip, 80)
    lookups = []

    def resolve(name, *args):
        lookups.append(name)
        return [(None, None, None, None, (vip, 80))]

    class Sock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, t):
            assert t == 6

        def connect(self, address):
            assert address == expected

        def sendall(self, data):
            assert (
                data
                == b"GET /api/health HTTP/1.0\r\nHost: inform.sch1357.ru\r\nConnection: close\r\n\r\n"
            )

        def makefile(self, *args):
            return io.BytesIO(
                b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\n\r\n{"ok":true}'
            )

    monkeypatch.setattr(probe.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(probe.socket, "socket", lambda *args: Sock())
    r = probe.sample(mode, vip)
    assert r.pop("outcome") == "healthy"
    assert lookups == ([query] if query else [])
    assert set(r) == {"tcp_ms", "headers_ms", "body_ms"} | (
        {"dns_ms"} if query else set()
    )
    assert all(v >= 0 for v in r.values())
    if query:
        monkeypatch.setattr(probe.socket, "getaddrinfo", lambda *args: [])
        assert probe.sample(mode, vip)["outcome"] == "unexpected-dns"
    with pytest.raises(ValueError):
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
def test_blog_render_drift_withholds_www(drift):
    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())
    docs = owner_render(owner="blog")
    assert eligible(docs, catalog, owner="blog")
    ing = next(d for d in docs if d["kind"] == "Ingress")
    svc = next(d for d in docs if d["kind"] == "Service")
    dep = next(d for d in docs if d["kind"] == "Deployment")
    containers = dep["spec"]["template"]["spec"]["containers"]
    if drift == "narrow":
        ing["spec"]["rules"][1]["http"]["paths"][0]["path"] = "/articles"
    elif drift == "middleware":
        ing["metadata"]["annotations"][
            "traefik.ingress.kubernetes.io/router.middlewares"
        ] = "blog-login"
    elif drift == "alias":
        ing["spec"]["rules"][0]["host"] = "other.alchemmist.xyz"
    elif drift == "no-opt-in":
        ing["metadata"]["labels"].clear()
    elif drift == "selector":
        svc["spec"]["selector"].pop("app.kubernetes.io/instance")
    elif drift == "port":
        containers[0]["ports"][0]["containerPort"] = 9000
    elif drift == "second-container":
        containers.append({"name": "sidecar"})
    else:
        docs.append(deepcopy(dep))
    assert not eligible(docs, catalog, owner="blog")


def test_tcp_resolver_changes_only_closed_pod_resolver_options():
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

    def render(*opts):
        return [
            d for d in yaml.safe_load_all(subprocess.check_output([*args, *opts])) if d
        ]

    default = render()
    assert default == render("--set", "useTcpResolver=false")
    candidate = render("--set", "useTcpResolver=true")
    deploys = [d for d in candidate if d["kind"] == "Deployment"]
    assert len(deploys) == 3
    for d in deploys:
        assert d["spec"]["template"]["spec"].pop("dnsConfig") == {
            "options": [{"name": "use-vc"}]
        }
    assert candidate == default
    bad = subprocess.run(
        [*args, "--set-string", "useTcpResolver=true"], capture_output=True
    )
    assert bad.returncode and b"useTcpResolver must be a boolean" in bad.stderr
