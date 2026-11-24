"""Check English documentation and Russian reader-facing wiki prose."""

import codecs
import re
from pathlib import Path

from ci.quality.common import ROOT, Finding, failure, finding, report, tracked

RUSSIAN = re.compile(r"[\u0410-\u044f\u0401\u0451]")
README = re.compile(r"readme(?:[._-].*)?", re.IGNORECASE)


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
MARKUP = re.compile(r"(`+).*?\1|\{\{.*?\}\}|https?://[^\s)]+|<[^>]+>")
ENGLISH_PROSE = set(
    "a an the to of in is are when if how for from with before after do not and or use check run create enable disable see this that it your you should must can".split()
)


def wiki_findings(name: str, lines: list[str]) -> list[Finding]:
    """Flag English prose, not product names, fenced examples or link destinations."""
    problems = []
    fence = ""
    front = bool(lines and lines[0] == "---")
    paragraph: list[str] = []
    start = 1

    def inspect(text: str, number: int) -> None:
        visible = MARKUP.sub(" ", re.sub(r"\]\([^)]*\)", "]", text))
        for sentence in re.split(r"(?<=[.!?])\s+", visible):
            words = re.findall(r"\b[A-Za-z]+\b", sentence.lower())
            if (
                not RUSSIAN.search(sentence)
                and len(words) >= 3
                and (ENGLISH_PROSE.intersection(words) or len(words) >= 7)
            ):
                problems.append(
                    finding(
                        "wiki-english-prose",
                        name,
                        number,
                        "Write wiki prose in Russian; keep technical names and code unchanged.",
                        sentence.strip(),
                    )
                )
                break

    for number, line in enumerate(lines, 1):
        if front:
            if number > 1 and line == "---":
                front = False
            elif line.startswith(("title:", "description:")):
                inspect(line.split(":", 1)[1], number)
            continue
        marker = FENCE.match(line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = ""
            continue
        separate = not line.strip() or marker or line.lstrip().startswith(("#", "|", "- ", "* "))
        if separate and paragraph:
            inspect(" ".join(paragraph), start)
            paragraph.clear()
        if marker:
            fence = marker[1]
        elif separate:
            inspect(line, number)
        else:
            if not paragraph:
                start = number
            paragraph.append(line.strip())
    if paragraph:
        inspect(" ".join(paragraph), start)
    return problems


def check(names: list[str]) -> tuple[list[Finding], int]:
    """Check every matching tracked text file, not only changed lines or Markdown."""
    findings = []
    count = 0
    for name in names:
        path = Path(name)
        wiki = path.parts[:2] == ("wiki", "content") and path.suffix.lower() == ".md"
        if not wiki and "docs" not in path.parts[:-1] and not README.fullmatch(path.name):
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
        if wiki:
            findings.extend(wiki_findings(name, lines))
            continue
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
