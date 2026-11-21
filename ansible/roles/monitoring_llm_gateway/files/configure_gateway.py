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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow HTTP redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Block redirects so authorization headers are never forwarded."""
        return None  # Never forward an authorization header to a redirected host.


def _get(runner, kubectl, namespace, kind, name):
    """Run one required kubectl read with no fallback permitted."""
    result = runner(
        kubectl + ["-n", namespace, "get", kind, name, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
        env=dict(os.environ, K3S_CONFIG_FILE="/dev/null"),
    )
    if result.returncode:
        message = "Required cluster read failed; no fallback is permitted"
        raise RuntimeError(message)
    return json.loads(result.stdout)


def _require_argocd_source(app, release, namespace):
    """Require the single Git-owned LiteLLM source and its destination."""
    spec = app["spec"]
    sources = spec.get("sources", [spec.get("source", {})])
    matching = [
        s
        for s in sources
        if s.get("repoURL") == "https://github.com/alchemmist/homelab.git"
        and s.get("path") == "charts/litellm"
    ]
    if (
        len(matching) != 1
        or spec["destination"]["namespace"] != namespace
        or spec["destination"].get("server") != "https://kubernetes.default.svc"
    ):
        message = "Expected Git-owned LiteLLM source/destination missing"
        raise RuntimeError(message)
    if matching[0].get("helm", {}).get("releaseName", release) != release:
        message = "Unexpected Git-owned release name"
        raise RuntimeError(message)


def _master_key_ref(deployment):
    """Return the single explicit deployed PROXY_MASTER_KEY secret reference."""
    refs = [
        e["valueFrom"]["secretKeyRef"]
        for c in deployment["spec"]["template"]["spec"]["containers"]
        for e in c.get("env", [])
        if e.get("name") == "PROXY_MASTER_KEY" and "secretKeyRef" in e.get("valueFrom", {})
    ]
    if len(refs) != 1:
        message = "Expected one explicit deployed master-key reference"
        raise RuntimeError(message)
    return refs[0]


def _require_base_url(service):
    """Validate the Service clusterIP is private and build the base URL."""
    address = ipaddress.ip_address(service["spec"]["clusterIP"])
    if (
        not address.is_private
        or address.is_loopback
        or address.is_unspecified
        or address.is_multicast
    ):
        message = "Expected private cluster Service address"
        raise RuntimeError(message)
    host = "[" + str(address) + "]" if address.version == 6 else str(address)
    return "http://" + host + ":4000"


def _request(opener, base, path, credential=None, read_json=False):
    """Perform one gateway request, returning status and optional JSON body."""
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
                message = "Oversized key metadata"
                raise RuntimeError(message)
            return 200, json.loads(body)
    except urllib.error.HTTPError as error:
        return error.code, None


def _require_key_state(request, token, master):
    """Require the existing key restricted to metrics and still enforced."""
    status, info = request("/key/info?" + urllib.parse.urlencode({"key": token}), master, True)
    if status != 200 or info.get("info", {}).get("allowed_routes") != ["/metrics"]:
        message = "Existing key must be restricted to metrics"
        raise RuntimeError(message)
    if request("/metrics")[0] not in (401, 403):
        message = "Anonymous metrics must remain denied"
        raise RuntimeError(message)
    if request("/metrics", token)[0] != 200:
        message = "Existing metrics key does not work; no repair attempted"
        raise RuntimeError(message)
    if request("/v1/models", token)[0] not in (401, 403):
        message = "Model API must remain denied to metrics key"
        raise RuntimeError(message)


def verify(args, runner=None, opener=None):
    runner = runner or subprocess.run
    opener = opener or urllib.request.build_opener(NoRedirect()).open
    kubectl = ["k3s", "kubectl", "--kubeconfig", args.kubeconfig, "--request-timeout=15s"]

    def get(namespace, kind, name):
        return _get(runner, kubectl, namespace, kind, name)

    app = get("argocd", "application", args.release)
    _require_argocd_source(app, args.release, args.namespace)

    deployment = get(args.namespace, "deployment", args.release)
    if (
        deployment["metadata"]["labels"].get("helm.sh/chart")
        != "litellm-helm-" + args.chart_version
    ):
        message = "Deployed chart label differs; review the maintenance contract"
        raise RuntimeError(message)
    ref = _master_key_ref(deployment)
    service = get(args.namespace, "service", args.release)
    base = _require_base_url(service)

    # Missing key is a prerequisite failure, never authorization to generate one.
    metrics_secret = get(args.namespace, "secret", args.secret)
    token = base64.b64decode(metrics_secret["data"]["api-key"], validate=True).decode()
    master_secret = get(args.namespace, "secret", ref["name"])
    master = base64.b64decode(master_secret["data"][ref["key"]], validate=True).decode()
    if not token or not master:
        message = "Empty existing key; refusing repair"
        raise RuntimeError(message)

    def request(path, credential=None, read_json=False):
        return _request(opener, base, path, credential, read_json)

    _require_key_state(request, token, master)
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
        message = (
            "Read-only gateway verification failed; review Git ownership and existing metrics prerequisites privately. No repair or fallback attempted."
        )
        raise SystemExit(message) from None
    print("changed=false")


if __name__ == "__main__":
    main()
