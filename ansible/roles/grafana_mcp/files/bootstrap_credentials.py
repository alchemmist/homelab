"""Bootstrap the Grafana MCP credentials secret in the cluster."""

import base64
import json
import os
import secrets
import subprocess
from typing import cast
import sys
import urllib.error
import urllib.request

NAMESPACE = "cattle-monitoring-system"
SECRET_NAME = "grafana-mcp-credentials"
ACCOUNT_NAME = "socrat-mcp"
KUBECTL = ["k3s", "kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml"]


class BootstrapError(Exception):
    """Exception raised when Grafana credential bootstrap fails."""


def kubectl(arguments: list[str], payload: object | None = None) -> dict[str, object] | None:
    """Document the kubectl operation."""
    result = subprocess.run(
        KUBECTL + arguments,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        env=dict(os.environ, K3S_CONFIG_FILE="/dev/null"),
        timeout=45,
    )
    if result.returncode:
        msg = "Kubernetes operation failed"
        raise BootstrapError(msg)
    return cast("dict[str, object]", json.loads(result.stdout)) if result.stdout.strip() else None


class Grafana:
    """Minimal Grafana HTTP API client."""

    def __init__(self, url: str, username: str, password: str) -> None:
        """Initialize the Grafana client."""

        self.url = url
        encoded = base64.b64encode((username + ":" + password).encode()).decode()
        self.authorization = "Basic " + encoded

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        token: str | None = None,
    ) -> dict[str, object]:
        'Issue a Grafana HTTP request and return the decoded JSON response.'
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
                return cast("dict[str, object]", json.load(response))
        except urllib.error.HTTPError as error:
            raise BootstrapError("Grafana returned HTTP " + str(error.code)) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            msg = "Grafana request failed"
            raise BootstrapError(msg) from None


def decode_secret(secret: object) -> dict[str, str]:
    """Document the decode secret operation."""
    try:
        data = cast("dict[str, object]", secret).get("data", {}) if secret else {}
        return {
            key: base64.b64decode(value, validate=True).decode()
            for key, value in cast("dict[str, str]", data).items()
        }
    except (ValueError, UnicodeError):
        return {}


def bootstrap(grafana, existing_secret, persist, has_admin=True):
    """Document the bootstrap operation."""
    values = decode_secret(existing_secret)
    if not has_admin:
        if not all(
            values.get(key) for key in ("grafana-token", "client-token", "service-account-id")
        ):
            msg = "Admin credentials required to create missing MCP credentials"
            raise BootstrapError(msg)
        grafana.request("GET", "/api/org", token=values["grafana-token"])
        return {"changed": False}
    accounts = grafana.request("GET", "/api/serviceaccounts/search?query=socrat-mcp&perpage=100")
    matches = [
        account
        for account in accounts.get("serviceAccounts", [])
        if account["name"] == ACCOUNT_NAME
    ]
    if len(matches) > 1:
        msg = "Multiple matching Grafana service accounts"
        raise BootstrapError(msg)
    changed = False
    if matches:
        account = matches[0]
        if account.get("isDisabled"):
            msg = "Grafana service account is disabled"
            raise BootstrapError(msg)
        if account.get("role") != "Viewer":
            grafana.request(
                "PATCH", "/api/serviceaccounts/" + str(account["id"]), {"role": "Viewer"}
            )
            changed = True
    else:
        account = grafana.request(
            "POST", "/api/serviceaccounts", {"name": ACCOUNT_NAME, "role": "Viewer"}
        )
        changed = True
    account_id = str(account["id"])
    values = decode_secret(existing_secret)
    if (
        values.get("grafana-token")
        and values.get("client-token")
        and values.get("service-account-id") == account_id
    ):
        try:
            grafana.request("GET", "/api/org", token=values["grafana-token"])
            return {"changed": changed}
        except BootstrapError:
            pass
    return {"changed": _issue_credentials(grafana, account_id, values, persist)}


def _issue_credentials(grafana, account_id, values, persist):
    """Create a fresh Grafana token, persist the Secret, and revoke on failure."""
    token = grafana.request(
        "POST",
        "/api/serviceaccounts/" + account_id + "/tokens",
        {"name": "socrat-mcp-" + secrets.token_hex(8), "secondsToLive": 0},
    )
    try:
        grafana.request("GET", "/api/org", token=token["key"])
        persist(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": SECRET_NAME, "namespace": NAMESPACE},
                "type": "Opaque",
                "stringData": {
                    "grafana-token": token["key"],
                    "client-token": values.get("client-token") or secrets.token_urlsafe(48),
                    "service-account-id": account_id,
                },
            }
        )
    except Exception:
        try:
            grafana.request(
                "DELETE", "/api/serviceaccounts/" + account_id + "/tokens/" + str(token["id"])
            )
        except Exception:
            msg = "Credential persistence failed; newly created token cleanup also failed"
            raise BootstrapError(
                msg
            ) from None
        msg = "Credential persistence failed; newly created token revoked"
        raise BootstrapError(msg) from None
    return True


def main():
    """Document the main operation."""
    try:
        credentials = json.load(sys.stdin)
        service = kubectl(
            ["-n", NAMESPACE, "get", "service", "kube-prometheus-stack-grafana", "-o", "json"]
        )
        spec = cast("dict[str, object]", service["spec"]) if service else {}
        address = cast("str", spec["clusterIP"])
        port = next(
            cast("dict[str, object]", entry)["port"]
            for entry in cast("list[object]", spec["ports"])
            if cast("dict[str, object]", entry).get("name") == "http-web"
        )
        grafana = Grafana(
            "http://" + address + ":" + str(port),
            credentials.get("admin_user", ""),
            credentials.get("admin_password", ""),
        )
        secret = kubectl(
            ["-n", NAMESPACE, "get", "secret", SECRET_NAME, "--ignore-not-found", "-o", "json"]
        )
        result = bootstrap(
            grafana,
            secret,
            lambda body: kubectl(
                ["apply", "--server-side", "--field-manager=socrat-mcp", "-f", "-", "-o", "json"],
                body,
            ),
            has_admin=bool(credentials.get("admin_user") and credentials.get("admin_password")),
        )
        print(json.dumps(result))
    except Exception as error:
        print(
            json.dumps(
                {
                    "error": str(error)
                    if isinstance(error, BootstrapError)
                    else "Credential bootstrap failed"
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
