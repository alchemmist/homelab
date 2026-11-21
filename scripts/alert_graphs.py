#!/usr/bin/env python3
"""Generate Git-owned alert graph dashboards and annotation-only Helm overrides.

Reads rendered owning charts, never live alert data. Conditions/labels/routing are
not changed. Requires Helm and PyYAML, like the repository's chart contract tests.
"""

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
OWNERS = [
    "prometheus",
    "alertmanager",
    "prometheus-operator",
    "node-exporter",
    "kube-state-metrics",
    "monitoring-k3s",
    "thanos",
    "loki",
    "lms",
]


def unparen(expr) -> str:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        depth, quote, escaped, closes = 0, None, False, None
        for i, char in enumerate(expr):
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in ('"', "'", "`"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    closes = i
                    break
        if closes != len(expr) - 1:
            break
        expr = expr[1:-1].strip()
    expression: str = expr
    return expression


def diagnostic(expr) -> tuple[str, float | None, str]:
    """Remove only a root numeric comparison; never rewrite inner PromQL logic."""
    expr = unparen(expr)
    depth, quote, escaped = 0, None, False
    for i, char in enumerate(expr):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'", "`"):
            quote = char
        elif char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        elif depth == 0 and char in "<>!=":
            match = re.fullmatch(
                r"(?:==|!=|>=|<=|>|<)\s*(?:bool\s+)?(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
                expr[i:].strip(),
            )
            if match:
                return (
                    expr[:i].strip(),
                    float(match[1]),
                    "Root threshold removed; the panel shows the measured operand.",
                )
    return (
        expr,
        None,
        "Exact rule expression; gaps mean no matching evaluation or missing telemetry, not proof of health.",
    )


def operands(expr) -> list[tuple[str, float | None, str]]:
    """Expose logical/comparison inputs without mutating the actual alert rule."""
    expr = unparen(expr)
    depth, quote, escaped = 0, None, False
    for i, char in enumerate(expr):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'", "`"):
            quote = char
        elif char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        elif depth == 0:
            match = re.match(r"\s+(?:and|or|unless)\s+", expr[i:])
            if match:
                right = expr[i + match.end() :].strip()
                right = re.sub(r"^(?:on|ignoring)\s*\([^)]*\)\s*", "", right)
                return operands(expr[:i]) + operands(right)
    value, threshold, reason = diagnostic(expr)
    if threshold is not None:
        return [(value, threshold, reason)]
    # For complex vector comparisons keep the exact expression rather than
    # guessing which modifier belongs to which operand.
    return [(value, None, reason)]


def render_owner(owner) -> list[dict[str, object]]:
    app = yaml.safe_load((ROOT / "deploy/argocd/apps" / f"{owner}.yaml").read_text())
    source = app["spec"].get("source")
    if source is None:
        source = next(s for s in app["spec"]["sources"] if s.get("path", "").startswith("charts/"))
    helm = source.get("helm", {})
    chart = ROOT / source["path"]
    args = [
        "helm",
        "template",
        helm.get("releaseName", owner),
        str(chart),
        "--namespace",
        app["spec"]["destination"]["namespace"],
    ]
    for filename in helm.get("valueFiles", []):
        if filename == "alert-graphs.values.yaml":
            continue
        args += ["-f", str(chart / filename)]
    return [
        doc
        for doc in yaml.safe_load_all(subprocess.check_output(args, cwd=ROOT, text=True))
        if isinstance(doc, dict) and doc.get("kind") == "PrometheusRule"
    ]


def inventory() -> list[dict[str, object]]:
    rules = []
    for owner in OWNERS:
        for resource in render_owner(owner):
            for group in cast(
                "list[dict[str, object]]", cast("dict[str, object]", resource["spec"])["groups"]
            ):
                for rule in cast("list[dict[str, object]]", group["rules"]):
                    if "alert" in rule:
                        rules.append(
                            {
                                "owner": owner,
                                "resource": cast("dict[str, object]", resource["metadata"])["name"],
                                "group": group["name"],
                                "rule": rule,
                            }
                        )
    observer = ROOT / "deploy/platform/rancher/public-entry"
    rendered = subprocess.check_output(
        ["helm", "template", "rancher-public-entry", str(observer), "--namespace", "cattle-system"],
        text=True,
    )
    for resource in yaml.safe_load_all(rendered):
        if isinstance(resource, dict) and resource.get("kind") == "PrometheusRule":
            spec = cast("dict[str, object]", resource["spec"])
            for group in cast("list[dict[str, object]]", spec["groups"]):
                for rule in cast("list[dict[str, object]]", group["rules"]):
                    if "alert" in rule:
                        rules.append(
                            {
                                "owner": "rancher",
                                "resource": cast("dict[str, object]", resource["metadata"])["name"],
                                "group": group["name"],
                                "rule": rule,
                            }
                        )
    for path in [ROOT / "docs/n8n/spi/alerts.json", ROOT / "docs/n8n/yandex-session-alerts.json"]:
        for rule in json.loads(path.read_text())["rules"]:
            queries = [q["model"]["expr"] for q in rule["data"] if q.get("model", {}).get("expr")]
            if not queries:
                raise ValueError("Grafana rule missing real metric query: " + rule["uid"])
            rules.append(
                {
                    "owner": "grafana-managed",
                    "resource": str(path.relative_to(ROOT)),
                    "group": rule["ruleGroup"],
                    "uid": rule["uid"],
                    "rule": {"alert": rule["title"], "expr": queries[0], "labels": rule["labels"]},
                }
            )
    return rules


def build(
    rules, panel_ids=None
) -> tuple[dict[str, object], dict[str, dict[str, object]], list[dict[str, object]]]:
    # Append-only IDs preserve historical graph URLs when sorted rule names grow.
    panel_ids = {} if panel_ids is None else panel_ids
    for uid, names in panel_ids.items():
        values = list(names.values())
        if any(type(v) is not int or v < 1 or v % 2 != 1 for v in values) or len(
            set(values)
        ) != len(values):
            raise ValueError("Invalid or duplicate persistent panel IDs: " + uid)
    grouped = defaultdict(list)
    for item in rules:
        grouped[(item["owner"], item["rule"]["alert"])].append(item)
    dashboards: dict[str, object] = {}
    mappings: defaultdict[str, dict[str, object]] = defaultdict(dict)
    rows: list[dict[str, object]] = []
    for (owner, name), variants in sorted(grouped.items()):
        group = cast("str", variants[0]["group"])
        uid = "alerts-" + hashlib.sha256((owner + "/" + group).encode()).hexdigest()[:16]
        dashboard = cast(
            "dict[str, object]",
            dashboards.setdefault(
                uid,
                {
                    "uid": uid,
                    "title": "Alerts / " + owner + " / " + group,
                    "schemaVersion": 39,
                    "version": 1,
                    "editable": False,
                    "timezone": "utc",
                    "tags": ["socrat", "alert-diagnostics"],
                    "refresh": "1m",
                    "time": {"from": "now-1h", "to": "now"},
                    "templating": {"list": []},
                    "panels": [],
                },
            ),
        )
        targets: list[dict[str, object]] = []
        reasons: list[str] = []
        thresholds: list[float] = []
        for index, item in enumerate(variants):
            for expr, threshold, reason in operands(str(item["rule"]["expr"])):
                if expr in ("vector(0)", "vector(1)") and len(variants) > 1:
                    continue
                if expr not in {t["expr"] for t in targets}:
                    targets.append(
                        {
                            "refId": str(len(targets) + 1),
                            "expr": expr,
                            "datasource": {"type": "prometheus", "uid": "prometheus"},
                        }
                    )
                reasons.append(reason)
                if threshold is not None:
                    thresholds.append(threshold)
        known = panel_ids.setdefault(uid, {})
        if name not in known:
            known[name] = max(known.values(), default=-1) + 2
        base = known[name]
        panel = {
            "id": base,
            "type": "timeseries",
            "title": name,
            "description": "Condition inputs for "
            + name
            + ". "
            + " ".join(sorted(set(reasons)))
            + " This rule-scoped panel may show multiple affected series; identify the alert target by its legend labels.",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "targets": targets,
            "gridPos": {"x": 0, "y": (base - 1) * 8, "w": 24, "h": 8},
            "fieldConfig": {
                "defaults": {
                    "custom": {"drawStyle": "line", "showPoints": "never", "spanNulls": False},
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [{"color": "green", "value": None}]
                        + [{"color": "gray", "value": t} for t in sorted(set(thresholds))],
                    },
                },
                "overrides": [],
            },
            "options": {
                "tooltip": {"mode": "multi"},
                "legend": {"displayMode": "table", "placement": "bottom"},
            },
        }
        cast("list[dict[str, object]]", dashboard["panels"]).append(panel)
        state = {
            **panel,
            "id": base + 1,
            "title": name + " / matching rule evaluations",
            "description": "Exact firing-condition query. Empty is not zero: it may mean false condition or missing telemetry.",
            "gridPos": {"x": 0, "y": (base - 1) * 8 + 8, "w": 24, "h": 8},
            "targets": [
                {
                    "refId": str(i + 1),
                    "expr": str(item["rule"]["expr"]),
                    "datasource": {"type": "prometheus", "uid": "prometheus"},
                }
                for i, item in enumerate(variants)
            ],
        }
        if (owner, name) == ("monitoring-k3s", "SocratSoftwareUpdateAvailable"):
            # The alert has a single cluster identity; the diagnostic keeps stable app identities.
            panel["targets"] = [
                {
                    "refId": "1",
                    "datasource": panel["datasource"],
                    "legendFormat": "{{app}}",
                    "expr": 'max by (app) (socrat_software_update_available{job="monitoring-update-watch",latest!=""})',
                }
            ]
            panel["description"] = (
                "One line per application: 0 = up to date, 1 = newer stable release. Failed checks leave gaps."
            )
            panel["fieldConfig"] = {
                "defaults": {
                    "min": 0,
                    "max": 1,
                    "decimals": 0,
                    "custom": {"lineInterpolation": "stepAfter", "spanNulls": False},
                },
                "overrides": [],
            }
        cast("list[dict[str, object]]", dashboard["panels"]).append(state)
        spec = {
            "version": 1,
            "graphs": [
                {
                    "id": "primary",
                    "title": name,
                    "dashboard_uid": uid,
                    "panel_id": base,
                    "variables": {},
                    "before_seconds": 1800,
                    "after_seconds": 300,
                },
                {
                    "id": "condition",
                    "title": name + " / rule evaluations",
                    "dashboard_uid": uid,
                    "panel_id": base + 1,
                    "variables": {},
                    "before_seconds": 7200,
                    "after_seconds": 300,
                },
            ],
        }
        mappings[owner][name] = spec
        for item in variants:
            rows.append(
                {
                    "owner": owner,
                    "resource": item["resource"],
                    "group": item["group"],
                    "alert": name,
                    "expr": str(item["rule"]["expr"]),
                    "uid": item.get("uid"),
                    "graphs": spec,
                }
            )
    return dashboards, dict(mappings), rows


def outputs(rules) -> tuple[dict[Path, str], dict[str, dict[str, object]]]:
    registry_path = ROOT / "deploy/monitoring/alert-graph-panel-ids.json"
    registry = json.loads(registry_path.read_text())
    if registry["schemaVersion"] != 1:
        raise ValueError("Unsupported panel ID registry schema")
    dashboards, mappings, rows = build(rules, registry["dashboards"])
    result = {registry_path: json.dumps(registry, indent=2, sort_keys=True) + "\n"}
    for uid, dashboard in dashboards.items():
        result[ROOT / "charts/monitoring-k3s/alert-dashboards" / f"{uid}.json"] = (
            json.dumps(dashboard, indent=2) + "\n"
        )
    result[ROOT / "docs/monitoring/alert-graphs.inventory.json"] = json.dumps(rows, indent=2) + "\n"
    policy: dict[str, list[str]] = {
        uid + ":" + str(panel["id"]): []
        for uid, dashboard in dashboards.items()
        for panel in cast("list[dict[str, object]]", cast("dict[str, object]", dashboard)["panels"])
    }
    result[ROOT / "charts/grafana/alert-graphs.policy.values.yaml"] = yaml.safe_dump(
        {"alertGraphs": {"panels": policy}}, sort_keys=True, explicit_start=True, explicit_end=True
    )
    for owner, mapping in mappings.items():
        if owner == "grafana-managed":
            continue
        if owner in (
            "prometheus",
            "alertmanager",
            "prometheus-operator",
            "node-exporter",
            "kube-state-metrics",
        ):
            value: dict[str, object] = {
                "kube-prometheus-stack": {
                    "defaultRules": {
                        "additionalRuleAnnotations": {
                            name: {"spi_graphs": json.dumps(spec, separators=(",", ":"))}
                            for name, spec in mapping.items()
                        }
                    }
                }
            }
            defaults = yaml.safe_load((ROOT / "charts" / owner / "values.yaml").read_text())[
                "kube-prometheus-stack"
            ]
            extra = defaults.get("additionalPrometheusRulesMap")
            if extra:
                # Helm replaces lists: retain every original field/group/recording
                # rule, changing annotations only, and verify exact rendered rules.
                for resource in extra.values():
                    for group in resource.get("groups", []):
                        for rule in group.get("rules", []):
                            if rule.get("alert") in mapping:
                                rule.setdefault("annotations", {})["spi_graphs"] = json.dumps(
                                    mapping[rule["alert"]], separators=(",", ":")
                                )
                stack = cast("dict[str, object]", value["kube-prometheus-stack"])
                stack["additionalPrometheusRulesMap"] = extra
        else:
            value = {
                "alertGraphAnnotations": {
                    name: json.dumps(spec, separators=(",", ":")) for name, spec in mapping.items()
                }
            }
        if owner == "lms":
            value = {"lms-database-ha": value}
        directory = ROOT / (
            "deploy/platform/rancher/public-entry" if owner == "rancher" else "charts/" + owner
        )
        result[directory / "alert-graphs.values.yaml"] = (
            "# Generated by scripts/alert_graphs.py; conditions and routing unchanged.\n"
            + yaml.safe_dump(value, sort_keys=True, explicit_start=True, explicit_end=True)
        )
    return result, mappings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rules = inventory()
    generated, mappings = outputs(rules)
    for path, content in generated.items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(
                    "Generated alert graph file differs: " + str(path.relative_to(ROOT))
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if not args.check:
        for relative in ("docs/n8n/spi/alerts.json", "docs/n8n/yandex-session-alerts.json"):
            path = ROOT / relative
            obj = json.loads(path.read_text())
            for rule in obj["rules"]:
                spec = cast("dict[str, object]", mappings["grafana-managed"][rule["title"]])
                rule.setdefault("annotations", {})["spi_graphs"] = json.dumps(
                    spec, separators=(",", ":")
                )
                graphs = cast("list[dict[str, object]]", spec["graphs"])
                rule["annotations"]["__dashboardUid__"] = graphs[0]["dashboard_uid"]
                rule["annotations"]["__panelId__"] = str(graphs[0]["panel_id"])
            path.write_text(json.dumps(obj, indent=2) + "\n")
    print(
        "Rules:",
        len(rules),
        "unique mappings:",
        sum(map(len, mappings.values())),
        "dashboards:",
        sum("alert-dashboards" in str(p) for p in generated),
    )


if __name__ == "__main__":
    main()
