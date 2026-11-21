#!/usr/bin/env python3
"""Explicit private prerequisites for the GitOps SWE Mini app; never prints values.
Run only after Argo creates swe-mini. Does not modify existing keys or accounts.
"""

import base64
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

NS = "swe-mini"


def kubectl(*args) -> bytes:
    return subprocess.check_output(["kubectl", *args], stderr=subprocess.DEVNULL)


def secret(namespace, name) -> dict[str, str]:
    secret_data: dict[str, str] = json.loads(
        kubectl("-n", namespace, "get", "secret", name, "-o", "json")
    )["data"]
    return secret_data


def ensure(name, data, kind="Opaque") -> None:
    if (
        subprocess.run(
            ["kubectl", "-n", NS, "get", "secret", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        print(name + ": preserved")
        return
    payload = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": NS},
        "type": kind,
        "data": data,
    }
    subprocess.run(
        ["kubectl", "create", "-f", "-"],
        input=json.dumps(payload).encode(),
        stdout=subprocess.DEVNULL,
        check=True,
    )
    print(name + ": created (values withheld)")


def main() -> None:
    kubectl("get", "namespace", NS)
    signer = secret("pr-agent", "pr-agent")
    ensure("swe-mini-github", {key: signer[key] for key in ("github-app-id", "github-private-key")})
    ensure(
        "swe-mini-harbor-pull",
        secret("monori", "monori-harbor-pull"),
        "kubernetes.io/dockerconfigjson",
    )
    if (
        subprocess.run(
            ["kubectl", "-n", NS, "get", "secret", "swe-mini-model"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        print("swe-mini-model: preserved")
        return
    master = base64.b64decode(secret("llm", "litellm-env")["LITELLM_MASTER_KEY"]).decode().strip()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    forward = subprocess.Popen(
        ["kubectl", "-n", "llm", "port-forward", "svc/litellm", f"{port}:4000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    key = None
    try:
        for _ in range(40):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.25)
        body = json.dumps(
            {
                "key_alias": "swe-mini-monori",
                "models": ["v-deepseek-uc"],
                "max_parallel_requests": 1,
                "metadata": {
                    "purpose": "owner-approved background Monori maintenance; no other models"
                },
            }
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/key/generate",
            data=body,
            headers={"Authorization": "Bearer " + master, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            key = json.load(response)["key"]
        ensure("swe-mini-model", {"api-key": base64.b64encode(key.encode()).decode()})
    except Exception:
        if key:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/key/delete",
                data=json.dumps({"keys": [key]}).encode(),
                headers={"Authorization": "Bearer " + master, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30):
                pass
        raise RuntimeError(
            "Private model provisioning failed; no credential values emitted"
        ) from None
    finally:
        forward.terminate()
        forward.wait(timeout=10)


if __name__ == "__main__":
    main()
