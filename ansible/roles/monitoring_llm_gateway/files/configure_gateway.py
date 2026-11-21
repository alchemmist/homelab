"""Read-only verification of an EXISTING Git-owned gateway and metrics key.
No Helm fallback, inference, key creation, Secret apply or rollout on any path.
"""

import argparse
import base64
import ipaddress
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import cast


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward an authorization header to a redirected host.


def verify(args, runner=None, opener=None):
    runner = runner or subprocess.run
    opener = opener or urllib.request.build_opener(NoRedirect()).open
    kubectl = ["k3s", "kubectl", "--kubeconfig", args.kubeconfig, "--request-timeout=15s"]

    def get(namespace, kind, name) -> dict[str, object]:
        result = runner(
            kubectl + ["-n", namespace, "get", kind, name, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(os.environ, K3S_CONFIG_FILE="/dev/null"),
        )
        if result.returncode:
            raise RuntimeError("Required cluster read failed; no fallback is permitted")
        document: dict[str, object] = json.loads(result.stdout)
        return document

    app = get("argocd", "application", args.release)
    spec = cast("dict[str, object]", app["spec"])
    sources = cast(
        "list[dict[str, object]]",
        spec.get("sources", [spec.get("source", {})]),
    )
    matching = [
        s
        for s in sources
        if s.get("repoURL") == "https://github.com/alchemmist/homelab.git"
        and s.get("path") == "charts/litellm"
    ]
    dist = cast("dict[str, object]", spec["destination"])
    if (
        len(matching) != 1
        or cast("str", dist["namespace"]) != args.namespace
        or cast("str", dist.get("server")) != "https://kubernetes.default.svc"
    ):
        raise RuntimeError("Expected Git-owned LiteLLM source/destination missing")
    helm = cast("dict[str, object]", matching[0].get("helm", {}))
    if helm.get("releaseName", args.release) != args.release:
        raise RuntimeError("Unexpected Git-owned release name")

    deployment = get(args.namespace, "deployment", args.release)
    deployment_meta = cast("dict[str, object]", deployment["metadata"])
    labels = cast("dict[str, object]", deployment_meta["labels"])
    if labels.get("helm.sh/chart") != "litellm-helm-" + args.chart_version:
        raise RuntimeError("Deployed chart label differs; review the maintenance contract")
    deployment_spec = cast("dict[str, object]", deployment["spec"])
    template = cast("dict[str, object]", deployment_spec["template"])
    pod_spec = cast("dict[str, object]", template["spec"])
    containers = cast("list[dict[str, object]]", pod_spec["containers"])
    refs = [
        cast("dict[str, object]", e["valueFrom"])["secretKeyRef"]
        for c in containers
        for e in cast("list[dict[str, object]]", c.get("env", []))
        if e.get("name") == "PROXY_MASTER_KEY"
        and "secretKeyRef" in cast("dict[str, object]", e.get("valueFrom", {}))
    ]
    if len(refs) != 1:
        raise RuntimeError("Expected one explicit deployed master-key reference")
    service = get(args.namespace, "service", args.release)
    address = ipaddress.ip_address(
        cast("str", cast("dict[str, object]", service["spec"])["clusterIP"])
    )
    if (
        not address.is_private
        or address.is_loopback
        or address.is_unspecified
        or address.is_multicast
    ):
        raise RuntimeError("Expected private cluster Service address")
    host = "[" + str(address) + "]" if address.version == 6 else str(address)
    base = "http://" + host + ":4000"

    # Missing key is a prerequisite failure, never authorization to generate one.
    metrics_secret = get(args.namespace, "secret", args.secret)
    metrics_data = cast("dict[str, object]", metrics_secret["data"])
    api_key_entry = cast("str", metrics_data["api-key"])
    token = base64.b64decode(api_key_entry, validate=True).decode()
    ref = cast("dict[str, object]", refs[0])
    master_secret = get(args.namespace, "secret", ref["name"])
    master_data = cast("dict[str, object]", master_secret["data"])
    master = base64.b64decode(
        cast("str", master_data[cast("str", ref["key"])]),
        validate=True,
    ).decode()
    if not token or not master:
        raise RuntimeError("Empty existing key; refusing repair")

    def request(path, credential=None, read_json=False) -> tuple[int, object | None]:
        headers = {} if credential is None else {"Authorization": "Bearer " + credential}
        req = urllib.request.Request(base + path, headers=headers, method="GET")
        try:
            with opener(req, timeout=30) as response:
                if response.status != 200:
                    return response.status, None
                if not read_json:
                    return 200, None
                body = response.read(65537)
                if len(body) > 65536:
                    raise RuntimeError("Oversized key metadata")
                document: object = json.loads(body)
                return 200, document
        except urllib.error.HTTPError as error:
            return error.code, None

    status, info = request("/key/info?" + urllib.parse.urlencode({"key": token}), master, True)
    key_info = cast("dict[str, object]", info) if isinstance(info, dict) else {}
    routes = cast("dict[str, object]", key_info.get("info", {})).get("allowed_routes")
    if status != 200 or routes != ["/metrics"]:
        raise RuntimeError("Existing key must be restricted to metrics")
    if request("/metrics")[0] not in (401, 403):
        raise RuntimeError("Anonymous metrics must remain denied")
    if request("/metrics", token)[0] != 200:
        raise RuntimeError("Existing metrics key does not work; no repair attempted")
    if request("/v1/models", token)[0] not in (401, 403):
        raise RuntimeError("Model API must remain denied to metrics key")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--chart-version", required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--secret", required=True)
    parser.add_argument(
        "--idle-timeout",
        type=int,
        help="Deprecated compatibility argument; no idle wait or rollout occurs",
    )
    args = parser.parse_args()
    try:
        verify(args)
    except Exception:
        # HTTP/key-info errors may contain a token in their URL. Never echo them.
        raise SystemExit(
            "Read-only gateway verification failed; review Git ownership and existing metrics prerequisites privately. No repair or fallback attempted."
        ) from None
    print("changed=false")


if __name__ == "__main__":
    main()
