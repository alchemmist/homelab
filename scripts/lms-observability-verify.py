"""Live browser -> LMS -> mTLS collector -> Tempo -> Grafana/Loki verification.

Explicit --create-canary-session creates a short-lived synthetic teacher profile,
not an impersonation of a real user or an Authentik login. It is deleted in finally.
No session value, Secret, private key or student content is saved or printed.
"""

import argparse
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict, cast

ROOT = Path(__file__).resolve().parents[1]


class _Metadata(TypedDict):
    name: str
    creationTimestamp: NotRequired[str]
    deletionTimestamp: NotRequired[str | None]


class _Status(TypedDict, total=False):
    conditions: list[dict[str, str]]
    phase: str


class _Node(TypedDict):
    metadata: _Metadata
    status: _Status


class _Pod(_Node):
    spec: dict[str, object]


def ready_canary_pod(pods: dict[str, object], nodes: dict[str, object]) -> str:
    ready_nodes = {
        node["metadata"]["name"]
        for node in cast("list[_Node]", nodes["items"])
        if any(
            c["type"] == "Ready" and c["status"] == "True"
            for c in node["status"].get("conditions", [])
        )
    }
    candidates = [
        pod
        for pod in cast("list[_Pod]", pods["items"])
        if not pod["metadata"].get("deletionTimestamp")
        and pod["spec"].get("nodeName") in ready_nodes
        and pod["status"].get("phase") == "Running"
        and any(
            c["type"] == "Ready" and c["status"] == "True"
            for c in pod["status"].get("conditions", [])
        )
    ]
    if not candidates:
        msg = "No active ready LMS pod available for canary"
        raise RuntimeError(msg)
    return max(candidates, key=lambda pod: pod["metadata"].get("creationTimestamp", ""))[
        "metadata"
    ]["name"]


def kubepython(code: str) -> dict[str, object]:
    def inspect(command: str) -> dict[str, object]:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "socrat-0", command],
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode:
            msg = "Canary pod discovery failed; sensitive output suppressed"
            raise RuntimeError(msg)
        payload: dict[str, object] = json.loads(result.stdout)
        return payload

    # exec deploy/lms can select a stale Ready/Terminating pod on a lost node.
    pod = ready_canary_pod(
        inspect("kubectl -n lms get pods -l app.kubernetes.io/name=lms -o json"),
        inspect("kubectl get nodes -o json"),
    )
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "socrat-0",
        "kubectl -n lms exec -i " + pod + " -- python -",
    ]
    result = subprocess.run(command, input=code, text=True, capture_output=True, timeout=60)
    if result.returncode:
        msg = "LMS canary operation failed; sensitive output suppressed"
        raise RuntimeError(msg)
    return cast("dict[str, object]", json.loads(result.stdout))


def get_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return cast("dict[str, object]", json.load(response))


def hex_id(value: str) -> str:
    if len(value) in (16, 32) and all(c in "0123456789abcdef" for c in value):
        return value
    return base64.b64decode(value).hex()


class _Span(TypedDict):
    name: str
    spanId: str
    parentSpanId: NotRequired[str]
    startTimeUnixNano: str | int
    endTimeUnixNano: str | int


class _Scope(TypedDict, total=False):
    spans: list[_Span]


class _Batch(TypedDict, total=False):
    scopeSpans: list[_Scope]
    instrumentationLibrarySpans: list[_Scope]


class _SpanRecord(TypedDict):
    name: str
    id: str
    parent: str | None
    durationMs: float


def summarize_trace(document: dict[str, object]) -> list[_SpanRecord]:
    records: list[_SpanRecord] = []
    batches = document.get("batches", document.get("resourceSpans", []))
    for batch in cast("list[_Batch]", batches):
        for scope in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", [])):
            for span in scope.get("spans", []):
                records.append(
                    {
                        "name": span["name"],
                        "id": hex_id(span["spanId"]),
                        "parent": hex_id(span["parentSpanId"])
                        if span.get("parentSpanId")
                        else None,
                        "durationMs": (
                            int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])
                        )
                        / 1e6,
                    }
                )
    return records


class _BrowserObservation(TypedDict):
    pageTrace: str
    apiContext: str


def _run_browser_canary(args: argparse.Namespace, cookie: str) -> tuple[_BrowserObservation, str]:
    """Drive the browser canary and return its observation and trace id."""
    env = {
        **os.environ,
        "LMS_CHECKOUT": str(args.lms_checkout.resolve()),
        "LMS_CANARY_URL": args.lms_url.rstrip("/"),
        "LMS_CANARY_SESSION": cookie,
    }
    browser = subprocess.run(
        ["node", str(ROOT / "scripts/lms-browser-trace-canary.mjs")],
        env=env,
        text=True,
        capture_output=True,
        timeout=100,
    )
    if browser.returncode:
        raise RuntimeError("Browser canary failed: " + browser.stderr[-2500:])
    observation = cast("_BrowserObservation", json.loads(browser.stdout))
    trace_id = observation["pageTrace"].split("-")[1]
    if observation["apiContext"].split("-")[1] != trace_id:
        msg = "Browser and backend trace IDs differ"
        raise ValueError(msg)
    return observation, trace_id


def _await_trace(grafana_url: object, trace_id: str) -> dict[str, object]:
    """Poll production Tempo until the browser canary trace is visible."""
    trace = None
    # Existing tail sampler waits 30 seconds; backend visibility is eventual.
    for _attempt in range(36):
        try:
            trace = get_json(
                str(grafana_url) + "/api/datasources/proxy/uid/tempo/api/traces/" + trace_id
            )
            if summarize_trace(trace):
                break
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        time.sleep(5)
    if trace is None:
        msg = "Production Tempo did not receive the browser trace"
        raise ValueError(msg)
    return trace


def _verify_waterfall(
    records: list[_SpanRecord], observation: _BrowserObservation
) -> tuple[set[str], list[str]]:
    """Verify the chain of parent spans and name the intermediate proxies."""
    page = next(s for s in records if s["name"] == "browser.page")
    api_id = observation["apiContext"].split("-")[2]
    api = next(s for s in records if s["id"] == api_id)
    # Production Traefik adds GET + ReverseProxy between browser and LMS.
    # Verify the ancestry rather than incorrectly requiring a direct edge.
    by_id = {s["id"]: s for s in records}
    seen = set()
    proxy_names = []
    while api["name"] != "browser.api":
        if api["id"] in seen or api["parent"] not in by_id:
            msg = "Waterfall parent relationships are broken"
            raise ValueError(msg)
        seen.add(api["id"])
        api = by_id[api["parent"]]
        if api["name"] != "browser.api":
            proxy_names.append(api["name"])
    if api["parent"] != page["id"]:
        msg = "Browser API span is not a child of the page"
        raise ValueError(msg)
    names = {s["name"] for s in records}
    if not {"content.read_render", "db.connect", "db.transaction"} <= names:
        msg = "Real backend operation spans missing"
        raise ValueError(msg)
    return names, proxy_names


class _LokiStream(TypedDict):
    values: list[object]


def _verify_loki_correlation(grafana_url: object, trace_id: str) -> int:
    """Require the trace id to appear in correlated real LMS Loki logs."""
    query = '{k8s_namespace_name="lms"} |= "' + trace_id + '"'
    logs = get_json(
        str(grafana_url)
        + "/api/datasources/proxy/uid/loki/loki/api/v1/query_range?"
        + urllib.parse.urlencode({"query": query, "limit": 20, "since": "15m"})
    )
    data = cast("dict[str, object]", logs["data"])
    streams = cast("list[_LokiStream]", data["result"])
    count = sum(len(stream["values"]) for stream in streams)
    if count < 2:
        msg = "Correlated real LMS Loki log lines missing"
        raise ValueError(msg)
    return count


def _verify_dashboard(
    args: argparse.Namespace, trace_id: str, span_count: int
) -> tuple[str, object, bool]:
    """Verify the live dashboard in a browser and the Loki-to-Tempo link."""
    dashboard = get_json(args.grafana_url + "/api/dashboards/uid/lms-performance")
    model = cast("dict[str, object]", dashboard["dashboard"])
    if model["uid"] != "lms-performance":
        msg = "Dashboard not provisioned"
        raise ValueError(msg)
    meta = cast("dict[str, object]", dashboard["meta"])
    grafana_url: str = args.grafana_url
    dashboard_url = grafana_url + cast("str", meta["url"]) + "?var-trace_id=" + trace_id
    ui_env = {
        **os.environ,
        "LMS_CHECKOUT": str(args.lms_checkout.resolve()),
        "LMS_DASHBOARD_URL": dashboard_url,
        "LMS_TRACE_ID": trace_id,
        "LMS_SPAN_COUNT": str(span_count),
    }
    ui = subprocess.run(
        ["node", str(ROOT / "scripts/lms-grafana-canary.mjs")],
        env=ui_env,
        text=True,
        capture_output=True,
        timeout=150,
    )
    if ui.returncode:
        raise RuntimeError("Live Grafana browser verification failed: " + ui.stderr[-2500:])
    ui_proof = json.loads(ui.stdout)
    loki = get_json(args.grafana_url + "/api/datasources/uid/loki")
    # Grafana may omit jsonData for an incompletely provisioned datasource;
    # treat that as no derived fields rather than turning verification into a
    # KeyError unrelated to the trace-link assertion.
    json_data = cast("dict[str, object]", loki.get("jsonData", {}))
    derived = cast("list[dict[str, object]]", json_data.get("derivedFields", []))
    link_verified = any(
        field.get("name") == "TraceID"
        and field.get("datasourceUid") == "tempo"
        and field.get("url") == "${__value.raw}"
        for field in derived
    )
    if not link_verified:
        msg = "Loki-to-Tempo derived link not provisioned"
        raise ValueError(msg)
    return dashboard_url, ui_proof, link_verified


def run(args: argparse.Namespace) -> None:
    if not args.create_canary_session:
        msg = "Explicit --create-canary-session required; temporary privileged test identity will be deleted"
        raise ValueError(msg)
    issuer, subject = "urn:homelab:lms-telemetry-canary", str(uuid.uuid4())
    try:
        result = kubepython(f"""
from app.config import Settings
from app.store import Store, digest
import json, time
store = Store(Settings.from_env().database_url)
cookie = store.create_session({issuer!r}, {subject!r}, 'Telemetry canary', '', role='teacher')
with store.connect() as db:
    db.execute('UPDATE sessions SET expires_at=%s WHERE token_hash=%s', (int(time.time())+900, digest(cookie)))
print(json.dumps(dict(cookie=cookie)))
""")
        cookie = cast("str", result["cookie"])
        observation, trace_id = _run_browser_canary(args, cookie)
        trace = _await_trace(args.grafana_url, trace_id)
        records = summarize_trace(trace)
        names, proxy_names = _verify_waterfall(records, observation)
        count = _verify_loki_correlation(args.grafana_url, trace_id)
        dashboard_url, ui_proof, link_verified = _verify_dashboard(args, trace_id, len(records))
        report = {
            "verifiedAt": datetime.now(UTC).isoformat(),
            "success": True,
            "traceId": trace_id,
            "browser": observation,
            "spanCount": len(records),
            "operationNames": sorted(names),
            "waterfallParentIdsVerified": True,
            "intermediateProxySpans": proxy_names,
            "spanTimingsNonnegative": all(s["durationMs"] >= 0 for s in records),
            "correlatedLokiLines": count,
            "dashboardUrl": dashboard_url,
            "dashboardBrowser": ui_proof,
            "lokiToTempoLinkVerified": link_verified,
            "productionMtlsDeliveryVerified": True,
            "secretsSaved": False,
            "syntheticProfileDeleted": False,
            "authentikLoginTested": False,
        }
    finally:
        cleanup = kubepython(f"""
from app.config import Settings
from app.store import Store
import json
store=Store(Settings.from_env().database_url)
with store.connect() as db:
    db.execute('DELETE FROM users WHERE issuer=%s AND subject=%s', ({issuer!r}, {subject!r}))
    count=db.execute('SELECT count(*) AS n FROM users WHERE issuer=%s AND subject=%s', ({issuer!r}, {subject!r})).fetchone()['n']
print(json.dumps(dict(deleted=count==0)))
""")
        if not cleanup["deleted"]:
            msg = "Canary profile cleanup failed"
            raise RuntimeError(msg)
    report["syntheticProfileDeleted"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-canary-session", action="store_true")
    parser.add_argument("--lms-checkout", type=Path, default=ROOT.parent / "lms")
    parser.add_argument("--lms-url", default="https://lms.alchemmist.xyz")
    parser.add_argument("--grafana-url", default="https://grafana.socrat.alchemmist.xyz")
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
