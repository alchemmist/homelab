"""Fail-closed integrity and coverage checks for the quality system itself."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import boundaries
from common import ROOT, frozen_source_files, tracked


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON policy/schema key")
        result[key] = value
    return result


def local_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref":
                require(
                    isinstance(item, str) and item.startswith("#"),
                    "Remote schema reference forbidden",
                )
            else:
                local_refs(item)
    elif isinstance(value, list):
        for item in value:
            local_refs(item)


# Offline modules executed by the seven push gates at main181eca75.
# This is coverage preservation, not acceptance of findings or unscheduled work.
RETAINED_PUSH_TESTS = frozenset(
    [
        "tests/test_alert_graph_panel_ids.py",
        "tests/test_alert_graphs_chart.py",
        "tests/test_argocd_refresh.py",
        "tests/test_deployment_ownership.py",
        "tests/test_gateway_readonly.py",
        "tests/test_infrastructure_contracts.py",
        "tests/test_n8n_failure_alert_policy.py",
        "tests/test_operational_entrypoints.py",
        "tests/test_otel_application_credentials.py",
        "tests/test_otel_application_leaf_rotation.py",
        "tests/test_otel_application_registry.py",
        "tests/test_refactor_acceptance.py",
        "tests/test_socrat5_app_placement.py",
        "tests/test_source_pointers.py",
        "tests/test_spi_execution_links.py",
        "tests/test_target_placement_ownership.py",
        "tests/test_vendor_contracts.py",
        "tests/test_vm105_management.py",
        "tests/test_vm105_renderer_lms_litellm.py",
        "tests/test_wg_peer15_relay.py",
        "tests/test_wishlist_observability.py",
    ]
)


def require_retained_push_tests(scheduled: set[str]) -> None:
    """Reject replacement DAGs that silently drop existing main push regressions."""
    require(
        RETAINED_PUSH_TESTS <= scheduled,
        "Existing main push regression lost from scheduled suites",
    )


def owned_test_files(names: list[str]) -> set[str]:
    """Inventory experimental tests too, without authorizing their execution."""
    return {
        name
        for name in names
        if name.startswith(("tests/", "experiments/"))
        and Path(name).name.startswith("test_")
        and name.endswith(".py")
    }


def check():
    frozen_source_files()
    for policy in (ROOT / "quality").rglob("*.json"):
        require(policy.resolve().is_relative_to(ROOT / "quality"), "Quality policy path escape")
        json.loads(policy.read_text(), object_pairs_hook=unique_json)

    lock = json.loads((ROOT / "quality/schemas.lock.json").read_text())
    require(lock["kubernetesVersion"] == "1.36.0", "Quality integrity contract failed")
    paths = set()
    for item in lock["files"]:
        path = ROOT / "quality/schemas" / item["path"]
        require(
            path.resolve().is_relative_to(ROOT / "quality/schemas"),
            "Quality integrity contract failed",
        )
        require(path.name not in paths, "Quality integrity contract failed")
        paths.add(path.name)
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"],
            "Quality integrity contract failed",
        )
        local_refs(json.loads(path.read_text()))
    require(
        paths == {p.name for p in (ROOT / "quality/schemas").glob("*.json")},
        "Quality integrity contract failed",
    )
    tools = json.loads((ROOT / "quality/tools.lock.json").read_text())
    for records in tools["platforms"].values():
        require(
            len({r["name"] for r in records}) == len(records),
            "Quality integrity contract failed",
        )
        for record in records:
            require(
                re.fullmatch("[a-f0-9]{64}", record["sha256"]),
                "Quality integrity contract failed",
            )
            require(
                re.fullmatch(
                    "https://github.com/[\\w-]+/[\\w-]+/releases/download/v[\\d.]+/[\\w.-]+",
                    record["url"],
                )
                or re.fullmatch(
                    r"https://dl\.k8s\.io/release/v1\.36\.4/bin/(linux/amd64|darwin/arm64)/kubectl",
                    record["url"],
                ),
                "Quality integrity contract failed",
            )
            require(
                record["member"] is None or ".." not in Path(record["member"]).parts,
                "Quality integrity contract failed",
            )
    inventory = json.loads((ROOT / "quality/test-suites.json").read_text())
    actual = owned_test_files(tracked())
    scheduled = [p for paths in inventory["suites"].values() for p in paths]
    require(len(scheduled) == len(set(scheduled)), "Test assigned to multiple suites")
    require_retained_push_tests(set(scheduled))
    deferred = set(inventory["notScheduled"])
    require(not set(scheduled) & deferred, "Quality integrity contract failed")
    require(
        actual == set(scheduled) | deferred,
        "New/stale test classification; do not silently lose tests",
    )
    require(
        all(len(reason) >= 20 for reason in inventory["notScheduled"].values()),
        "Quality integrity contract failed",
    )
    require(all(inventory["suites"].values()), "Empty test suite")
    import yaml

    graph = yaml.safe_load((ROOT / "qg.yaml").read_text())
    for suite in inventory["suites"]:
        node = graph["nodes"]["tests-" + suite]
        isolation = "" if suite == "cluster" else " --isolate-network"
        require(
            node["run"] == f"uv run python scripts/quality/tests.py {suite}{isolation}",
            "Test suite execution contract drift",
        )
        require(
            node["results"] == {"junit": f"reports/tests-{suite}.xml"}, "Test report contract drift"
        )
    for baseline in (ROOT / "quality/debt").glob("*.json"):
        data = json.loads(baseline.read_text())
        require(data["version"] == 1 and len(data["reason"]) >= 20, "Unreviewed quality debt")
        require(data.get("acceptance") is False, "Quality debt must not be accepted")
        ids = [f["id"] for f in data["findings"]]
        require(len(ids) == len(set(ids)), "Duplicate quality debt identities")
        for item in data["findings"]:
            require(re.fullmatch(r"[a-f0-9]{64}\.[1-9][0-9]*", item["id"]), "Invalid debt identity")
            require(
                not Path(item["path"]).is_absolute() and ".." not in Path(item["path"]).parts,
                "Unsafe debt source path",
            )
    exceptions = json.loads((ROOT / "quality/secret-false-positives.json").read_text())
    exception_ids = [item["id"] for item in exceptions["findings"]]
    require(len(exception_ids) == len(set(exception_ids)), "Duplicate secret exception IDs")
    for item in exceptions["findings"]:
        require(
            set(item) == {"id", "path", "rule", "reason"},
            "Raw secret payload must not enter exception policy",
        )
        require(len(item["reason"]) >= 20, "Unreviewed secret false positive")
        require(
            not Path(item["path"]).is_absolute() and ".." not in Path(item["path"]).parts,
            "Unsafe secret exception path",
        )
    boundaries.check(ROOT)
    for name in (
        "check_infrastructure_contracts.py",
        "check_source_pointers.py",
        "check_operational_entrypoints.py",
        "check_vendor_contracts.py",
    ):
        path = ROOT / "scripts" / name
        spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
        require(spec is not None and spec.loader is not None, "Missing architecture checker")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        checker = getattr(module, "check", None)
        require(callable(checker), "Missing architecture checker")
        checker()
    print(
        f"Quality contracts OK: {len(paths)} offline schemas, {len(scheduled)}/{len(actual)} scheduled test modules"
    )


if __name__ == "__main__":
    check()
