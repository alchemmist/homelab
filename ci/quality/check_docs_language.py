"""Check English documentation and Russian reader-facing wiki prose."""

import codecs
import re
from pathlib import Path

from ci.quality.common import ROOT, Finding, failure, finding, report, tracked

RUSSIAN = re.compile(r"[\u0410-\u044f\u0401\u0451]")
README = re.compile(r"readme(?:[._-].*)?", re.IGNORECASE)


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
MARKUP = re.compile(r"(`+).*?\1|\{\{.*?\}\}|https?://[^\s)]+|<[^>]+>")
MIN_WORDS = 3
LONG_WORD_COUNT = 7
ENGLISH_PROSE = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "is",
    "are",
    "when",
    "if",
    "how",
    "for",
    "from",
    "with",
    "before",
    "after",
    "do",
    "not",
    "and",
    "or",
    "use",
    "check",
    "run",
    "create",
    "enable",
    "disable",
    "see",
    "this",
    "that",
    "it",
    "your",
    "you",
    "should",
    "must",
    "can",
}


def _flag_english(name: str, text: str, number: int, problems: list[Finding]) -> None:
    """Flag paragraphs of English prose, recursing into at most one finding per call."""
    visible = MARKUP.sub(" ", re.sub(r"\]\([^)]*\)", "]", text))
    for sentence in re.split(r"(?<=[.!?])\s+", visible):
        words = re.findall(r"\b[A-Za-z]+\b", sentence.lower())
        if (
            not RUSSIAN.search(sentence)
            and len(words) >= MIN_WORDS
            and (ENGLISH_PROSE.intersection(words) or len(words) >= LONG_WORD_COUNT)
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


def _flush_paragraph(name: str, paragraph: list[str], start: int, problems: list[Finding]) -> None:
    """Inspect one accumulated paragraph, then clear it."""
    _flag_english(name, " ".join(paragraph), start, problems)
    paragraph.clear()


def _front_line(name: str, line: str, number: int, problems: list[Finding], *, front: bool) -> bool:
    """Inspect front-matter metadata lines, ending the matter at its closing marker."""
    if line.startswith(("title:", "description:")):
        _flag_english(name, line.split(":", 1)[1], number, problems)
    return front and not (number > 1 and line == "---")


def wiki_findings(name: str, lines: list[str]) -> list[Finding]:
    """Flag English prose, not product names, fenced examples or link destinations."""
    problems: list[Finding] = []
    fence = ""
    front = bool(lines and lines[0] == "---")
    paragraph: list[str] = []
    start = 1

    for number, line in enumerate(lines, 1):
        if front:
            front = _front_line(name, line, number, problems, front=front)
            continue
        marker = FENCE.match(line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = ""
            continue
        separate = not line.strip() or marker or line.lstrip().startswith(("#", "|", "- ", "* "))
        if separate and paragraph:
            _flush_paragraph(name, paragraph, start, problems)
        if marker:
            fence = marker[1]
        elif separate:
            _flag_english(name, line, number, problems)
        else:
            if not paragraph:
                start = number
            paragraph.append(line.strip())
    if paragraph:
        _flush_paragraph(name, paragraph, start, problems)
    return problems


def _document_encoding(data: bytes) -> str | None:
    """Recognize a text BOM, refusing binary assets; utf-8-sig covers plain README text."""
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if b"\0" in data:
        return None  # Binary assets are not documentation text.
    return "utf-8-sig"


def check(names: list[str]) -> tuple[list[Finding], int]:
    """Check every matching tracked text file, not only changed lines or Markdown."""
    findings = []
    count = 0
    for name in names:
        path = Path(name)
        if path.parts[:2] == ("docs", "plans"):
            continue  # Plans, including nested READMEs, may use any language.
        wiki = path.parts[:2] == ("wiki", "content") and path.suffix.lower() == ".md"
        if not wiki and "docs" not in path.parts[:-1] and not README.fullmatch(path.name):
            continue
        if "docs" in path.parts[:-1] and path.suffix.lower() == ".json":
            continue  # JSON artifacts (n8n workflow exports, fixtures) are not documentation prose.
        data = (ROOT / name).read_bytes()
        encoding = _document_encoding(data)
        if encoding is None:
            continue  # Binary assets are not documentation text.
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
