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
import textwrap
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import override

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


def _quote_scan(expr: str) -> Iterator[tuple[int, str]]:
    """Yield (index, char) pairs, skipping characters inside string literals."""
    quote, escaped = None, False
    for i, char in enumerate(expr):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'", "`"):
            quote = char
        else:
            yield i, char


def _root_close(expr: str) -> int | None:
    """Return the index closing a leading top-level parenthesis, if balanced."""
    depth, close = 0, None
    for i, char in _quote_scan(expr):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close = i
                break
    return close


def unparen(expr: str) -> str:
    """Strip redundant outer parentheses that wrap the whole expression."""
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        if _root_close(expr) != len(expr) - 1:
            break
        expr = expr[1:-1].strip()
    return expr


def _top_level(expr: str) -> Iterator[int]:
    """Yield indices of characters outside brackets and string literals."""
    depth = 0
    for i, char in _quote_scan(expr):
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        elif depth == 0:
            yield i


def diagnostic(expr: str) -> tuple[str, float | None, str]:
    """Remove only a root numeric comparison; never rewrite inner PromQL logic."""
    expr = unparen(expr)
    for i in _top_level(expr):
        if expr[i] in "<>!=":
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


def operands(expr: str) -> list[tuple[str, float | None, str]]:
    """Expose logical/comparison inputs without mutating the actual alert rule."""
    expr = unparen(expr)
    for i in _top_level(expr):
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


def render_owner(owner):
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


def _rule_entries(resource: str, owner: str, resource_name: str) -> list[dict]:
    """Flatten a rendered PrometheusRule into one entry per alert rule."""
    entries = []
    for group in resource["spec"]["groups"]:
        for rule in group["rules"]:
            if "alert" in rule:
                entries.append(
                    {
                        "owner": owner,
                        "resource": resource_name,
                        "group": group["name"],
                        "rule": rule,
                    }
                )
    return entries


def _grafana_entry(path: Path, rule: dict) -> dict:
    """Build an inventory entry for one Grafana-managed alert rule."""
    queries = [q["model"]["expr"] for q in rule["data"] if q.get("model", {}).get("expr")]
    if not queries:
        raise ValueError("Grafana rule missing real metric query: " + rule["uid"])
    return {
        "owner": "grafana-managed",
        "resource": str(path.relative_to(ROOT)),
        "group": rule["ruleGroup"],
        "uid": rule["uid"],
        "rule": {"alert": rule["title"], "expr": queries[0], "labels": rule["labels"]},
    }


def inventory():
    rules = []
    for owner in OWNERS:
        for resource in render_owner(owner):
            rules += _rule_entries(resource, owner, resource["metadata"]["name"])
    observer = ROOT / "deploy/platform/rancher/public-entry"
    rendered = subprocess.check_output(
        [
            "helm",
            "template",
            "rancher-public-entry",
            str(observer),
            "--namespace",
            "cattle-system",
        ],
        text=True,
    )
    for resource in yaml.safe_load_all(rendered):
        if isinstance(resource, dict) and resource.get("kind") == "PrometheusRule":
            rules += _rule_entries(resource, "rancher", resource["metadata"]["name"])
    for path in [
        ROOT / "docs/n8n/spi/alerts.json",
        ROOT / "docs/n8n/yandex-session-alerts.json",
    ]:
        for rule in json.loads(path.read_text())["rules"]:
            rules.append(_grafana_entry(path, rule))
    return rules


def _validate_panel_ids(panel_ids: dict[str, dict[str, int]]) -> None:
    """Fail loudly on invalid or duplicate persistent panel IDs."""
    for uid, names in panel_ids.items():
        values = list(names.values())
        duplicated = len(set(values)) != len(values)
        malformed = any(type(v) is not int or v < 1 or v % 2 != 1 for v in values)
        if duplicated or malformed:
            raise ValueError("Invalid or duplicate persistent panel IDs: " + uid)


def _variant_targets(variants: list[dict]) -> tuple[list[dict], list[str], list[float]]:
    """Collect condition-input targets, reasons, and thresholds for alert variants."""
    targets, reasons, thresholds = [], [], []
    for item in variants:
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
    return targets, reasons, thresholds


def _apply_update_override(panel: dict) -> None:
    """Replace the update-available panel with one line per application identity."""
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


def build(rules, panel_ids=None):
    # Append-only IDs preserve historical graph URLs when sorted rule names grow.
    panel_ids = {} if panel_ids is None else panel_ids
    _validate_panel_ids(panel_ids)
    grouped = defaultdict(list)
    for item in rules:
        grouped[(item["owner"], item["rule"]["alert"])].append(item)
    dashboards, mappings, rows = {}, defaultdict(dict), []
    for (owner, name), variants in sorted(grouped.items()):
        group = variants[0]["group"]
        uid = "alerts-" + hashlib.sha256((owner + "/" + group).encode()).hexdigest()[:16]
        dashboard = dashboards.setdefault(
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
        )
        targets, reasons, thresholds = _variant_targets(variants)
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
                    "custom": {
                        "drawStyle": "line",
                        "showPoints": "never",
                        "spanNulls": False,
                    },
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
        dashboard["panels"].append(panel)
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
            _apply_update_override(panel)
        dashboard["panels"].append(state)
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


KUBE_PROMETHEUS_OWNERS = (
    "prometheus",
    "alertmanager",
    "prometheus-operator",
    "node-exporter",
    "kube-state-metrics",
)


def _kube_prometheus_value(owner: str, mapping: dict) -> dict:
    """Render annotation overrides layered on kube-prometheus-stack defaults."""
    value = {
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
        value["kube-prometheus-stack"]["additionalPrometheusRulesMap"] = extra
    return value


_LONG_SCALAR_LENGTH = 72
_YAML_LINE_WIDTH = 100


class _GraphValuesDumper(yaml.SafeDumper):
    """Emit annotation-only Helm values in the repository's canonical style."""

    @override
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        """Indent sequences under their mapping key, like the owning values files."""
        super().increase_indent(flow, indentless=False)

    @override
    def write_folded(self, text: str) -> None:
        """Keep indivisible compact JSON words alone on otherwise overlong lines."""
        if text.startswith('{"version":'):
            # PyYAML wraps *after* an overlong word. Fold before it instead,
            # but only when YAML's single spaces will reconstruct the exact string.
            lines = textwrap.wrap(
                text,
                width=_YAML_LINE_WIDTH - (self.indent or 0),
                break_on_hyphens=False,
                break_long_words=False,
            )
            if " ".join(lines) == text:
                self.write_indicator(">-", need_whitespace=True)
                for line in lines:
                    self.write_indent()
                    self.write_indicator(line, need_whitespace=False)
                self.write_line_break()
                return
        super().write_folded(text)


def _graph_scalar(dumper: _GraphValuesDumper, value: str) -> yaml.ScalarNode:
    """Keep multiline PromQL literal and long single-line annotations folded."""
    style = None
    if "\n" in value:
        style = "|"
    elif len(value) > _LONG_SCALAR_LENGTH:
        style = ">"
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_GraphValuesDumper.add_representer(str, _graph_scalar)


def _dump_graph_values(value: dict[str, object]) -> str:
    """Serialize generated values deterministically without changing scalar content."""
    return yaml.dump(
        value,
        Dumper=_GraphValuesDumper,
        sort_keys=True,
        explicit_start=True,
        explicit_end=True,
    )


def outputs(rules):
    registry_path = ROOT / "deploy/monitoring/alert-graph-panel-ids.json"
    registry = json.loads(registry_path.read_text())
    if registry["schemaVersion"] != 1:
        msg = "Unsupported panel ID registry schema"
        raise ValueError(msg)
    dashboards, mappings, rows = build(rules, registry["dashboards"])
    result = {registry_path: json.dumps(registry, indent=2, sort_keys=True) + "\n"}
    for uid, dashboard in dashboards.items():
        result[ROOT / "charts/monitoring-k3s/alert-dashboards" / f"{uid}.json"] = (
            json.dumps(dashboard, indent=2) + "\n"
        )
    result[ROOT / "docs/observability/monitoring/alert-graphs.inventory.json"] = (
        json.dumps(rows, indent=2) + "\n"
    )
    policy = {
        uid + ":" + str(panel["id"]): []
        for uid, dashboard in dashboards.items()
        for panel in dashboard["panels"]
    }
    result[ROOT / "charts/grafana/alert-graphs.policy.values.yaml"] = yaml.safe_dump(
        {"alertGraphs": {"panels": policy}},
        sort_keys=True,
        explicit_start=True,
        explicit_end=True,
    )
    for owner, mapping in mappings.items():
        if owner == "grafana-managed":
            continue
        if owner in KUBE_PROMETHEUS_OWNERS:
            value = _kube_prometheus_value(owner, mapping)
        else:
            value = {
                "alertGraphAnnotations": {
                    name: json.dumps(spec, separators=(",", ":")) for name, spec in mapping.items()
                }
            }
        if owner == "lms":
            value = {**value, "lms-database-ha": value}
        directory = ROOT / (
            "deploy/platform/rancher/public-entry" if owner == "rancher" else "charts/" + owner
        )
        result[directory / "alert-graphs.values.yaml"] = (
            "# Generated by scripts/alert_graphs.py; conditions and routing unchanged.\n"
            + _dump_graph_values(value)
        )
    return result, mappings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    rules = inventory()
    generated, mappings = outputs(rules)
    for path, content in generated.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for relative in ("docs/n8n/spi/alerts.json", "docs/n8n/yandex-session-alerts.json"):
        path = ROOT / relative
        obj = json.loads(path.read_text())
        for rule in obj["rules"]:
            spec = mappings["grafana-managed"][rule["title"]]
            rule.setdefault("annotations", {})["spi_graphs"] = json.dumps(
                spec, separators=(",", ":")
            )
            rule["annotations"]["__dashboardUid__"] = spec["graphs"][0]["dashboard_uid"]
            rule["annotations"]["__panelId__"] = str(spec["graphs"][0]["panel_id"])
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
