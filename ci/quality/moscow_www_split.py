"""Compile the closed www/relay split only. Never bind a host socket or read real keys."""

from ipaddress import IPv4Address, IPv4Network

from ci.quality.closed_root_backend import entries, plain, view

WWW = "www.alchemmist.xyz"
VPN = "vpn.alchemmist.xyz"
MSG_ROUTE_SELECTION = "route selection changed"
MSG_TCP_OWNER = "TCP owner changed"
MSG_BLOG_OWNER = "blog owner changed"
MSG_WWW_PATH = "www path changed"
MSG_BLOG_SERVICE = "blog Service changed"


def fixture(route: object, blog: object, service: object) -> dict[str, object]:
    """Compile the reviewed IngressRouteTCP/Ingress split into one closed fixture."""
    route_doc = view(route)
    blog_doc = view(blog)
    service_doc = view(service)
    spec = view(route_doc["spec"])
    route_meta = view(route_doc["metadata"])
    blog_spec = view(blog_doc["spec"])
    service_spec = view(service_doc["spec"])
    selector = {"app.kubernetes.io/name": "blog", "app.kubernetes.io/instance": "blog"}
    annotations = view(route_meta.get("annotations", {})).get("kubernetes.io/ingress.class")
    opt_in = view(route_meta.get("labels", {})).get("homelab.alchemmist.xyz/moscow-rehearsal")
    if (
        any(view(view(o)["metadata"]).get("deletionTimestamp") for o in (route, blog, service))
        or annotations != "traefik-moscow"
        or opt_in != "true"
    ):
        raise ValueError(MSG_ROUTE_SELECTION)
    if (
        route_doc["kind"],
        route_doc["apiVersion"],
        route_meta["namespace"],
        route_meta["name"],
    ) != (
        "IngressRouteTCP",
        "traefik.io/v1alpha1",
        "vpn-transit",
        "moscow-tcp-443",
    ) or spec != {
        "entryPoints": ["websecure"],
        "routes": [
            {
                "match": f"HostSNI(`{VPN}`)",
                "services": [{"name": "vpn-transit", "port": "tcp-443", "nativeLB": True}],
            }
        ],
        "tls": {"passthrough": True},
    }:
        raise ValueError(MSG_TCP_OWNER)
    blog_labels = view(view(blog_doc["metadata"]).get("labels", {}))
    blog_meta = view(blog_doc["metadata"])
    if (
        blog_doc["kind"] != "Ingress"
        or blog_doc["apiVersion"] != "networking.k8s.io/v1"
        or blog_labels.get("homelab.alchemmist.xyz/public-web") != "true"
        or any(
            k.startswith("traefik.")
            for o in (blog, service)
            for k in view(view(view(o)["metadata"]).get("annotations", {}))
        )
        or blog_meta["namespace"] != "blog"
        or blog_meta["name"] != "blog"
        or blog_spec.get("ingressClassName") != "traefik"
        or blog_spec["tls"] != [{"secretName": "blog-tls", "hosts": ["alchemmist.xyz", WWW]}]
    ):
        raise ValueError(MSG_BLOG_OWNER)
    rules = [r for r in entries(blog_spec["rules"]) if view(r).get("host") == WWW]
    paths = [
        {
            "path": "/",
            "pathType": "Prefix",
            "backend": {"service": {"name": "blog", "port": {"number": 80}}},
        }
    ]
    if len(rules) != 1:
        raise ValueError(MSG_WWW_PATH)
    http = view(view(rules[0])["http"])
    if entries(http["paths"]) != paths:
        raise ValueError(MSG_WWW_PATH)
    service_meta = view(service_doc["metadata"])
    if (
        service_doc["kind"] != "Service"
        or service_meta["namespace"] != "blog"
        or service_meta["name"] != "blog"
        or service_spec.get("selector") != selector
        or service_spec.get("type") != "ClusterIP"
        or service_spec["ports"]
        != [{"name": "http", "port": 80, "targetPort": 8080, "protocol": "TCP"}]
        or IPv4Address(plain(service_spec["clusterIP"])) not in IPv4Network("10.43.0.0/16")
    ):
        raise ValueError(MSG_BLOG_SERVICE)
    cluster_ip = plain(service_spec["clusterIP"])
    tcp_match = plain(view(entries(spec["routes"])[0])["match"])
    return {
        "tls": {
            "options": {"default": {"sniStrict": True}},
            "certificates": [{"certFile": "/fixture/www.crt", "keyFile": "/fixture/www.key"}],
        },
        "http": {
            "routers": {
                "www": {
                    "entryPoints": ["websecure"],
                    "rule": f"Host(`{WWW}`)",
                    "service": "blog",
                    "tls": {},
                }
            },
            "services": {
                "blog": {"loadBalancer": {"servers": [{"url": f"http://{cluster_ip}:80"}]}}
            },
        },
        "tcp": {
            "routers": {
                "vpn": {
                    "entryPoints": ["websecure"],
                    "rule": tcp_match,
                    "tls": {"passthrough": True},
                    "service": "fixture",
                }
            },
            "services": {
                "fixture": {"loadBalancer": {"servers": [{"address": "127.0.0.1:19443"}]}}
            },
        },
    }
