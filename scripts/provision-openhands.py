#!/usr/bin/env python3
"""Explicit operator bootstrap of OpenHands' native settings; never prints secrets.

Requires kubectl access. Creates a distinct LiteLLM v-deepseek-uc-only virtual
key, NOT a personal Pi key. Uses the already running native settings API; model
credentials and policy are persisted by OpenHands, not a custom runtime service.
"""

import base64
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path


def kube_secret(ns, name):
    raw = subprocess.check_output(
        [
            "kubectl",
            "-n",
            ns,
            "get",
            "secret",
            name,
            "-o",
            "json",
            "--ignore-not-found",
        ],
        stderr=subprocess.DEVNULL,
    )
    return json.loads(raw) if raw.strip() else None


def wait_forward(port) -> None:
    """Block until the local port-forward accepts connections."""
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.25)


def start_forward():
    """Start a port-forward to the litellm service; return (port, forward)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    forward = subprocess.Popen(
        ["kubectl", "-n", "llm", "port-forward", "svc/litellm", f"{port}:4000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_forward(port)
    return port, forward


def stop_forward(forward) -> None:
    """Terminate and reap the local port-forward process."""
    forward.terminate()
    forward.wait(timeout=10)


def monori_secret_current(current) -> bool:
    """Return True if the secret already holds the openhands-monori key alias."""
    return bool(
        current
        and current["metadata"].get("annotations", {}).get("homelab/key-alias")
        == "openhands-monori"
    )


def create_model_secret() -> None:
    """Generate the scoped LiteLLM key and store it in the openhands-model Secret."""
    master = (
        base64.b64decode(kube_secret("llm", "litellm-env")["data"]["LITELLM_MASTER_KEY"])
        .decode()
        .strip()
    )
    port, forward = start_forward()
    headers = {"Authorization": "Bearer " + master, "Content-Type": "application/json"}
    created = None
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/key/generate",
            headers=headers,
            data=json.dumps(
                {
                    "key_alias": "openhands-monori",
                    "models": ["v-deepseek-uc", "qwen3.8-27b"],
                    "max_parallel_requests": 3,
                    "metadata": {"purpose": "owner-approved OpenHands; no paid fallback"},
                }
            ).encode(),
        )
        created = json.load(urllib.request.urlopen(request, timeout=30))["key"]
        payload = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "openhands-model",
                "namespace": "openhands",
                "annotations": {"homelab/key-alias": "openhands-monori"},
            },
            "type": "Opaque",
            "data": {"api-key": base64.b64encode(created.encode()).decode()},
        }
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=json.dumps(payload),
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    except Exception:
        if created:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/key/delete",
                headers=headers,
                data=json.dumps({"keys": [created]}).encode(),
            )
            urllib.request.urlopen(request, timeout=30).close()
        msg = "Scoped model provisioning failed; values withheld"
        raise RuntimeError(msg) from None
    finally:
        stop_forward(forward)


def main() -> None:
    dry = os.environ.get("PROVISION_OPENHANDS_DRY_RUN") == "1"
    current = kube_secret("openhands", "openhands-model")
    if dry and not monori_secret_current(current):
        print("dry-run: would create openhands-monori without o-deepseek, max_parallel_requests 3")
        return
    if not monori_secret_current(current):
        create_model_secret()
    key = base64.b64decode(kube_secret("openhands", "openhands-model")["data"]["api-key"]).decode()
    # o-deepseek rpm is shared. This key must not hold that model. Parallelism
    # stays at least 3 and is never lowered below the live key.
    master = (
        base64.b64decode(kube_secret("llm", "litellm-env")["data"]["LITELLM_MASTER_KEY"])
        .decode()
        .strip()
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    forward = subprocess.Popen(
        ["kubectl", "-n", "llm", "port-forward", "svc/litellm", f"{port}:4000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_forward(port)
    try:
        headers = {
            "Authorization": "Bearer " + master,
            "Content-Type": "application/json",
        }
        info = (
            json.load(
                urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://127.0.0.1:{port}/key/info?key=" + urllib.parse.quote(key),
                        headers=headers,
                        method="GET",
                    ),
                    timeout=30,
                )
            ).get("info")
            or {}
        )
        live_parallel = int(info.get("max_parallel_requests") or 0)
        parallel = max(live_parallel, 3)
        models = ["v-deepseek-uc", "qwen3.8-27b"]
        if dry:
            print(
                "dry-run openhands-monori models",
                models,
                "max_parallel_requests",
                parallel,
                "live",
                live_parallel,
            )
            return
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/key/update",
            headers=headers,
            data=json.dumps(
                {"key": key, "models": models, "max_parallel_requests": parallel}
            ).encode(),
        )
        urllib.request.urlopen(request, timeout=30).close()
    finally:
        stop_forward(forward)
    policy = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("deploy/openhands/integration/READY_TO_REVIEW.md")
        .read_text()
    )
    settings = {
        "agent_settings_diff": {
            "agent_kind": "openhands",
            "llm": {
                "model": "openai/v-deepseek-uc",
                "base_url": "http://litellm.llm.svc.cluster.local:4000/v1",
                "api_key": key,
                "api_mode": "chat",
                "native_tool_calling": True,
                "max_input_tokens": 30000,
                "max_output_tokens": 4096,
                "num_retries": 5,
                "timeout": 900,
                "reasoning_effort": None,
                "enable_encrypted_reasoning": False,
                "caching_prompt": False,
                "prompt_cache_retention": None,
                "input_cost_per_token": 0,
                "output_cost_per_token": 0,
            },
            "agent_context": {"system_message_suffix": policy},
            "condenser": {"max_size": 240, "max_tokens": 24000},
        },
        "conversation_settings_diff": {"max_iterations": 200},
    }
    # Input travels on a private exec stream, not argv, logs, chat or Git.
    code = """import json,sys,pathlib,urllib.request
settings=json.load(sys.stdin)
key=pathlib.Path('/home/openhands/.openhands/agent-canvas/api-key.txt').read_text().strip()
def api(path,body=None,method=None):
 r=urllib.request.Request('http://127.0.0.1:8000'+path,method=method,data=json.dumps(body).encode() if body is not None else None,headers={'X-Session-API-Key':key,'Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=30) as response:return json.load(response)
api('/api/settings',settings,'PATCH')
name='socrat-deepseek'
connections=[c for c in api('/api/llm/provider-connections') if c['display_name']=='Socrat LiteLLM (Venice only)']
if len(connections)>1:raise RuntimeError('Ambiguous provider connections; stop')
connection={'display_name':'Socrat LiteLLM (Venice only)','provider':'custom','api_key':settings['agent_settings_diff']['llm']['api_key'],'base_url':settings['agent_settings_diff']['llm']['base_url']}
if connections: c=api('/api/llm/provider-connections/'+connections[0]['id'],connection,'PATCH')
else:c=api('/api/llm/provider-connections',connection)
llm=dict(settings['agent_settings_diff']['llm']);llm.pop('api_key');llm['provider_connection_id']=c['id']
api('/api/profiles/'+name,{'llm':llm,'include_secrets':False})
api('/api/agent-profiles/'+name,{'agent_kind':'openhands','llm_profile_ref':name,'mcp_server_refs':[],'secret_refs':[],'integration_refs':[],'system_message_suffix':settings['agent_settings_diff']['agent_context']['system_message_suffix'],'condenser':settings['agent_settings_diff']['condenser']})
p=api('/api/agent-profiles/'+name)['profile']
api('/api/agent-profiles/'+p['id']+'/activate',{})
d=api('/api/settings');print('Native agent profile active:',name,'key_set:',d['llm_api_key_is_set'])
"""
    subprocess.run(
        [
            "kubectl",
            "-n",
            "openhands",
            "exec",
            "-i",
            "openhands-0",
            "--",
            "python",
            "-c",
            code,
        ],
        input=json.dumps(settings),
        text=True,
        check=True,
    )
    private = Path.home() / ".config/homelab/openhands"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    if private.is_symlink():
        msg = "Unsafe private state directory"
        raise RuntimeError(msg)
    os.chmod(private, 0o700)
    owner_key = subprocess.check_output(
        [
            "kubectl",
            "-n",
            "openhands",
            "exec",
            "openhands-0",
            "--",
            "cat",
            "/home/openhands/.openhands/agent-canvas/api-key.txt",
        ]
    )
    fd = os.open(
        private / "session-key",
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(owner_key)
    print("Owner login key saved privately: ~/.config/homelab/openhands/session-key")


if __name__ == "__main__":
    main()
