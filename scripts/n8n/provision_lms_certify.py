#!/usr/bin/env python3
"""Deploy the idle LMS certify worker and active n8n workflow.

The LiteLLM key is the existing LMS migrator key. Queue text is built from the
sibling LMS checkout and applied as a ConfigMap; it is not committed.
"""
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
LMS = Path(os.environ.get("LMS_CONTENT", BASE.parent / "lms" / "content"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync import api, CONFIG


def kubectl(*args, input_text=None):
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "socrat-0", "kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml " + " ".join(args)],
                            input=input_text, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("kubectl failed")
    return result.stdout


def apply(obj):
    kubectl("apply", "-f", "-", input_text=json.dumps(obj))


def queue():
    items = []
    for path in sorted(LMS.rglob("tests.yaml")):
        if path.stat().st_size > 40:
            continue
        statement = path.with_name("statement.md")
        if not statement.exists():
            continue
        text = statement.read_text(encoding="utf-8")
        if len(text) > 12000:
            text = text[:12000]
        items.append({"id": path.parent.name, "statement": text, "tests": []})
    if not items:
        raise RuntimeError("LMS queue is empty")
    return items


def ensure_secret():
    import base64
    key = (Path.home() / ".config/lms-migrator/litellm-key").read_text().strip()
    if not key.startswith("sk-"):
        raise RuntimeError("LMS LiteLLM key missing")
    probe = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "socrat-0",
         "kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n automation get secret lms-certify -o jsonpath={.data.WORKER_TOKEN}"],
        text=True, capture_output=True)
    if probe.returncode == 0 and probe.stdout.strip():
        return base64.b64decode(probe.stdout.strip()).decode()
    token = secrets.token_urlsafe(32)
    apply({"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
           "metadata": {"name": "lms-certify", "namespace": "automation"},
           "stringData": {"WORKER_TOKEN": token, "LITELLM_KEY": key}})
    return token


def main():
    token = ensure_secret()
    code = {"server.py": (BASE / "services/lms-certify/server.py").read_text(),
            "idle_step.py": (BASE.parent / "lms" / "migration" / "idle_step.py").read_text()}
    apply({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "lms-certify-code", "namespace": "automation"}, "data": code})
    apply({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "lms-certify-queue", "namespace": "automation"},
           "data": {"queue.json": json.dumps(queue(), ensure_ascii=False)}})
    kubectl("apply", "-f", "-", input_text=(BASE / "deploy/lms-certify/worker.yaml").read_text())
    kubectl("rollout", "restart", "deployment/lms-certify", "-n", "automation")
    mapping_path = CONFIG / "lms-certify-credentials.json"
    mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    if not mapping.get("httpHeaderAuth", {}).get("id"):
        created = api("POST", "credentials", {"name": "lms-certify worker", "type": "httpHeaderAuth",
                                              "data": {"name": "X-Worker-Token", "value": token}})
        mapping = {"httpHeaderAuth": {"id": created["id"], "name": created["name"]}}
        mapping_path.write_text(json.dumps(mapping))
        os.chmod(mapping_path, 0o600)
    workflow = json.loads((BASE / "docs/n8n/lms-certify/workflow.json").read_text())
    for node in workflow["nodes"]:
        for kind in list(node.get("credentials", {})):
            node["credentials"][kind] = mapping[kind]
    page = api("GET", "workflows?limit=250")
    matches = [item for item in page["data"] if item["name"] == workflow["name"]]
    if len(matches) > 1:
        raise RuntimeError("Ambiguous workflow")
    body = {key: workflow[key] for key in ("name", "nodes", "connections", "settings")}
    if matches and matches[0].get("active"):
        api("POST", "workflows/" + matches[0]["id"] + "/deactivate")
    result = api("PUT" if matches else "POST", "workflows/" + matches[0]["id"] if matches else "workflows", body)
    api("POST", "workflows/" + result["id"] + "/activate")
    print("active", result["id"])


if __name__ == "__main__":
    main()
