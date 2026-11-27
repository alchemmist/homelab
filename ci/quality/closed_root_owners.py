"""Compile narrowly reviewed root HTTP admissions from the owner's complete Argo render."""

import argparse
import hashlib
import json
from collections.abc import Mapping

import yaml

from ci.quality.closed_argocd_backend import eligible as argo_eligible
from ci.quality.closed_root_backend import entries, plain, view
from ci.quality.closed_status_owner import render_status
from ci.quality.common import command
from ci.quality.public_web import CATALOG, ROOT

PINNED_OWNER_DOCS = 6
PINNED_VENICE_DOCS = 8

APP = "format-quorum"
HOST = "fq.alchemmist.xyz"
PIN = "format-quorum-tls"
OUTPUT = ROOT / "deploy/public-web/closed-root-owners.yaml"


# Namespace, resource name, approved host, pin, Service port, upstream port,
# target Pod selector. This table is reviewed; a new label cannot add entries.
ROOTS = {
    "blog": (
        "blog",
        "blog",
        "www.alchemmist.xyz",
        "blog-tls",
        80,
        8080,
        {"app.kubernetes.io/name": "blog", "app.kubernetes.io/instance": "blog"},
    ),
    **{
        app: (
            app,
            app,
            app + ".alchemmist.xyz",
            app + "-tls",
            80,
            "http" if app == "wishlist" else 8000,
            {"app.kubernetes.io/name": app, "app.kubernetes.io/instance": app},
        )
        for app in ("lms", "wishlist")
    },
    "venice-api": (
        "venice-api",
        "venice-api",
        "venice.socrat.alchemmist.xyz",
        "venice-api-tls",
        8080,
        8080,
        {"app": "venice-browser-candidate"},
    ),
    "remark42": (
        "remark42",
        "remark42",
        "remark42.alchemmist.xyz",
        "remark42-tls",
        80,
        "http",
        {"app": "remark42"},
    ),
    "umami": ("umami", "umami", "umami.alchemmist.xyz", "umami-tls", 80, "http", {"app": "umami"}),
    "img-proxy": (
        "img-proxy",
        "img-proxy",
        "img.alchemmist.xyz",
        "img-proxy-tls",
        80,
        8080,
        {"app.kubernetes.io/name": "img-proxy", "app.kubernetes.io/instance": "img-proxy"},
    ),
    APP: (
        APP,
        APP,
        HOST,
        PIN,
        80,
        3000,
        {"app.kubernetes.io/name": APP, "app.kubernetes.io/instance": APP},
    ),
    "wiki-runtime": (
        "wiki",
        "wiki-runtime-wiki",
        "wiki.socrat.alchemmist.xyz",
        "wiki-tls",
        8080,
        "http",
        {"app.kubernetes.io/name": "hugo-docs-wiki", "app.kubernetes.io/instance": "wiki-runtime"},
    ),
    "monori": (
        "monori",
        "monori",
        "monori.alchemmist.xyz",
        "monori-tls",
        80,
        "http",
        {"app": "monori"},
    ),
}


def eligible(
    items: list[dict[str, object]], catalog: dict[str, object], *, owner: str = APP
) -> bool:
    """Only translate the complete reviewed root matcher and exact upstream contract."""
    ns, name, host, pin, svc_port, target_port, selector = ROOTS[owner]
    wiki = owner == "wiki-runtime"
    hosts = view(view(catalog["hosts"]).get(ns, {}))
    if hosts.get(host) != {"dns": "managed", "tlsSourceName": pin}:
        return False
    if owner in {"img-proxy", "remark42"}:
        # One two-container Pod; review the nginx privacy config and VPN sidecar
        # together. No additional workload may share this egress selector.
        expected = {
            (
                "Deployment",
                name,
            ): "bb0ef4b596a4f0bb90a0fc72a7b87133ae738dababe15b620c653b516ef8e289",
            (
                "ConfigMap",
                name + "-nginx",
            ): "28c2a1c488724fe2cf5c512099c2f1685e0df6d7f5895407272553cc7cfb03fe",
            (
                "ConfigMap",
                name + "-service-vpn",
            ): "216f150e896b366e654ce19af866c9f889891a76ea0e7223b369ebbfca41dcc2",
        }
        extras = {("ServiceAccount", name)}
        if owner == "remark42":
            # The reviewed Deployment binds the named http port to remark42,
            # not to its service-vpn sidecar. Do not inspect credential data.
            expected = {
                (
                    "Deployment",
                    name,
                ): "66a16c5179a637242696d942f7194cf6b2fd0341953b1364357a6693c0146ce6",
                (
                    "ConfigMap",
                    name + "-service-vpn",
                ): "6ba92ac4527c162edec3905471eb6407d09ac8ad41b235ab12c0237bf5953f12",
            }
            extras = {("Secret", name + "-env"), ("PersistentVolumeClaim", name + "-data")}
        keys = [(plain(d["kind"]), plain(view(d["metadata"])["name"])) for d in items]
        if len(keys) != PINNED_OWNER_DOCS or set(keys) != set(expected) | extras | {
            ("Ingress", name),
            ("Service", name),
        }:
            return False
        for key, d in zip(keys, items, strict=True):
            if (
                key in expected
                and hashlib.sha256(
                    json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                != expected[key]
            ):
                return False
    if owner == "venice-api":
        # Only bridge HTTP, never browser control or egress. A switch back to
        # the legacy Deployment needs a separate review rather than a fallback.
        candidate = "venice-browser-candidate"
        reviewed = {
            (
                "Deployment",
                candidate,
            ): "4430a4c9ff1d1c7d34c0a98c9b643f6b65d279536058a6a48232203b0b7463d5",
            (
                "Deployment",
                name,
            ): "a5368ef5565848ea7879f09381b4908f24984e80d6e5c78139fdafb256409336",
            (
                "NetworkPolicy",
                candidate,
            ): "3cc89643dcaa890398f1cbd1c4ad5a210a22c0a433d03040b5027f91ed5dbec4",
        }
        keys = [(plain(d["kind"]), plain(view(d["metadata"])["name"])) for d in items]
        if len(keys) != PINNED_VENICE_DOCS or set(keys) != set(reviewed) | {
            ("Ingress", name),
            ("Service", name),
            ("ServiceAccount", name),
            ("StorageClass", "venice-browser-retain"),
            ("PersistentVolumeClaim", "venice-browser-profile"),
        }:
            return False
        for key, d in zip(keys, items, strict=True):
            if (
                key in reviewed
                and hashlib.sha256(
                    json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                != reviewed[key]
            ):
                return False
    if owner == "umami" and sorted(
        (plain(d["kind"]), plain(view(d["metadata"])["name"])) for d in items
    ) != [
        ("Deployment", name),
        ("Ingress", name),
        ("Service", name),
    ]:
        return False
    if owner == "blog" and sorted(
        (plain(d["kind"]), plain(view(d["metadata"])["name"])) for d in items
    ) != [
        ("Deployment", name),
        ("Ingress", name),
        ("Service", name),
        ("ServiceAccount", name),
    ]:
        return False
    owners = [view(d) for d in items if plain(d["kind"]) == "Ingress"]
    services = [
        view(d)
        for d in items
        if plain(d["kind"]) == "Service" and plain(view(d["metadata"])["name"]) == name
    ]
    if (
        len(owners) != 1
        or len(services) != 1
        or any(
            plain(d["kind"]) in {"IngressRoute", "HTTPRoute", "IngressRouteTCP", "TLSRoute"}
            for d in items
        )
    ):
        return False
    ing, svc = owners[0], services[0]
    if any(
        plain(view(d["metadata"])["name"]) != name
        or view(d["metadata"]).get("namespace", ns if wiki else None) != ns
        for d in (ing, svc)
    ):
        return False
    if (
        (target_port == "http" and owner != "remark42") or owner in {"lms", "blog"}
    ) and not _named_runtime(items, ns, name, selector, host, wiki=wiki):
        return False
    port = {"name": "http"} if wiki else {"number": svc_port}
    # Validate the complete owner Ingress. Only www is emitted by the closed chart.
    source_hosts = ["alchemmist.xyz", host] if owner == "blog" else [host]
    ing_meta = view(ing["metadata"])
    svc_meta = view(svc["metadata"])
    ing_spec = view(ing["spec"])
    svc_spec = view(svc["spec"])
    return bool(
        ing["apiVersion"] == "networking.k8s.io/v1"
        and svc["apiVersion"] == "v1"
        and view(ing_meta.get("labels", {})).get("homelab.alchemmist.xyz/public-web") == "true"
        and ing_meta.get("annotations") == {"cert-manager.io/cluster-issuer": "letsencrypt-http01"}
        and ing_spec
        == {
            "ingressClassName": "traefik",
            "tls": [{"hosts": source_hosts, "secretName": pin}],
            "rules": [
                {
                    "host": source_host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {"service": {"name": name, "port": port}},
                            }
                        ]
                    },
                }
                for source_host in source_hosts
            ],
        }
        and not svc_meta.get("annotations")
        and svc_spec
        == {
            "selector": selector,
            "ports": [
                {
                    "name": "http",
                    "port": svc_port,
                    "targetPort": target_port,
                },
                *(
                    [{"name": "metrics", "port": 8001, "targetPort": "metrics"}]
                    if owner == "wishlist"
                    else []
                ),
            ],
        }
    )


def _carries_labels(item: dict[str, object], selector: Mapping[str, object]) -> bool:
    """Compare the workload template labels to the reviewed selector."""
    template = view(view(item["spec"])["template"])
    labels = view(view(template.get("metadata", {})).get("labels", {}))
    return all(labels.get(k) == v for k, v in selector.items())


def _named_runtime(
    items: list[dict[str, object]],
    ns: str,
    name: str,
    selector: Mapping[str, object],
    host: str,
    *,
    wiki: bool,
) -> bool:
    """Check the single reviewed workload that may receive public traffic."""
    workloads = []
    kinds = {"Deployment", "DaemonSet", "StatefulSet", "Job", "ReplicaSet"}
    for doc in items:
        item = view(doc)
        if (
            plain(item["kind"]) in kinds
            and view(item["metadata"]).get("namespace", ns) == ns
            and _carries_labels(item, selector)
        ):
            workloads.append(item)
    if (
        len(workloads) != 1
        or plain(workloads[0]["kind"]) != "Deployment"
        or plain(view(workloads[0]["metadata"])["name"]) != name
    ):
        return False
    template = view(view(workloads[0]["spec"])["template"])
    pod = view(template["spec"])
    containers = entries(pod["containers"])
    if (
        view(template["metadata"])["labels"] != selector
        or pod.get("hostNetwork")
        or len(containers) != 1
    ):
        return False
    c = view(containers[0])
    if ns == "blog":
        return bool(c["name"] == name and c.get("ports") == [{"containerPort": 8080}])
    if ns == "umami":
        return bool(
            c["name"] == name
            and c.get("ports") == [{"name": "http", "containerPort": 3000}]
            and not c.get("args")
            and not c.get("command")
        )
    if ns == "wishlist":
        return bool(
            c["name"] == ns
            and c.get("ports")
            == [
                {"name": "http", "containerPort": 8000},
                {"name": "metrics", "containerPort": 8001},
            ]
        )
    if ns == "lms":
        return bool(c["name"] == ns and c.get("ports") == [{"containerPort": 8000}])
    if not wiki:
        return bool(
            c["name"] == "front" and c.get("ports") == [{"name": "http", "containerPort": 8000}]
        )
    return bool(
        c["name"] == "wiki"
        and c.get("ports") == [{"name": "http", "containerPort": 8080}]
        and [view(v) for v in entries(c["env"]) if view(v)["name"] == "WIKI_PUBLIC"]
        == [{"name": "WIKI_PUBLIC", "value": "true"}]
        and [view(v) for v in entries(c["env"]) if view(v)["name"] == "PUBLIC_ORIGIN"]
        == [{"name": "PUBLIC_ORIGIN", "value": "https://" + host}]
    )


def owner_render(*, owner: str = APP) -> list[dict[str, object]]:
    """Render the reviewed upstream Helm release for one root owner."""
    ns = ROOTS[owner][0]
    release = owner
    path, file = (
        ("deploy/wiki-runtime/chart", "../values.yaml")
        if owner == "wiki-runtime"
        else (f"charts/{owner}", f"../../deploy/{owner}/values.yaml")
    )
    spec = yaml.safe_load((ROOT / f"deploy/argocd/apps/{release}.yaml").read_text())["spec"]
    src = spec["source"]
    files = [file, "alert-graphs.values.yaml"] if owner == "lms" else [file]
    if owner in {"img-proxy", "umami", "remark42"}:
        files = []
    params = src.get("helm", {}).get("parameters", [])
    reviewed_params: list[list[dict[str, str]]] = [[]]
    if owner in {"lms", "wishlist", "img-proxy", "umami", "remark42", "venice-api"}:
        reviewed_params.extend([[{"name": "publicWeb", "value": v}] for v in ("true", "false")])
    if (
        params not in reviewed_params
        or "sources" in spec
        or src
        != {
            "repoURL": "https://github.com/alchemmist/homelab.git",
            "targetRevision": "main",
            "path": path,
            "helm": {
                "releaseName": release,
                **({"valueFiles": files} if files else {}),
                "parameters": params,
            },
        }
        or spec["destination"] != {"namespace": ns, "server": "https://kubernetes.default.svc"}
    ):
        reason = "unreviewed owner release inputs"
        raise ValueError(reason)
    chart = ROOT / path
    argv = ["helm", "template", release, str(chart), "-n", ns]
    for value_file in files:
        argv.extend(["-f", str(chart / value_file)])
    for param in params:
        argv.extend(["--set", param["name"] + "=" + param["value"]])
    raw = command(argv).stdout
    return [d for d in yaml.safe_load_all(raw) if d]


def render() -> str:
    """Render the complete reviewed closed-root owners YAML."""
    catalog = yaml.safe_load(CATALOG.read_text())
    bits = {
        k: eligible(owner_render(owner=w), catalog, owner=w)
        for k, w in [
            ("closedBlog", "blog"),
            ("closedFormatQuorum", APP),
            ("closedWiki", "wiki-runtime"),
            ("closedMonori", "monori"),
            ("closedVenice", "venice-api"),
            ("closedRemark", "remark42"),
            ("closedUmami", "umami"),
            ("closedImg", "img-proxy"),
            ("closedLms", "lms"),
            ("closedWishlist", "wishlist"),
        ]
    }
    bits.update(render_status(catalog))
    bits["closedArgo"] = argo_eligible(catalog)
    return "# Generated by python -m ci.quality.closed_root_owners\n" + yaml.safe_dump(bits)


def main() -> int:
    """Check or rewrite the generated closed-root owners manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = render()
    if args.check:
        return int(not OUTPUT.is_file() or OUTPUT.read_text() != value)
    OUTPUT.write_text(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
