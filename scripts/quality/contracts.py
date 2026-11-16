"""Fail-closed integrity and coverage checks for the quality system itself."""

from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from common import ROOT, tracked
import boundaries


def require(condition, message):
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


def check():
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
    actual = {
        p
        for p in tracked()
        if p.startswith("tests/") and Path(p).name.startswith("test_") and p.endswith(".py")
    }
    scheduled = [p for paths in inventory["suites"].values() for p in paths]
    require(len(scheduled) == len(set(scheduled)), "Test assigned to multiple suites")
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
