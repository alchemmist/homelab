#!/usr/bin/env python3
"""Render isolated same-origin branding assets; no credentials or application JS."""

import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import cast


def _collect_assets(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Verify each reviewed asset; return base64 payload by hashed name and key map."""
    assets = cast(
        "dict[str, dict[str, str]]", json.loads((root / "assets.json").read_text())
    )
    binary: dict[str, str] = {}
    names: dict[str, str] = {}
    for key, asset in assets.items():
        path = root / asset["path"]
        if path.suffix not in {".woff2", ".webp", ".avif", ".svg", ".css"}:
            message = "Only reviewed font/image/scene CSS assets may be served"
            raise ValueError(message)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != asset["sha256"]:
            message = "Asset checksum mismatch"
            raise ValueError(message)
        name = digest[:12] + "-" + path.name
        binary[name] = base64.b64encode(content).decode()
        names[key] = name
    if sum(len(base64.b64decode(value)) for value in binary.values()) > 16_000_000:
        message = "Static bundle exceeds reviewed total budget"
        raise ValueError(message)
    return binary, names


def _shard_binary(binary: dict[str, str]) -> list[dict[str, str]]:
    """Split the payload into immutable shards under the ConfigMap size limit."""
    chunks: list[dict[str, str]] = []
    chunk = {}
    size = 0
    for key, value in sorted(binary.items()):
        length = len(base64.b64decode(value))
        if length > 650_000:
            message = "Individual asset exceeds ConfigMap shard budget"
            raise ValueError(message)
        if size + length > 650_000:
            chunks.append(chunk)
            chunk, size = {}, 0
        chunk[key] = value
        size += length
    if chunk:
        chunks.append(chunk)
    return chunks


def _nature_config(root: Path, names: dict[str, str]) -> tuple[str, str]:
    """Return nginx config and locations implementing the randomized Nature photo scene."""
    random_config = ""
    random_locations = ""
    nature_file = root / "nature.json"
    if not nature_file.exists():
        return random_config, random_locations
    photos = cast("list[dict[str, str]]", json.loads(nature_file.read_text())["photos"])
    if not 2 <= len(photos) <= 100:
        message = "Nature collection must have 2..100 reviewed photos"
        raise ValueError(message)
    if len({p["id"] for p in photos}) != len(photos):
        message = "Duplicate Nature ID"
        raise ValueError(message)
    if any(not re.fullmatch("[0-9a-f]{12}", p["id"]) for p in photos):
        message = "Invalid Nature ID"
        raise ValueError(message)
    # Equal weights to two decimal places, final bucket receives rounding remainder.
    base, remainder = divmod(10000, len(photos))
    weights = [
        f" {(base + (i < remainder)) / 100:.2f}% {p['id']};"
        for i, p in enumerate(photos[:-1])
    ]
    weights.append(f" * {photos[-1]['id']};")
    # A document/request is NOT an authorization journey. Native full-page
    # redirects import CSS again. OIDC's unchanged encoded next (with state)
    # identifies that journey, without storing/logging/echoing its contents.
    # For native/error pages without next, reuse only an allowlisted cosmetic
    # photo ID. This cookie is unrelated to authentik_session and grants no
    # identity/access. No IP/UA/session-token hashing or application JS.
    random_config = r"""map $http_referer $nature_next {
 default "";
 ~^https://auth[.]socrat[.]alchemmist[.]xyz/if/flow/[^?]+[?](?:[^\s]*&)?next=(?<qm_next>[^&]+) $qm_next;
}
map $nature_next $nature_flow_seed {
 default "";
 ~*(?:%26|%3f)state%3d.+ $nature_next;
}
map $nature_flow_seed $nature_seed {
 "" $request_id;
 default $nature_flow_seed;
}
"""
    random_config += (
        'split_clients "$nature_seed" $nature_draw {\n' + "\n".join(weights) + "\n}\n"
    )
    cookie_ids = "|".join(p["id"] for p in photos)
    # $cookie_* does not normalize hyphens in cookie names like $http_*.
    random_config += (
        'map $http_cookie $nature_previous {\n default "";\n'
        ' "~(?:^|;[ ]*)__Secure-qm_nature=(?<qm_cookie>'
        + cookie_ids
        + ')(?:;|$)" $qm_cookie;\n}\n'
    )
    random_config += """map $nature_previous $nature_fallback {
 "" $nature_draw;
 default $nature_previous;
}
map $nature_flow_seed $nature_scene {
 "" $nature_fallback;
 default $nature_draw;
}
"""
    css_rows = [f" {p['id']} {names[p['sceneCss']]};" for p in photos]
    random_config += "map $nature_scene $nature_css {\n" + "\n".join(css_rows) + "\n}\n"
    random_locations += """
  location = /-/quiet-mono/v1/nature/scene.css {
   alias /assets/$nature_css;
   default_type text/css;
   add_header Cache-Control "no-store" always;
   add_header X-Content-Type-Options nosniff always;
   add_header X-Quiet-Mono-Scene $nature_scene always;
   add_header Set-Cookie "__Secure-qm_nature=$nature_scene; Path=/-/quiet-mono/v1/; Max-Age=1800; Secure; HttpOnly; SameSite=Lax";
   add_header Vary "Cookie, Referer" always;
   limit_except GET HEAD { deny all; }
  }
"""
    random_config += (
        "map $http_accept $nature_format { default webp; ~*image/avif avif; }\n"
    )
    for variant in ["desktop", "mobile"]:
        rows = [f" {p['id']}:webp {names[p[variant]]};" for p in photos]
        rows += [f" {p['id']}:avif {names[p[variant + 'Avif']]};" for p in photos]
        random_config += (
            f'map "$nature_scene:$nature_format" $nature_{variant} {{\n'
            + "\n".join(rows)
            + "\n}\n"
        )
        random_locations += f"""
  location = /-/quiet-mono/v1/nature/{variant} {{
   if ($request_method !~ ^(GET|HEAD)$) {{ return 403; }}
   absolute_redirect off;
   return 302 /-/quiet-mono/v1/$nature_{variant};
   add_header Cache-Control "no-store" always;
   add_header X-Content-Type-Options nosniff always;
   add_header Vary "Accept, Cookie, Referer" always;
   add_header Set-Cookie "__Secure-qm_nature=$nature_scene; Path=/-/quiet-mono/v1/; Max-Age=1800; Secure; HttpOnly; SameSite=Lax";
   add_header X-Quiet-Mono-Scene $nature_scene always;
   limit_except GET HEAD {{ deny all; }}
  }}
"""
    return random_config, random_locations


def render(root: Path) -> dict[str, object]:
    """Render the theme ConfigMaps, Deployment, Service and Ingress manifests."""
    binary, names = _collect_assets(root)
    chunks = _shard_binary(binary)
    random_config, random_locations = _nature_config(root, names)
    config = """worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 128; }
http {
 __NATURE_CONFIG__
 include /etc/nginx/mime.types;
 types { image/avif avif; }
 default_type application/octet-stream;
 access_log off;
 server_tokens off;
 sendfile on;
 client_body_temp_path /tmp/client_temp;
 proxy_temp_path /tmp/proxy_temp;
 fastcgi_temp_path /tmp/fastcgi_temp;
 uwsgi_temp_path /tmp/uwsgi_temp;
 scgi_temp_path /tmp/scgi_temp;
 server {
  listen 8080;
  location = /healthz { return 200 "ok\\n"; }
  __NATURE_LOCATIONS__
  location /-/quiet-mono/v1/ {
   alias /assets/;
   add_header Cache-Control "public, max-age=31536000, immutable";
   add_header X-Content-Type-Options nosniff always;
   limit_except GET HEAD { deny all; }
  }
  location / { return 404; }
 }
}
"""
    config = config.replace("__NATURE_CONFIG__", random_config).replace(
        "__NATURE_LOCATIONS__", random_locations
    )
    digest = hashlib.sha256(
        json.dumps({"binary": binary, "config": config}, sort_keys=True).encode()
    ).hexdigest()[:12]
    name = "socrat-authentik-theme"
    config_name = name + "-" + digest
    labels = {"app.kubernetes.io/name": name}
    namespace = "identity"

    def meta(resource: str) -> dict[str, object]:
        """Build the shared object metadata for a rendered resource."""
        return {"name": resource, "namespace": namespace, "labels": labels}

    image = cast(
        "str",
        cast("dict[str, object]", json.loads((root / "static-image.json").read_text()))[
            "image"
        ],
    )
    if "@sha256:" not in image:
        message = "Static image must be pinned by registry digest"
        raise ValueError(message)
    shards: list[dict[str, object]] = []
    shard_names: list[str] = []
    for chunk in chunks:
        shard_name = (
            name
            + "-assets-"
            + hashlib.sha256(json.dumps(chunk, sort_keys=True).encode()).hexdigest()[
                :12
            ]
        )
        shard_names.append(shard_name)
        shards.append(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": meta(shard_name),
                "immutable": True,
                "binaryData": chunk,
            }
        )
    items: list[dict[str, object]] = [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": meta(config_name),
            "immutable": True,
            "data": {"nginx.conf": config},
        },
        *shards,
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": meta(name),
            "spec": {
                "replicas": 3,
                "selector": {"matchLabels": labels},
                "strategy": {
                    "type": "RollingUpdate",
                    "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
                },
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "affinity": {
                            "nodeAffinity": {
                                "preferredDuringSchedulingIgnoredDuringExecution": [
                                    {
                                        "weight": 80,
                                        "preference": {
                                            "matchExpressions": [
                                                {
                                                    "key": "kubernetes.io/hostname",
                                                    "operator": "In",
                                                    "values": [
                                                        "socrat-0",
                                                        "socrat-5",
                                                        "socrat-2",
                                                    ],
                                                }
                                            ]
                                        },
                                    }
                                ]
                            },
                            "podAntiAffinity": {
                                "preferredDuringSchedulingIgnoredDuringExecution": [
                                    {
                                        "weight": 100,
                                        "podAffinityTerm": {
                                            "topologyKey": "kubernetes.io/hostname",
                                            "labelSelector": {"matchLabels": labels},
                                        },
                                    }
                                ]
                            },
                        },
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": 101,
                            "runAsGroup": 101,
                            "fsGroup": 101,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [
                            {
                                "name": "static",
                                "image": image,
                                "imagePullPolicy": "IfNotPresent",
                                "command": ["nginx"],
                                "args": ["-g", "daemon off;"],
                                "ports": [{"name": "http", "containerPort": 8080}],
                                "securityContext": {
                                    "readOnlyRootFilesystem": True,
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                                "resources": {
                                    "requests": {
                                        "cpu": "5m",
                                        "memory": "16Mi",
                                        "ephemeral-storage": "32Mi",
                                    },
                                    "limits": {
                                        "cpu": "100m",
                                        "memory": "64Mi",
                                        "ephemeral-storage": "64Mi",
                                    },
                                },
                                "readinessProbe": {
                                    "httpGet": {"path": "/healthz", "port": "http"},
                                    "periodSeconds": 5,
                                },
                                "livenessProbe": {
                                    "httpGet": {"path": "/healthz", "port": "http"},
                                    "periodSeconds": 15,
                                },
                                "volumeMounts": [
                                    {
                                        "name": "config",
                                        "mountPath": "/etc/nginx/nginx.conf",
                                        "subPath": "nginx.conf",
                                        "readOnly": True,
                                    },
                                    {
                                        "name": "assets",
                                        "mountPath": "/assets",
                                        "readOnly": True,
                                    },
                                    {"name": "tmp", "mountPath": "/tmp"},
                                ],
                            }
                        ],
                        "volumes": [
                            {
                                "name": "config",
                                "configMap": {
                                    "name": config_name,
                                    "items": [
                                        {"key": "nginx.conf", "path": "nginx.conf"}
                                    ],
                                },
                            },
                            {
                                "name": "assets",
                                "projected": {
                                    "sources": [
                                        {
                                            "configMap": {
                                                "name": shard_name,
                                                "items": [
                                                    {"key": key, "path": key}
                                                    for key in sorted(chunk)
                                                ],
                                            }
                                        }
                                        for shard_name, chunk in zip(
                                            shard_names, chunks, strict=True
                                        )
                                    ]
                                },
                            },
                            {"name": "tmp", "emptyDir": {"sizeLimit": "32Mi"}},
                        ],
                    },
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": meta(name),
            "spec": {
                "selector": labels,
                "ports": [{"name": "http", "port": 80, "targetPort": "http"}],
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                **meta(name),
                "annotations": {"traefik.ingress.kubernetes.io/router.priority": "120"},
            },
            "spec": {
                "ingressClassName": "traefik",
                "tls": [
                    {
                        "hosts": ["auth.socrat.alchemmist.xyz"],
                        "secretName": "authentik-tls",
                    }
                ],
                "rules": [
                    {
                        "host": "auth.socrat.alchemmist.xyz",
                        "http": {
                            "paths": [
                                {
                                    "path": "/-/quiet-mono/v1/",
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {
                                            "name": name,
                                            "port": {"number": 80},
                                        }
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        },
    ]
    return {"apiVersion": "v1", "kind": "List", "items": items}


if __name__ == "__main__":
    # JSON documents are valid YAML. Separate resources avoid kubectl's List-kind
    # OpenAPI-v2 fallback; each built-in resource keeps Strict v3 validation.
    for item in cast("list[dict[str, object]]", render(Path(sys.argv[1]))["items"]):
        print("---")
        print(json.dumps(item))
