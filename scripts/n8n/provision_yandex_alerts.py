#!/usr/bin/env python3
"""Provision narrowly routed Grafana alerts; admin credentials never leave the host."""

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import cast

BASE = Path(__file__).resolve().parents[2]
HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_REDIRECTION = 300
REMOTE = r"""
import sys,json,subprocess,urllib.request,urllib.error,base64
r=json.load(sys.stdin);k=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml','-n','cattle-monitoring-system']
s=json.loads(subprocess.check_output(k+['get','secret','socrat-grafana-admin','-o','json'],stderr=subprocess.DEVNULL))['data']
a=base64.b64decode(s['admin-user']).decode()+':'+base64.b64decode(s['admin-password']).decode()
v=json.loads(subprocess.check_output(k+['get','svc','kube-prometheus-stack-grafana','-o','json'],stderr=subprocess.DEVNULL))['spec']
u='http://'+v['clusterIP']+':'+str(v['ports'][0]['port'])+r['path']
if r['method']in ('POST','PUT') and isinstance(r.get('body'),dict) and r['body'].get('type')=='webhook' and r['body'].get('settings',{}).get('url')=='https://n8n.socrat.alchemmist.xyz/webhook/socrat-alerts':
 ingress=json.loads(subprocess.check_output(k+['get','secret','spi-alert-ingress','-o','json'],stderr=subprocess.DEVNULL))['data']['token']
 r['body']['settings']['authorization_scheme']='Bearer'
 r['body']['settings']['authorization_credentials']=base64.b64decode(ingress).decode()
req=urllib.request.Request(u,data=json.dumps(r['body']).encode()if r.get('body')is not None else None,method=r['method'],headers={'Authorization':'Basic '+base64.b64encode(a.encode()).decode(),'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(req,timeout=25)as response:status=response.status;raw=response.read().decode()
except urllib.error.HTTPError as e:status=e.code;raw=e.read().decode()
try:body=json.loads(raw)
except ValueError:body={}
print(json.dumps({'status':status,'body':body}))
"""


def api(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    """Run one authenticated n8n API call through the private host and return parsed JSON."""
    r = subprocess.run(
        ["ssh", "socrat-0", "python3 -c " + shlex.quote(REMOTE)],
        input=json.dumps({"method": method, "path": path, "body": body}),
        text=True,
        capture_output=True,
        check=True,
    )
    response: dict[str, object] = json.loads(r.stdout)
    return response


def main() -> None:
    """Provision the reviewed Grafana alert definition from a local JSON file."""
    definition = json.loads(
        (
            BASE / (sys.argv[1] if len(sys.argv) > 1 else "docs/n8n/yandex-session-alerts.json")
        ).read_text()
    )
    folder = api("GET", "/api/folders/automation")
    if folder["status"] == HTTP_NOT_FOUND:
        created = cast(
            "int",
            api("POST", "/api/folders", {"uid": "automation", "title": "Automation"})["status"],
        )
        if created >= HTTP_REDIRECTION:
            msg = "Automation folder creation failed with HTTP " + str(created)
            raise RuntimeError(msg)
    elif folder["status"] != HTTP_OK:
        msg = "Grafana folder listing failed with HTTP " + str(folder["status"])
        raise RuntimeError(msg)
    cp = definition["contactPoint"]
    existing = api("GET", "/api/v1/provisioning/contact-points")
    if existing["status"] != HTTP_OK:
        msg = "Contact points listing failed with HTTP " + str(existing["status"])
        raise RuntimeError(msg)
    method = (
        "PUT"
        if any(c.get("uid") == cp["uid"] for c in cast("list[dict[str, object]]", existing["body"]))
        else "POST"
    )
    path = "/api/v1/provisioning/contact-points" + ("/" + cp["uid"] if method == "PUT" else "")
    result = api(method, path, cp)
    if cast("int", result["status"]) >= HTTP_REDIRECTION:
        msg = "Grafana provisioning failed with HTTP " + str(result["status"])
        raise RuntimeError(msg)
    for rule in definition["rules"]:
        current = api("GET", "/api/v1/provisioning/alert-rules/" + rule["uid"])
        if current["status"] not in (HTTP_OK, HTTP_NOT_FOUND):
            msg = "Alert rule lookup returned HTTP " + str(current["status"])
            raise RuntimeError(msg)
        method = "PUT" if current["status"] == HTTP_OK else "POST"
        path = "/api/v1/provisioning/alert-rules" + ("/" + rule["uid"] if method == "PUT" else "")
        result = api(method, path, rule)
        if cast("int", result["status"]) >= HTTP_REDIRECTION:
            msg = "Grafana provisioning failed with HTTP " + str(result["status"])
            raise RuntimeError(msg)
        print("Grafana alert provisioned:", rule["uid"])


if __name__ == "__main__":
    main()
