"""Scan selected public deployment images without granting registry credentials to PRs."""

import json
import re
import subprocess
from pathlib import Path

import yaml

SOURCES = ("charts/grafana-mcp/values.yaml", "deploy/netbird/values.yaml")


def main() -> int:
    """List HIGH/CRITICAL CVEs and block CRITICAL findings with an available fix."""
    blocked = False
    for source in SOURCES:
        image = yaml.safe_load(Path(source).read_text())["image"]
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image["digest"]):
            raise ValueError(f"Missing immutable image digest in {source}")
        ref = f"{image['repository']}@{image['digest']}"
        print(f"Scanning {source}: {ref}", flush=True)
        output = subprocess.check_output(
            [
                "trivy",
                "image",
                "--image-src",
                "remote",
                "--platform",
                "linux/amd64",
                "--scanners",
                "vuln",
                "--severity",
                "HIGH,CRITICAL",
                "--format",
                "json",
                "--",
                ref,
            ]
        )
        for result in json.loads(output)["Results"]:
            for vuln in result.get("Vulnerabilities", []):
                fix = vuln.get("FixedVersion")
                print(
                    vuln["Severity"],
                    vuln["VulnerabilityID"],
                    vuln["PkgName"],
                    "fix:",
                    fix or "none",
                )
                blocked |= vuln["Severity"] == "CRITICAL" and bool(fix)
    return int(blocked)


if __name__ == "__main__":
    raise SystemExit(main())
