import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request


class ConfigurationError(Exception):
    pass


def request_json(opener, base_url, path, token=None, payload=None):
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
        raise ConfigurationError(f"Open WebUI request failed: HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ConfigurationError("Open WebUI request failed: connection error") from None
    except (ValueError, UnicodeError):
        raise ConfigurationError("Open WebUI returned invalid JSON") from None


def configure(args):
    result = {
        "changed": False,
        "skipped": False,
        "model": args.model,
        "max_output": args.max_output_tokens,
    }
    service = subprocess.run(
        [
            "kubectl",
            "--namespace",
            args.namespace,
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
        raise ConfigurationError("Unable to inspect Open WebUI service")
    if not service.stdout.strip():
        result["skipped"] = True
        return result
    try:
        spec = json.loads(service.stdout)["spec"]
        address = spec["clusterIP"]
        port = next(port["port"] for port in spec["ports"] if port["name"] == "http")
    except (ValueError, KeyError, TypeError, StopIteration):
        raise ConfigurationError("Open WebUI service has an unsupported configuration") from None
    if not address or address == "None":
        raise ConfigurationError("Open WebUI service has no cluster IP")
    if ":" in address:
        address = f"[{address}]"
    base_url = f"http://{address}:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    config = request_json(opener, base_url, "/api/config")
    features = config.get("features") if isinstance(config, dict) else None
    if not isinstance(features, dict) or features.get("auth") is not False:
        result["skipped"] = True
        return result
    session = request_json(
        opener,
        base_url,
        "/api/v1/auths/signin",
        payload={"email": "admin@localhost", "password": "admin"},
    )
    token = session.get("token") if isinstance(session, dict) else None
    if not isinstance(token, str) or not token:
        raise ConfigurationError("Open WebUI did not return a session token")
    models = request_json(opener, base_url, "/api/models?refresh=true", token)
    available = models.get("data") if isinstance(models, dict) else None
    if not isinstance(available, list) or not any(
        isinstance(model, dict) and model.get("id") == args.model for model in available
    ):
        raise ConfigurationError("Requested model is absent from the refreshed Open WebUI model list")
    defaults = request_json(opener, base_url, "/api/v1/configs/models", token)
    if not isinstance(defaults, dict):
        raise ConfigurationError("Open WebUI returned invalid model defaults")
    params = defaults.get("DEFAULT_MODEL_PARAMS")
    if params is not None and not isinstance(params, dict):
        raise ConfigurationError("Open WebUI returned invalid model parameters")
    updated = dict(defaults)
    updated["DEFAULT_MODELS"] = args.model
    updated["DEFAULT_MODEL_PARAMS"] = {**(params or {}), "max_tokens": args.max_output_tokens}
    if updated != defaults:
        request_json(opener, base_url, "/api/v1/configs/models", token, updated)
        result["changed"] = True
    readback = request_json(opener, base_url, "/api/v1/configs/models", token)
    if (
        not isinstance(readback, dict)
        or readback.get("DEFAULT_MODELS") != args.model
        or not isinstance(readback.get("DEFAULT_MODEL_PARAMS"), dict)
        or readback["DEFAULT_MODEL_PARAMS"].get("max_tokens") != args.max_output_tokens
    ):
        raise ConfigurationError("Open WebUI model defaults failed readback validation")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-output-tokens", type=int, default=16384)
    parser.add_argument("--namespace", default="llm")
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
