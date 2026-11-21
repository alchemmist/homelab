"""Set the default chat model and its limits across WebUI users."""

import argparse
import getpass
import json
import subprocess
import sys
import urllib.error
import urllib.request


class ConfigurationError(Exception):
    """Exception raised when the Open WebUI model configuration is invalid."""


def request_json(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    path: str,
    token: str | None = None,
    payload: object | None = None,
) -> object:
    """Request json."""
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url + path, data=data, headers=headers)
    try:
        with opener.open(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        message = f"Open WebUI request failed: HTTP {error.code}"
        raise ConfigurationError(message) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        message = "Open WebUI request failed: connection error"
        raise ConfigurationError(message) from None
    except (ValueError, UnicodeError):
        message = "Open WebUI returned invalid JSON"
        raise ConfigurationError(message) from None


def _service_base_url(namespace: str) -> str | None:
    service = subprocess.run(
        [
            "kubectl",
            "--namespace",
            namespace,
            "get",
            "service",
            "open-webui",
            "--ignore-not-found",
            "--output=json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if service.returncode != 0:
        message = "Unable to inspect Open WebUI service"
        raise ConfigurationError(message)
    if not service.stdout.strip():
        return None
    try:
        spec = json.loads(service.stdout)["spec"]
        address = spec["clusterIP"]
        port = next(port["port"] for port in spec["ports"] if port["name"] == "http")
    except (ValueError, KeyError, TypeError, StopIteration):
        message = "Open WebUI service has an unsupported configuration"
        raise ConfigurationError(message) from None
    if not address or address == "None":
        message = "Open WebUI service has no cluster IP"
        raise ConfigurationError(message)
    if ":" in address:
        address = f"[{address}]"
    return f"http://{address}:{port}"


def _sign_in(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    args: argparse.Namespace,
    *,
    auth_required: bool,
) -> str | None:
    if auth_required:
        if not args.admin_email:
            return None
        credentials = {
            "email": args.admin_email,
            "password": getpass.getpass("Open WebUI password: "),
        }
    else:
        credentials = {"email": "admin@localhost", "password": "admin"}
    session = request_json(
        opener,
        base_url,
        "/api/v1/auths/signin",
        payload=credentials,
    )
    token = session.get("token") if isinstance(session, dict) else None
    if not isinstance(token, str) or not token:
        message = "Open WebUI did not return a session token"
        raise ConfigurationError(message)
    return token


def _share_with_users(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    token: str,
    args: argparse.Namespace,
) -> bool:
    records: object = request_json(opener, base_url, "/api/v1/models/all", token)
    if isinstance(records, list) and any(
        isinstance(model, dict) and model.get("id") == args.model for model in records
    ):
        return False
    request_json(
        opener,
        base_url,
        "/api/v1/models/create",
        token,
        {
            "id": args.model,
            "name": args.display_name or args.model,
            "base_model_id": None,
            "meta": {
                "capabilities": {
                    "code_interpreter": False,
                    "terminal": True,
                    "builtin_tools": True,
                },
                "builtinTools": dict.fromkeys(
                    [
                        "skills",
                        "tasks",
                        "notes",
                        "automations",
                        "calendar",
                        "channels",
                        "notifications",
                        "knowledge",
                        "chats",
                        "memory",
                        "subagents",
                    ],
                    False,
                ),
            },
            "params": {},
            "access_grants": [
                {"principal_type": "user", "principal_id": "*", "permission": "read"}
            ],
        },
    )
    return True


def _apply_model_defaults(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    token: str,
    args: argparse.Namespace,
) -> bool:
    defaults: object = request_json(opener, base_url, "/api/v1/configs/models", token)
    if not isinstance(defaults, dict):
        message = "Open WebUI returned invalid model defaults"
        raise ConfigurationError(message)
    params = defaults.get("DEFAULT_MODEL_PARAMS")
    if params is not None and not isinstance(params, dict):
        message = "Open WebUI returned invalid model parameters"
        raise ConfigurationError(message)
    updated = dict(defaults)
    updated["DEFAULT_MODELS"] = args.model
    updated["DEFAULT_MODEL_PARAMS"] = {**(params or {}), "max_tokens": args.max_output_tokens}
    if updated != defaults:
        request_json(opener, base_url, "/api/v1/configs/models", token, updated)
        changed = True
    else:
        changed = False
    readback: object = request_json(opener, base_url, "/api/v1/configs/models", token)
    if (
        not isinstance(readback, dict)
        or readback.get("DEFAULT_MODELS") != args.model
        or not isinstance(readback.get("DEFAULT_MODEL_PARAMS"), dict)
        or readback["DEFAULT_MODEL_PARAMS"].get("max_tokens") != args.max_output_tokens
    ):
        message = "Open WebUI model defaults failed readback validation"
        raise ConfigurationError(message)
    return changed


def configure(args: argparse.Namespace) -> dict[str, object]:
    """Configure."""
    result: dict[str, object] = {
        "changed": False,
        "skipped": False,
        "model": args.model,
        "max_output": args.max_output_tokens,
    }
    base_url = _service_base_url(args.namespace)
    if base_url is None:
        result["skipped"] = True
        return result
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    config: object = request_json(opener, base_url, "/api/config")
    features = config.get("features") if isinstance(config, dict) else None
    if not isinstance(features, dict):
        message = "Open WebUI returned invalid authentication configuration"
        raise ConfigurationError(message)
    token = _sign_in(opener, base_url, args, auth_required=features.get("auth") is not False)
    if token is None:
        result["skipped"] = True
        return result
    models: object = request_json(opener, base_url, "/api/models?refresh=true", token)
    available = models.get("data") if isinstance(models, dict) else None
    if not isinstance(available, list) or not any(
        isinstance(model, dict) and model.get("id") == args.model for model in available
    ):
        message = "Requested model is absent from the refreshed Open WebUI model list"
        raise ConfigurationError(message)
    if args.share_with_users and _share_with_users(opener, base_url, token, args):
        result["changed"] = True
    if _apply_model_defaults(opener, base_url, token, args):
        result["changed"] = True
    return result


def main() -> int:
    """Main."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-output-tokens", type=int, default=16384)
    parser.add_argument("--namespace", default="llm")
    parser.add_argument("--admin-email")
    parser.add_argument("--display-name")
    parser.add_argument("--share-with-users", action="store_true")
    args = parser.parse_args()
    if args.max_output_tokens <= 0:
        parser.error("--max-output-tokens must be positive")
    try:
        result = configure(args)
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Unable to configure Open WebUI model defaults", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
