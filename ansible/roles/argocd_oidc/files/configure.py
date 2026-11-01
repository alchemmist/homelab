"""Provision the Argo CD OIDC client from Authentik's private runtime and inject its secret.

All OAuth client material remains in the private homelab-authentik cache and the
Kubernetes argocd-secret. It is never written to stdout, Ansible output, or Git.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

ROOT = Path.home() / ".cache/homelab-authentik"
CLIENTS_PATH = ROOT / "oidc-clients.json"
KUBECTL = ["kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml"]
NAMESPACE = "argocd"
SECRET_KEY = "oidc.authentik.clientSecret"
PROVIDER_NAME = "homelab-argocd"
APP_SLUG = "argocd"
APP_URL = "https://argocd.socrat.alchemmist.xyz/"
REDIRECT_URI = "https://argocd.socrat.alchemmist.xyz/auth/callback"

# Runs in the Authentik server pod so the bootstrap token stays inside the pod
# environment and API traffic uses the cluster service, not public DNS/TLS.
PROBE_CODE = r'''import json, os, urllib.parse, urllib.request
base="http://authentik-server.identity.svc/api/v3/"
token=os.environ["AUTHENTIK_BOOTSTRAP_TOKEN"]
def get(path):
    req=urllib.request.Request(base+path,headers={"Authorization":"Bearer "+token})
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
def rows(path):return get(path+"?page_size=100")["results"]
p=[x for x in rows("providers/oauth2/") if x.get("name")=="homelab-argocd"]
a=get("core/applications/?superuser_full_list=true&page_size=100")["results"]
a=[x for x in a if x.get("slug")=="argocd"]
if len(p)>1 or len(a)>1:raise SystemExit(2)
print(json.dumps({"provider_exists":bool(p),"application_exists":bool(a)}))'''

RECONCILE_CODE = r'''import json, os, urllib.parse, urllib.request
base="http://authentik-server.identity.svc/api/v3/"
token=os.environ["AUTHENTIK_BOOTSTRAP_TOKEN"]
client=json.load(__import__("sys").stdin)
def api(method,path,payload=None):
    req=urllib.request.Request(base+path,method=method,
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
        data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req,timeout=60) as r:
        body=r.read();return json.loads(body) if body else None
def rows(path):return api("GET",path+"?page_size=100")["results"]
def unique(path,field,value):
    endpoint=path+"?superuser_full_list=true&page_size=100" if path=="core/applications/" else path+"?page_size=100"
    found=[x for x in api("GET",endpoint)["results"] if x.get(field)==value]
    if len(found)>1:raise RuntimeError("duplicate")
    return found[0] if found else None
flows={x["slug"]:x["pk"] for x in rows("flows/instances/")}
cert=unique("crypto/certificatekeypairs/","name","authentik Self-signed Certificate")
scopes=rows("propertymappings/provider/scope/")
standard={x.get("scope_name"):x["pk"] for x in scopes}
required=["openid","profile","email"]
if not cert or any(x not in standard for x in required):raise RuntimeError("missing defaults")
expression='return {"groups": [group.name for group in request.user.ak_groups.all()]}'
changed=False
groups=unique("propertymappings/provider/scope/","scope_name","groups")
if groups:
    if groups.get("expression")!=expression or groups.get("name")!="homelab Argo CD groups":raise RuntimeError("groups mapping conflict")
else:
    groups=api("POST","propertymappings/provider/scope/",{
        "name":"homelab Argo CD groups","scope_name":"groups","expression":expression})
    changed=True
provider=unique("providers/oauth2/","name","homelab-argocd")
settings={"name":"homelab-argocd","client_type":"confidential",
    "client_id":client["client_id"],"client_secret":client["client_secret"],
    "grant_types":["authorization_code","refresh_token"],
    "authentication_flow":flows["default-authentication-flow"],
    "authorization_flow":flows["default-provider-authorization-explicit-consent"],
    "invalidation_flow":flows["default-provider-invalidation-flow"],
    "property_mappings":[standard[x] for x in required]+[groups["pk"]],
    "signing_key":cert["pk"],
    "redirect_uris":[{"matching_mode":"strict","url":"https://argocd.socrat.alchemmist.xyz/auth/callback"}],
    "include_claims_in_id_token":True,"sub_mode":"hashed_user_id",
    "access_token_validity":"minutes=5","refresh_token_validity":"hours=8"}
if provider:provider=api("PATCH","providers/oauth2/"+str(provider["pk"])+"/",settings)
else:
    provider=api("POST","providers/oauth2/",settings)
    changed=True
app=unique("core/applications/","slug","argocd")
app_settings={"name":"Argo CD","slug":"argocd","provider":provider["pk"],
    "meta_launch_url":"https://argocd.socrat.alchemmist.xyz/",
    "meta_description":"Homelab GitOps control plane",
    "policy_engine_mode":"any","group":"Socrat"}
if app:
    if app.get("provider") not in (None,provider["pk"]):raise RuntimeError("application provider conflict")
    app=api("PATCH","core/applications/"+str(app["pk"])+"/",app_settings)
else:
    app=api("POST","core/applications/",app_settings)
    changed=True
allowed=["homelab-owner","homelab-platform-operator"]
known={x.get("name"):x["pk"] for x in rows("core/groups/")}
if any(x not in known for x in allowed):raise RuntimeError("required Authentik group missing")
bindings=api("GET","policies/bindings/?target="+urllib.parse.quote(str(app["pk"]))+"&page_size=100")["results"]
existing={x.get("group") for x in bindings if x.get("group")}
if existing-set(known[x] for x in allowed):raise RuntimeError("unexpected application group binding")
for order,name in enumerate(allowed):
    if known[name] not in existing:
        api("POST","policies/bindings/",{"target":app["pk"],"group":known[name],
            "order":order,"enabled":True,"failure_result":False})
        changed=True
print(json.dumps({"ok":True,"changed":changed}))'''


def run(args: list[str], *, input_text: str | None = None, check: bool = True) -> str:
    result = subprocess.run(args, input=input_text, text=True, capture_output=True)
    if check and result.returncode:
        # Never include subprocess output: it may contain authentication material.
        raise RuntimeError("secure OIDC reconciliation command failed")
    return result.stdout.strip()


def exec_authentik(code: str, input_text: str | None = None) -> dict:
    args = KUBECTL + ["-n", "identity", "exec"]
    if input_text is not None:
        args.append("-i")
    args += ["deploy/authentik-server", "--", "python", "-c", code]
    raw = run(args, input_text=input_text)
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Authentik returned an unexpected response") from exc


def persist_clients(clients: dict) -> None:
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".oidc-clients-", dir=ROOT)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(clients, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, CLIENTS_PATH)
        CLIENTS_PATH.chmod(0o600)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> None:
    if not (ROOT / "credentials.json").is_file():
        raise RuntimeError("Authentik runtime credential file is missing")
    clients = json.loads(CLIENTS_PATH.read_text()) if CLIENTS_PATH.exists() else {}
    entry = clients.get("argocd")
    state = exec_authentik(PROBE_CODE)
    if entry is None:
        if state["provider_exists"]:
            raise RuntimeError("Existing provider has no local credential journal; refusing rotation")
        entry = {"client_id": "socrat-argocd", "client_secret": secrets.token_urlsafe(48)}
        clients["argocd"] = entry
        persist_clients(clients)
    if not entry.get("client_id") or not entry.get("client_secret"):
        raise RuntimeError("Argo CD OAuth credential journal is incomplete")
    result = exec_authentik(RECONCILE_CODE, json.dumps(entry))
    if result.get("ok") is not True:
        raise RuntimeError("Authentik did not confirm the Argo CD client")

    desired = base64.b64encode(entry["client_secret"].encode()).decode()
    current = json.loads(run(KUBECTL + ["-n", NAMESPACE, "get", "secret",
                                        "argocd-secret", "-o", "json"]))
    if current.get("data", {}).get(SECRET_KEY) != desired:
        patch = {"data": {SECRET_KEY: desired}}
        run(KUBECTL + ["-n", NAMESPACE, "patch", "secret", "argocd-secret",
                       "--type=merge", "--patch-file", "/dev/stdin"],
            input_text=json.dumps(patch))
        run(KUBECTL + ["-n", NAMESPACE, "rollout", "restart",
                       "deployment/argo-cd-argocd-server"])
        run(KUBECTL + ["-n", NAMESPACE, "rollout", "status",
                       "deployment/argo-cd-argocd-server", "--timeout=180s"])
        result["changed"] = True
    print("changed=" + str(bool(result.get("changed"))).lower())


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--check"]:
            if not (ROOT / "credentials.json").is_file():
                raise RuntimeError("Authentik runtime credential file is missing")
            state = exec_authentik(PROBE_CODE)
            print("preflight=ok provider_exists=" + str(state["provider_exists"]).lower() +
                  " application_exists=" + str(state["application_exists"]).lower())
        elif not sys.argv[1:]:
            main()
        else:
            raise RuntimeError("unsupported option")
    except Exception:
        print("Argo CD Authentik OIDC setup failed; sensitive command output was suppressed", file=sys.stderr)
        raise SystemExit(1)
