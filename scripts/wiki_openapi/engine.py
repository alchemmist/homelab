"""Decide when a bot push should refresh the public wiki page."""

import re
from collections.abc import Iterable, Mapping, Sequence

SPEC = "openapi.yaml"
PAGE = "wiki/content/platform/socrat-bot.md"
MARKER = "<!-- wiki-openapi-refresh -->"
SHA = re.compile(r"[a-f0-9]{40}")


class UnsafeInput(Exception):
    """Exception raised on unsafe wiki OpenAPI input."""


def require_sha(value: object) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise UnsafeInput("Full SHA required")
    return value


def spec_changed(event: object, files: Iterable[object] | None) -> bool:
    """Files is the GitHub compare/commit file list. Push payload is not trusted for this."""
    if not isinstance(event, dict) or event.get("ref") != "refs/heads/main":
        return False
    require_sha(event.get("after", ""))
    before = event.get("before", "")
    if before != "0" * 40:
        require_sha(before)
    return any(isinstance(item, dict) and item.get("filename") == SPEC for item in files or [])


def branch_for(sha: object) -> str:
    return "automation/wiki-openapi-" + require_sha(sha)


def page_ok(markdown: object) -> str:
    if not isinstance(markdown, str) or len(markdown) > 200_000:
        raise UnsafeInput("Rendered page is missing or too large")
    if not markdown.startswith("---\n") or 'title: "Socrat Bot"' not in markdown.split("---", 2)[1]:
        raise UnsafeInput("Rendered page lost its Socrat Bot front matter")
    if "POST /v1/messages" not in markdown:
        raise UnsafeInput("Rendered page has no message API")
    return markdown


def select_closable(
    decision: object,
    candidates: Sequence[Mapping[str, object]],
    keep: object,
) -> list[int]:
    """Model may only name already-filtered automation PRs, never the survivor."""
    if not isinstance(decision, dict) or not isinstance(decision.get("close"), list):
        raise UnsafeInput("Model close list is missing")
    allowed = {item["number"] for item in candidates}
    chosen = []
    for number in decision["close"]:
        if (
            not isinstance(number, int)
            or number == keep
            or number not in allowed
            or number in chosen
        ):
            continue
        chosen.append(number)
    return chosen
