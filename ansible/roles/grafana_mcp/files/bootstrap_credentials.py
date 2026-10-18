import base64
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request

NAMESPACE = "cattle-monitoring-system"
SECRET_NAME = "grafana-mcp-credentials"
ACCOUNT_NAME = "socrat-mcp"
KUBECTL = ["k3s", "kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml"]


class BootstrapError(Exception):
    pass


def kubectl(arguments, payload=None):
    result = subprocess.run(
        KUBECTL + arguments,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        env=dict(os.environ, K3S_CONFIG_FILE="/dev/null"),
        timeout=45,
    )
    if result.returncode:
        raise BootstrapError("Kubernetes operation failed")
    return json.loads(result.stdout) if result.stdout.strip() else None


class Grafana:
    def __init__(self, url, username, password):
        self.url = url
        encoded = base64.b64encode((username + ":" + password).encode()).decode()
        self.authorization = "Basic " + encoded

    def request(self, method, path, payload=None, token=None):
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Authorization": "Bearer " + token if token else self.authorization,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise BootstrapError("Grafana returned HTTP " + str(error.code)) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise BootstrapError("Grafana request failed") from None


def decode_secret(secret):
    try:
        return {
            key: base64.b64decode(value, validate=True).decode()
            for key, value in (secret or {}).get("data", {}).items()
        }
    except (ValueError, UnicodeError):
        return {}


def bootstrap(grafana, existing_secret, persist, has_admin=True):
    values = decode_secret(existing_secret)
    if not has_admin:
        if not all(values.get(key) for key in ("grafana-token", "client-token", "service-account-id")):
            raise BootstrapError("Admin credentials required to create missing MCP credentials")
        grafana.request("GET", "/api/org", token=values["grafana-token"])
        return {"changed": False}
    accounts = grafana.request("GET", "/api/serviceaccounts/search?query=socrat-mcp&perpage=100")
    matches = [account for account in accounts.get("serviceAccounts", []) if account["name"] == ACCOUNT_NAME]
    if len(matches) > 1:
        raise BootstrapError("Multiple matching Grafana service accounts")
    changed = False
    if matches:
        account = matches[0]
        if account.get("isDisabled"):
            raise BootstrapError("Grafana service account is disabled")
        if account.get("role") != "Viewer":
            grafana.request("PATCH", "/api/serviceaccounts/" + str(account["id"]), {"role": "Viewer"})
            changed = True
    else:
        account = grafana.request("POST", "/api/serviceaccounts", {"name": ACCOUNT_NAME, "role": "Viewer"})
        changed = True
    account_id = str(account["id"])
    values = decode_secret(existing_secret)
    if values.get("grafana-token") and values.get("client-token") and values.get("service-account-id") == account_id:
        try:
            grafana.request("GET", "/api/org", token=values["grafana-token"])
            return {"changed": changed}
        except BootstrapError:
            pass
    token = grafana.request(
        "POST", "/api/serviceaccounts/" + account_id + "/tokens",
        {"name": "socrat-mcp-" + secrets.token_hex(8), "secondsToLive": 0},
    )
    try:
        grafana.request("GET", "/api/org", token=token["key"])
        persist({
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": SECRET_NAME, "namespace": NAMESPACE},
            "type": "Opaque",
            "stringData": {
                "grafana-token": token["key"],
                "client-token": values.get("client-token") or secrets.token_urlsafe(48),
                "service-account-id": account_id,
            },
        })
    except Exception:
        try:
            grafana.request("DELETE", "/api/serviceaccounts/" + account_id + "/tokens/" + str(token["id"]))
        except Exception:
            raise BootstrapError("Credential persistence failed; newly created token cleanup also failed") from None
        raise BootstrapError("Credential persistence failed; newly created token revoked") from None
    return {"changed": True}


def main():
    try:
        credentials = json.load(sys.stdin)
        service = kubectl(["-n", NAMESPACE, "get", "service", "kube-prometheus-stack-grafana", "-o", "json"])
        address = service["spec"]["clusterIP"]
        port = next(port["port"] for port in service["spec"]["ports"] if port.get("name") == "http-web")
        grafana = Grafana("http://" + address + ":" + str(port), credentials.get("admin_user", ""), credentials.get("admin_password", ""))
        secret = kubectl(["-n", NAMESPACE, "get", "secret", SECRET_NAME, "--ignore-not-found", "-o", "json"])
        result = bootstrap(grafana, secret, lambda body: kubectl(["apply", "--server-side", "--field-manager=socrat-mcp", "-f", "-", "-o", "json"], body), has_admin=bool(credentials.get("admin_user") and credentials.get("admin_password")))
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({"error": str(error) if isinstance(error, BootstrapError) else "Credential bootstrap failed"}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
