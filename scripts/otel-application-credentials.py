"""Narrow in-cluster client-leaf mirror; never logs Secret values or reads CA keys.

Runs as the dedicated ServiceAccount. Existing target Secrets are patched only
when the three selected leaf/public-CA data fields change. Reload targets remain
empty until the corresponding application SDK rollout is explicitly enabled.
"""

import base64
import hashlib
import json
import os
import socket
import ssl
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import cast

SOURCE_NS = "cattle-monitoring-system"
DESTINATIONS = {
    "harbor": "harbor",
    "litellm": "llm",
    "vllm": "llm",
    "open-webui": "llm",
    "lms": "lms",
    "wishlist": "wishlist",
}
OBSERVED_PHASE = {"stage": "bootstrap", "application": None}


def require(expected: object, message: str) -> None:
    """Enforce an invariant, failing with the given message."""
    if not expected:
        raise ValueError(message)


def validate_destination(entry):
    app = entry["application"]
    if (
        app not in DESTINATIONS
        or entry["namespace"] != DESTINATIONS[app]
        or entry["secret"] != "otel-app-tls-" + app
    ):
        raise ValueError("Unexpected application leaf destination")
    approved = {
        "harbor": {"harbor-core", "harbor-jobservice", "harbor-registry"},
        "litellm": {"litellm"},
        "vllm": {"vllm"},
        "open-webui": {"open-webui"},
        "lms": {"lms"},
        "wishlist": {"wishlist"},
    }
    if not set(entry.get("reloadDeployments", [])) <= approved[app]:
        raise ValueError("Unexpected application reload target")


def run():
    token_root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    token = (token_root / "token").read_text().strip()
    context = ssl.create_default_context(cafile=str(token_root / "ca.crt"))
    endpoint = (
        "https://"
        + os.environ["KUBERNETES_SERVICE_HOST"]
        + ":"
        + os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    )
    entries = json.loads(Path("/etc/otel-applications/destinations.json").read_text())
    require(
        len(entries) == len(DESTINATIONS)
        and {entry["application"] for entry in entries} == set(DESTINATIONS),
        "Exactly the registered dedicated application client leaves required",
    )

    def api(namespace, resource, name, patch=None) -> dict[str, object]:
        path = "/api/v1/namespaces/" if resource == "secrets" else "/apis/apps/v1/namespaces/"
        path += (
            urllib.parse.quote(namespace, safe="")
            + "/"
            + resource
            + "/"
            + urllib.parse.quote(name, safe="")
        )
        request = urllib.request.Request(
            endpoint + path,
            data=json.dumps(patch).encode() if patch is not None else None,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/merge-patch+json",
            },
            method="PATCH" if patch is not None else "GET",
        )
        with urllib.request.urlopen(request, context=context, timeout=15) as response:
            payload: dict[str, object] = json.load(response)
            return payload

    updated = []
    verified = []
    for entry in entries:
        validate_destination(entry)
        app = entry["application"]
        OBSERVED_PHASE.update(stage="read-named-client-leaf", application=app)
        source = api(SOURCE_NS, "secrets", "otel-app-tls-" + app)
        data = {
            key: cast("dict[str, str]", source["data"])[key]
            for key in ["tls.crt", "tls.key", "ca.crt"]
        }
        # Validate pair and actual private native ingress before distribution.
        with tempfile.TemporaryDirectory(dir="/run/otel-check") as temporary:
            root = Path(temporary)
            for key, value in data.items():
                path = root / key
                path.write_bytes(base64.b64decode(value, validate=True))
                path.chmod(0o600)
            native = ssl.create_default_context(cafile=str(root / "ca.crt"))
            native.load_cert_chain(str(root / "tls.crt"), str(root / "tls.key"))
            native.set_alpn_protocols(["h2"])
            OBSERVED_PHASE["stage"] = "native-mtls-http2-handshake"
            with socket.create_connection(("10.250.0.1", 44317), timeout=10) as connection:
                with native.wrap_socket(connection, server_hostname="10.250.0.1") as secure:
                    secure.sendall(
                        b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
                        + b"\x00\x00\x00\x04\x00\x00\x00\x00\x00"
                    )
                    header = b""
                    while len(header) < 9:
                        chunk = secure.recv(9 - len(header))
                        if not chunk:
                            raise ValueError(
                                "Native authenticated HTTP2 handshake did not complete"
                            )
                        header += chunk
                    if header[3] != 4:
                        raise ValueError("Native authenticated HTTP2 SETTINGS were not received")
        verified.append(app)
        certificate_hash = hashlib.sha256(base64.b64decode(data["tls.crt"])).hexdigest()
        OBSERVED_PHASE["stage"] = "mirror-named-client-leaf"
        target = api(entry["namespace"], "secrets", entry["secret"])
        changed = any(
            cast("dict[str, object]", target.get("data", {})).get(key) != value
            for key, value in data.items()
        )
        if changed:
            api(
                entry["namespace"],
                "secrets",
                entry["secret"],
                {
                    "data": data,
                    "metadata": {
                        "annotations": {
                            "homelab.alchemmist.xyz/client-certificate-sha256": certificate_hash
                        }
                    },
                },
            )
            updated.append(app)
        for deployment in entry.get("reloadDeployments", []):
            workload = api(entry["namespace"], "deployments", deployment)
            spec = cast("dict[str, object]", workload["spec"])
            template = cast("dict[str, object]", spec["template"])
            metadata = cast("dict[str, object]", template.get("metadata", {}))
            annotations = cast("dict[str, object]", metadata.get("annotations", {}))
            annotation = annotations.get("homelab.alchemmist.xyz/client-certificate-sha256")
            if annotation != certificate_hash:
                api(
                    entry["namespace"],
                    "deployments",
                    deployment,
                    {
                        "spec": {
                            "template": {
                                "metadata": {
                                    "annotations": {
                                        "homelab.alchemmist.xyz/client-certificate-sha256": certificate_hash
                                    }
                                }
                            }
                        }
                    },
                )
    print(
        json.dumps(
            {
                "nativeClientMtlsVerified": verified,
                "mirroredClientLeavesUpdated": updated,
                "caPrivateKeysRead": False,
                "secretValuesLogged": False,
            }
        )
    )


if __name__ == "__main__":
    os.umask(0o077)
    try:
        run()
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "success": False,
                    "errorType": type(error).__name__,
                    "secretValuesLogged": False,
                    **OBSERVED_PHASE,
                }
            )
        )
        raise SystemExit(1) from error
