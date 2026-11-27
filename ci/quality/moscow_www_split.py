"""Compile the closed www/relay split only. Never bind a host socket or read real keys."""

from ipaddress import IPv4Address, IPv4Network

WWW = "www.alchemmist.xyz"
VPN = "vpn.alchemmist.xyz"


def fixture(route, blog, service):
    spec = route["spec"]
    m = route["metadata"]
    b = blog["spec"]
    s = service["spec"]
    selector = {"app.kubernetes.io/name": "blog", "app.kubernetes.io/instance": "blog"}
    if (
        any(o["metadata"].get("deletionTimestamp") for o in (route, blog, service))
        or m.get("annotations", {}).get("kubernetes.io/ingress.class") != "traefik-moscow"
        or m.get("labels", {}).get("homelab.alchemmist.xyz/moscow-rehearsal") != "true"
    ):
        raise ValueError("route selection changed")
    if (route["kind"], route["apiVersion"], m["namespace"], m["name"]) != (
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
        raise ValueError("TCP owner changed")
    if (
        blog["kind"] != "Ingress"
        or blog["apiVersion"] != "networking.k8s.io/v1"
        or blog["metadata"].get("labels", {}).get("homelab.alchemmist.xyz/public-web") != "true"
        or any(
            k.startswith("traefik.")
            for o in (blog, service)
            for k in o["metadata"].get("annotations", {})
        )
        or blog["metadata"]["namespace"] != "blog"
        or blog["metadata"]["name"] != "blog"
        or b.get("ingressClassName") != "traefik"
        or b["tls"] != [{"secretName": "blog-tls", "hosts": ["alchemmist.xyz", WWW]}]
    ):
        raise ValueError("blog owner changed")
    rules = [r for r in b["rules"] if r.get("host") == WWW]
    paths = [
        {
            "path": "/",
            "pathType": "Prefix",
            "backend": {"service": {"name": "blog", "port": {"number": 80}}},
        }
    ]
    if len(rules) != 1 or rules[0]["http"]["paths"] != paths:
        raise ValueError("www path changed")
    if (
        service["kind"] != "Service"
        or service["metadata"]["namespace"] != "blog"
        or service["metadata"]["name"] != "blog"
        or s.get("selector") != selector
        or s.get("type") != "ClusterIP"
        or s["ports"] != [{"name": "http", "port": 80, "targetPort": 8080, "protocol": "TCP"}]
        or IPv4Address(s["clusterIP"]) not in IPv4Network("10.43.0.0/16")
    ):
        raise ValueError("blog Service changed")
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
                "blog": {"loadBalancer": {"servers": [{"url": f"http://{s['clusterIP']}:80"}]}}
            },
        },
        "tcp": {
            "routers": {
                "vpn": {
                    "entryPoints": ["websecure"],
                    "rule": spec["routes"][0]["match"],
                    "tls": {"passthrough": True},
                    "service": "fixture",
                }
            },
            "services": {
                "fixture": {"loadBalancer": {"servers": [{"address": "127.0.0.1:19443"}]}}
            },
        },
    }
