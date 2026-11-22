"""Reject Russian alphabet characters in tracked documentation and README files."""

import codecs
import re
from pathlib import Path

from ci.quality.common import ROOT, Finding, failure, finding, report, tracked

RUSSIAN = re.compile(r"[\u0410-\u044f\u0401\u0451]")
README = re.compile(r"readme(?:[._-].*)?", re.IGNORECASE)


def check(names: list[str]) -> tuple[list[Finding], int]:
    """Check every matching tracked text file, not only changed lines or Markdown."""
    findings = []
    count = 0
    for name in names:
        path = Path(name)
        if "docs" not in path.parts[:-1] and not README.fullmatch(path.name):
            continue
        if "docs" in path.parts[:-1] and path.suffix.lower() == ".json":
            continue  # JSON artifacts (n8n workflow exports, fixtures) are not documentation prose.
        data = (ROOT / name).read_bytes()
        if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            encoding = "utf-32"
        elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        elif b"\0" in data:
            continue  # Binary assets are not documentation text.
        else:
            encoding = "utf-8-sig"
        lines = data.decode(encoding).splitlines()
        count += 1
        for number, line in enumerate(lines, 1):
            if RUSSIAN.search(line):
                findings.append(
                    finding(
                        "docs-russian-letter",
                        name,
                        number,
                        "Use English in documentation and README files.",
                        line.strip(),
                    )
                )
    return findings, count


def main() -> int:
    """Publish a native report for the full tracked tree, including nested READMEs."""
    output = ROOT / "reports/docs-language.json"
    try:
        findings, count = check(tracked())
        return int(report("docs-language", findings, count, output))
    except (OSError, RuntimeError, ValueError) as error:
        failure(output, error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
