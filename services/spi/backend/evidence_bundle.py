"""Bounded, redacted evidence persisted as ordinary issue comments; no Contents grant."""

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast
from urllib.parse import quote, urlencode, urlsplit

from core import ASSIGNMENT, SECRET_KEY, SECRET_VALUE, Failure
from grafana_links import repair_markdown_links

MAX_ARTIFACT = 90000
MAX_BUNDLE = 360000
PART_SIZE = 40000
MIN_KNOWN_SECRET_CHARS = 8
EXCERPT_BUDGET_CHARS = 24000
EXCERPT_CHARS = 4000
INDEX_LINK_LIMIT = 18
MIN_FENCE_LEN = 3
NAME_MAX_CHARS = 100
MARKER_DIGEST_CHARS = 20
DEFAULT_GITHUB_APP_ID = "5569869"
DEFAULT_GITHUB_BOT_USER_ID = "351189559"
EXPLORE_PREFIX = "https://grafana.socrat.alchemmist.xyz/explore?"
DEFAULT_EVIDENCE_ORIGIN = "https://spi-evidence.socrat.alchemmist.xyz"
ALLOWED_EVIDENCE_ORIGINS = (
    "https://rustfs.socrat.alchemmist.xyz",
    DEFAULT_EVIDENCE_ORIGIN,
)
REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"
STORAGE_PREFIX = "spi/v1/"
CODE_WRITE_NEEDS_REVIEW = "WRITE_NEEDS_REVIEW"
CODE_STORAGE_INTEGRITY = "STORAGE_INTEGRITY"
CODE_STORAGE_PUBLIC_ORIGIN = "STORAGE_PUBLIC_ORIGIN"
MIN_EXCERPT_TAIL_CHARS = 4
CODE_GRAPH_REQUIRES_S3 = "GRAPH_REQUIRES_S3"
GRAPH_LINK_BUDGET_CHARS = 12000
NAVIGATION_LINK_LIMIT = 18
NAVIGATION_BUDGET_CHARS = 12000
GRAFANA_ORIGIN = "https://grafana.socrat.alchemmist.xyz"
PANEL_TS_MIN_MS = 0
URL_PRINTABLE_MIN_ORDINAL = 33
GAP_ROW_LIMIT = 24
# Secret-bearing comment the redactor never learns dynamically (header form).
SECRET_FIELD_PATTERN = re.compile(r"(?i)(token|credential|credentials|client_secret|set-cookie)")


def encoded(value: object) -> str:
    """Encode one deterministic, sort-stable ASCII JSON text without backticks."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2).replace("`", "\\u0060")


def _redact_mapping(value: Mapping[object, object], known: Sequence[object]) -> dict[str, object]:
    """Redact one mapping level, keeping topology and non-secret keys visible."""
    redacted: dict[str, object] = {}
    for key, item in value.items():
        name = str(key)
        if SECRET_KEY.search(name) or SECRET_FIELD_PATTERN.fullmatch(name):
            redacted[name] = REDACTED
        else:
            redacted[name] = redact(item, known)
    return redacted


def _redact_string(value: str, known: Sequence[object]) -> str:
    """Apply the fixed redaction ladder to one string."""
    for secret in sorted(
        (x for x in known if isinstance(x, str) and len(x) >= MIN_KNOWN_SECRET_CHARS),
        key=len,
        reverse=True,
    ):
        value = value.replace(secret, REDACTED)
    value = SECRET_VALUE.sub(REDACTED, value)
    value = re.sub(
        r"(?im)\b((?:set-cookie|cookie|authorization)\s*[:=]\s*)[^\r\n]+", r"\1" + REDACTED, value
    )
    value = re.sub(
        r"""(?i)((?:["']?(?:password|passwd|token|secret|api[_-]?key"""
        r"""|access[_-]?token|refresh[_-]?token)["']?)\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*')""",
        r'\1"' + REDACTED + '"',
        value,
    )
    value = re.sub(
        r"(?im)(\b(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)[^\r\n,;&]+",
        r"\1" + REDACTED,
        value,
    )
    value = ASSIGNMENT.sub(r"\1" + REDACTED, value)
    value = re.sub(
        r"(\b[a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@",
        r"\1" + REDACTED + "@",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", REDACTED_EMAIL, value)


def redact(value: object, known: Iterable[object] = ()) -> object:
    """Redact a JSON-shaped value recursively; strings get the pattern ladder."""
    known_list = list(known)
    if isinstance(value, dict):
        return _redact_mapping(value, known_list)
    if isinstance(value, list):
        return [redact(item, known_list) for item in value]
    if isinstance(value, str):
        return _redact_string(value, known_list)
    return value


def prepare_bundle(
    event: object,
    evidence: object,
    artifacts: object = (),
    links: object = (),
    known: object = (),
) -> dict[str, object]:
    """Chunk sanitized artifacts plus their manifest into bounded comment parts."""
    event_map = cast("dict[str, object]", event)
    evidence_map = cast("dict[str, object]", evidence)
    known_list = cast("Iterable[object]", known)
    records: list[dict[str, object]] = []
    parts: list[dict[str, object]] = []
    remaining = MAX_BUNDLE
    skipped: list[dict[str, object]] = []
    event_key = cast("str", event_map["event_key"])
    artifact_items = list(cast("Iterable[object]", artifacts))
    for index, item in enumerate(artifact_items):
        safe = cast("dict[str, object]", redact(item, known_list))
        content = encoded(safe.get("content"))
        original = len(content)
        take = min(MAX_ARTIFACT, remaining // max(1, len(artifact_items) - index))
        if take < MIN_EXCERPT_TAIL_CHARS:
            skipped.append(
                {
                    "source": str(safe.get("name", "artifact"))[:NAME_MAX_CHARS],
                    "reason": "ARTIFACT_BUNDLE_BUDGET",
                }
            )
            continue
        stored = content[:take]
        if len(stored) < original:
            # Never call a chopped JSON string a JSON snapshot. Retain a valid
            # envelope with the original digest/size and an explicitly bounded excerpt.
            base: dict[str, object] = {
                "representation": "bounded_json_excerpt",
                "truncated": True,
                "sanitized_chars": original,
                "sanitized_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "limitation": (
                    "Full sanitized document exceeded the artifact/bundle budget. Excerpt"
                    " is text, not a complete upstream response."
                ),
            }
            low, high = 0, len(stored)
            while low < high:
                mid = (low + high + 1) // 2
                if len(encoded({**base, "excerpt": content[:mid]})) <= take:
                    low = mid
                else:
                    high = mid - 1
            stored = encoded({**base, "excerpt": content[:low]})
            if len(stored) > take:
                stored = "null" if take >= MIN_EXCERPT_TAIL_CHARS else ""
        remaining -= len(stored)
        artifact_id = "E" + str(index + 1).zfill(3)
        sha = hashlib.sha256(stored.encode()).hexdigest()
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(safe.get("name", "evidence.json")))[
            :NAME_MAX_CHARS
        ]
        row: dict[str, object] = {
            "id": artifact_id,
            "name": name,
            "sha256": sha,
            "source": safe.get("source", {}),
            "stored_chars": len(stored),
            "sanitized_chars": original,
            "truncated": len(stored) < original,
            "redaction_applied": encoded(item) != encoded(safe),
        }
        records.append(row)
        total_parts = (len(stored) + PART_SIZE - 1) // PART_SIZE
        for offset in range(0, len(stored), PART_SIZE):
            part_no = offset // PART_SIZE + 1
            part_text = stored[offset : offset + PART_SIZE]
            parts.append(
                {
                    "id": artifact_id,
                    "name": name,
                    "part": part_no,
                    "total": total_parts,
                    "sha256": sha,
                    "text": part_text,
                }
            )
    manifest: dict[str, object] = {
        "format": "socrat-evidence-v2",
        "event_key": event_key,
        "status": event_map["status"],
        "incident_start": event_map["startsAt"],
        "incident_end": event_map.get("endsAt"),
        "window": evidence_map.get("window"),
        "artifacts": records,
        "missing": redact(
            list(cast("Iterable[object]", evidence_map.get("missing", []))) + skipped, known_list
        ),
        "links": redact(list(cast("Iterable[object]", links)), known_list),
        "limits": {
            "artifact_chars": MAX_ARTIFACT,
            "bundle_chars": MAX_BUNDLE,
            "comment_payload_chars": PART_SIZE,
        },
        "redaction_policy": (
            "Known credentials, credential fields/patterns, cookies, PEM private keys,"
            " URL passwords and emails removed. Internal topology retained."
            " Original data is bounded, not an exhaustive dump."
        ),
    }
    manifest_text = encoded(manifest)
    # Manifest itself is a first-class, partitioned artifact, never silently clipped.
    manifest_digest = hashlib.sha256(manifest_text.encode()).hexdigest()
    manifest_parts: list[dict[str, object]] = [
        {
            "id": "MANIFEST",
            "name": "manifest.json",
            "part": pos // PART_SIZE + 1,
            "total": (len(manifest_text) + PART_SIZE - 1) // PART_SIZE,
            "sha256": manifest_digest,
            "text": manifest_text[pos : pos + PART_SIZE],
        }
        for pos in range(0, len(manifest_text), PART_SIZE)
    ]
    allparts = manifest_parts + parts
    for part in allparts:
        identity = hashlib.sha256(encoded(part).encode()).hexdigest()[:MARKER_DIGEST_CHARS]
        part["marker"] = "<!-- socrat-spi-artifact:" + event_key + ":" + identity + " -->"
    excerpts: list[dict[str, object]] = []
    budget = EXCERPT_BUDGET_CHARS
    seen_ids: set[object] = set()
    base_names = {
        "alert-event.json",
        "rule-definitions.json",
        "metric-samples.json",
        "collection-context.json",
    }
    for part in parts:
        if budget <= 0:
            break
        if part["id"] in seen_ids or part["name"] in base_names:
            continue
        seen_ids.add(part["id"])
        part_text = cast("str", part["text"])
        text = part_text[: min(EXCERPT_CHARS, budget)]
        budget -= len(text)
        excerpts.append(
            {
                "id": part["id"],
                "part": part["part"],
                "excerpt": text,
                "excerpt_truncated": len(text) < len(part_text),
            }
        )
    return {
        "manifest": manifest,
        "parts": allparts,
        "model_context": {
            "index": records,
            "excerpts": excerpts,
            "limitation": (
                "Excerpts are bounded. Use evidence IDs in facts. Not every stored"
                " byte was reviewed by the model."
            ),
        },
    }


def index_markdown(bundle: object) -> str:
    """Render the deterministic evidence index comment body."""
    if not bundle:
        return ""
    manifest = cast("dict[str, object]", cast("dict[str, object]", bundle)["manifest"])
    lines: list[str] = [
        "",
        "## Reproducible evidence",
        "Incident: "
        + cast("str", manifest["incident_start"])
        + " to "
        + (cast("str", manifest["incident_end"] or "collection time"))
        + ".",
        (
            "Text artifacts and checksums follow in linked comments. Parts concatenate in"
            " order; SHA-256 covers the stored ASCII JSON text, without code fences."
            " Truncation/redaction and failed reads are recorded in MANIFEST."
        ),
        (
            "Grafana Explore links request sign-in and require Explore permission"
            " (Editor/Admin here); anonymous dashboard access is not sufficient."
        ),
    ]
    link_budget = EXCERPT_BUDGET_CHARS
    for link in cast("list[dict[str, object]]", manifest.get("links", []))[:INDEX_LINK_LIMIT]:
        url = str(link.get("url", ""))
        # Only generated Grafana origin links, never alert-supplied arbitrary URLs.
        if url.startswith(EXPLORE_PREFIX):
            if len(url) > link_budget:
                continue
            link_budget -= len(url)
            lines.append(
                "- ["
                + cast("str", link["title"]).replace("[", "").replace("]", "")
                + "]("
                + url
                + ")"
            )
    lines.extend(
        "- "
        + cast("str", artifact["id"])
        + ": `"
        + cast("str", artifact["name"])
        + "`"
        + (" (TRUNCATED)" if artifact["truncated"] else "")
        for artifact in cast("list[dict[str, object]]", manifest["artifacts"])
    )
    # Also fix bundles collected/saved before the generator login correction.
    return repair_markdown_links("\n".join(lines))


def index_marker(bundle: object) -> str:
    """Return the deterministic index comment marker for one bundle."""
    bundle_map = cast("dict[str, object]", bundle)
    manifest = cast("dict[str, object]", bundle_map["manifest"])
    identity = hashlib.sha256(encoded(manifest).encode()).hexdigest()[:MARKER_DIGEST_CHARS]
    return (
        "<!-- socrat-spi-evidence-index:"
        + cast("str", manifest["event_key"])
        + ":"
        + identity
        + " -->"
    )


def trusted_comment(comment: Mapping[str, object]) -> bool:
    """Accept only comments authored by this app or its immutable bot user."""
    user = cast("dict[str, object]", comment.get("user", {}))
    app = cast("dict[str, object]", comment.get("performed_via_github_app") or {})
    if user.get("type") != "Bot":
        return False
    if app.get("id") is not None:
        return cast("int", app["id"]) == int(os.environ.get("GITHUB_APP_ID", DEFAULT_GITHUB_APP_ID))
    # Issue responses may omit performed_via_github_app; bot user IDs are immutable too.
    return cast("int", user.get("id")) == int(
        os.environ.get("GITHUB_BOT_USER_ID", DEFAULT_GITHUB_BOT_USER_ID)
    )


class _PublishContext:
    """Host, issue and reconciliation state shared by the publish helpers."""

    def __init__(
        self,
        github: "_CommentHost",
        number: int,
        comments: Sequence[Mapping[str, object]],
        progress: dict[str, object],
        save: Callable[[], None],
    ) -> None:
        """Capture the per-run publish context."""
        self.github = github
        self.number = number
        self.comments = comments
        self.progress = progress
        self.save = save


class _CommentHost(Protocol):
    """Minimal GitHub comment host used by the publisher."""

    def comments(self, number: int) -> list[dict[str, object]]:
        """List the comments of one issue."""
        ...

    def request(self, method: str, path: str, payload: Mapping[str, object]) -> dict[str, object]:
        """Perform one REST call and return the decoded response."""
        ...


def _post_comment(host: _CommentHost, number: int, body: str) -> dict[str, object]:
    """POST one issue comment through the host and return the response."""
    return host.request("POST", "/issues/" + str(number) + "/comments", {"body": body})


def _clear_ambiguous(progress: dict[str, object], key: str, save: Callable[[], None]) -> None:
    """Drop an ambiguous-intent marker when the failure is retryable."""
    progress.pop(key, None)
    save()


def _part_body(part: Mapping[str, object]) -> str:
    """Render one part comment: heading, checksum, fenced inert text, marker."""
    # Four backticks cannot be closed by ordinary triple-backtick stack/log text.
    part_text = cast("str", part["text"])
    fence = "`" * (max([len(x) for x in re.findall(r"`+", part_text)] + [MIN_FENCE_LEN]) + 1)
    return (
        "## Evidence "
        + cast("str", part["id"])
        + " — "
        + cast("str", part["name"])
        + " (part "
        + str(part["part"])
        + "/"
        + str(part["total"])
        + ")\n\nSHA-256: `"
        + cast("str", part["sha256"])
        + "`\n\n"
        + fence
        + "text\n"
        + part_text
        + "\n"
        + fence
        + "\n\n"
        + cast("str", part["marker"])
    )


def _publish_part(ctx: "_PublishContext", part: Mapping[str, object]) -> None:
    """Publish one artifact part with persist-before-POST ordering."""
    progress = ctx.progress
    comments = ctx.comments
    marker = cast("str", part["marker"])
    if marker in cast("dict[str, object]", progress.get("done", {})):
        return
    found = next(
        (
            c
            for c in comments
            if marker in cast("str", cast("dict[str, object]", c).get("body") or "")
        ),
        None,
    )
    if found is not None:
        cast("dict[str, object]", progress.setdefault("done", {}))[marker] = cast(
            "dict[str, object]", found
        ).get("html_url", "")
        _clear_ambiguous(progress, "pending", ctx.save)
        return
    if progress.get("pending") == marker:
        raise Failure(CODE_WRITE_NEEDS_REVIEW)
    progress["pending"] = marker
    ctx.save()
    try:
        response = _post_comment(ctx.github, ctx.number, _part_body(part))
    except Failure as exc:
        if str(exc.code).startswith("HTTP_4") and str(exc.code) != "HTTP_408":
            _clear_ambiguous(ctx.progress, "pending", ctx.save)
        raise
    cast("dict[str, object]", progress.setdefault("done", {}))[marker] = response.get(
        "html_url", ""
    )
    _clear_ambiguous(ctx.progress, "pending", ctx.save)


def _publish_index(ctx: "_PublishContext", bundle: dict[str, object]) -> None:
    """Publish the deterministic index comment, once and audited the same way."""
    comments = ctx.comments
    progress = ctx.progress
    marker = index_marker(bundle)
    if any(
        marker in cast("str", cast("dict[str, object]", c).get("body") or "") for c in comments
    ) or progress.get("index_done"):
        return
    if progress.get("index_pending"):
        raise Failure(CODE_WRITE_NEEDS_REVIEW)
    lines = [
        "## Evidence artifact index",
        "Event: `" + cast("str", cast("dict[str, object]", bundle["manifest"])["event_key"]) + "`",
    ]
    links = progress.get("done", {})
    for part in cast("list[dict[str, object]]", bundle["parts"]):
        url = cast("dict[str, object]", links).get(cast("str", part["marker"]))
        label = (
            cast("str", part["id"]) + " / " + cast("str", part["name"]) + " / " + str(part["part"])
        )
        lines.append("- [" + label + "](" + cast("str", url) + ")" if url else "- " + label)
    progress["index_pending"] = True
    ctx.save()
    try:
        _post_comment(
            ctx.github,
            ctx.number,
            index_markdown(bundle) + "\n\n" + "\n".join(lines) + "\n\n" + marker,
        )
    except Failure as exc:
        if str(exc.code).startswith("HTTP_4") and str(exc.code) != "HTTP_408":
            _clear_ambiguous(ctx.progress, "index_pending", ctx.save)
        raise
    progress["index_done"] = True
    _clear_ambiguous(ctx.progress, "index_pending", ctx.save)


def publish_parts(
    github: object,
    number: int,
    bundle: object,
    progress: dict[str, object],
    save: Callable[[], None],
) -> None:
    """Persist before each POST; an unobservable ambiguous write requires review."""
    guest = cast("_CommentHost", github)
    if not bundle:
        return
    if cast("dict[str, object]", bundle).get("binary_refs"):
        raise Failure(CODE_GRAPH_REQUIRES_S3)
    comments = [c for c in guest.comments(number) if trusted_comment(c)]
    ctx = _PublishContext(guest, number, comments, progress, save)
    bundle_map = cast("dict[str, object]", bundle)
    for part in cast("list[dict[str, object]]", bundle_map["parts"]):
        _publish_part(ctx, part)
    # A deterministic index comment provides direct navigation without editing human text.
    _publish_index(ctx, bundle_map)


def storage_objects(bundle: object) -> list[tuple[str, bytes]]:
    """Reconstitute exactly the persisted ASCII bytes; reject damaged bundles."""
    if not bundle:
        return []
    bundle_map = cast("dict[str, object]", bundle)
    manifest = cast("dict[str, object]", bundle_map["manifest"])
    text = encoded(manifest).encode("ascii")
    sha = hashlib.sha256(text).hexdigest()
    prefix = STORAGE_PREFIX + cast("str", manifest["event_key"]) + "/" + sha + "/"
    objects: list[tuple[str, bytes]] = [(prefix + "manifest.json", text)]
    binary_refs = cast("dict[str, object]", bundle_map.get("binary_refs", {}))
    for row in cast("list[dict[str, object]]", manifest["artifacts"]):
        row_id = cast("str", row["id"])
        if row_id in binary_refs:
            from graph_evidence import read_artifact

            try:
                raw = read_artifact(binary_refs[row_id])
            except (ValueError, OSError):
                raise Failure(CODE_STORAGE_INTEGRITY) from None
        else:
            subset = (
                p for p in cast("list[dict[str, object]]", bundle_map["parts"]) if p["id"] == row_id
            )
            parts = sorted(subset, key=lambda p: cast("int", p["part"]))
            raw = "".join(cast("str", p["text"]) for p in parts).encode("ascii")
        size = (
            row.get("stored_bytes")
            if manifest.get("format") == "socrat-evidence-v3"
            else row["stored_chars"]
        )
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise Failure(CODE_STORAGE_INTEGRITY)
        objects.append((prefix + row_id + "-" + cast("str", row["name"]), raw))
    return objects


def storage_markdown(objects: Sequence[tuple[str, bytes]]) -> str:
    """Render the bounded storage-body evidence section with public links."""
    if not objects:
        return ""
    origin = os.environ.get("SPI_EVIDENCE_PUBLIC_ORIGIN", DEFAULT_EVIDENCE_ORIGIN)
    if origin not in ALLOWED_EVIDENCE_ORIGINS:
        raise Failure(CODE_STORAGE_PUBLIC_ORIGIN)
    intro = (
        "\n\n## Reproducible evidence\nSanitized, bounded evidence; truncation and"
        " missing reads are recorded in the manifest. Not every byte was reviewed"
        " by the model. Sign-in required.\n"
    )
    links: list[str] = []
    for index, (key, _raw) in enumerate(objects):
        label = "MANIFEST" if index == 0 else key.rsplit("/", 1)[1]
        links.append("- [" + label + "](" + origin + "/" + key + ")")
    text = intro + "\n".join(links)

    try:
        manifest = json.loads(objects[0][1].decode("ascii"))
    except (ValueError, UnicodeError):
        return text
    text += navigation_markdown(manifest)
    keys = {key.rsplit("/", 1)[1]: key for key, _raw in objects}
    graphs: list[str] = []
    graph_link_budget = GRAPH_LINK_BUDGET_CHARS
    for row in cast("list[dict[str, object]]", manifest.get("artifacts", [])):
        source = cast("dict[str, object]", row.get("source", {}))
        if row.get("mime_type") != "image/png" or source.get("kind") != "grafana_panel_png":
            continue
        name = cast("str", row["id"]) + "-" + cast("str", row["name"])
        if name not in keys:
            raise Failure(CODE_STORAGE_INTEGRITY)
        title = " ".join(str(source.get("title", row["name"])).split())[:NAME_MAX_CHARS]
        title = (
            title.replace("\\", "\\\\")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        try:
            start = datetime.fromtimestamp(cast("int", source["from_ms"]) / 1000, UTC).isoformat()
            end = datetime.fromtimestamp(cast("int", source["to_ms"]) / 1000, UTC).isoformat()
        except (KeyError, TypeError, ValueError, OverflowError):
            raise Failure(CODE_STORAGE_INTEGRITY) from None
        dashboard = grafana_panel_url(source)
        link = (
            " [Open Grafana panel](" + dashboard + ")"
            if len(dashboard) <= graph_link_budget
            else " Panel URL omitted by publication budget; see manifest."
        )
        if len(dashboard) <= graph_link_budget:
            graph_link_budget -= len(dashboard)
        graphs.append(
            "- ["
            + title
            + " (PNG)]("
            + origin
            + "/"
            + keys[name]
            + ") \u2014 "
            + start
            + " to "
            + end
            + "."
            + link
        )
    if graphs:
        text += (
            "\n\n## Graphs\nPrivate PNG evidence; sign in through the existing"
            " Evidence/Authentik flow. Images are for human review, not model input.\n"
            + "\n".join(graphs)
        )
    return text


def navigation_markdown(manifest: object) -> str:
    """Human navigation is deterministic metadata, never model-generated prose."""
    lines: list[str] = ["", "## Grafana and Loki navigation"]
    budget = NAVIGATION_BUDGET_CHARS
    seen: set[str] = set()
    omitted = 0
    for link in cast("list[dict[str, object]]", manifest.get("links", []))[:NAVIGATION_LINK_LIMIT]:
        url = cast("str", link.get("url", ""))
        if not isinstance(url, str) or any(
            ord(c) < URL_PRINTABLE_MIN_ORDINAL or c in "<>()[]\\" for c in url
        ):
            omitted += 1
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            omitted += 1
            continue
        if (
            parsed.scheme != "https"
            or parsed.netloc != "grafana.socrat.alchemmist.xyz"
            or (
                parsed.path != "/explore"
                and re.fullmatch(r"/d/[A-Za-z0-9_-]{1,64}/_", parsed.path) is None
            )
            or parsed.fragment
        ):
            omitted += 1
            continue
        if url in seen:
            continue
        if len(url) > budget:
            omitted += 1
            continue
        seen.add(url)
        budget -= len(url)
        title = re.sub(r"[\\`\[\]<>\r\n]", " ", str(link.get("title", "Grafana Explore")))[
            :NAME_MAX_CHARS
        ]
        lines.append("- [" + title + "](" + url + ")")
    if omitted:
        lines.append(
            "- "
            + str(omitted)
            + " navigation links omitted by validation/publication budget; see manifest."
        )
    if not seen:
        lines.append("- No validated Explore link was collected; this is not evidence of health.")
    gaps = cast("list[dict[str, object]]", manifest.get("missing", []))
    if gaps:
        lines.extend(
            [
                "",
                "## Evidence gaps",
                "Missing/failed/empty reads are not proof of recovery. See the manifest for"
                " query/window details.",
            ]
        )
        for item in gaps[:GAP_ROW_LIMIT]:
            source = re.sub(r"[^A-Za-z0-9_.-]", "_", str(item.get("source", "unknown")))[:80]
            reason = re.sub(r"[^A-Za-z0-9_.-]", "_", str(item.get("reason", "unknown")))[:100]
            lines.append("- `" + source + "`: `" + reason + "`")
        if len(gaps) > GAP_ROW_LIMIT:
            lines.append("- Additional gaps are listed in the manifest.")
    return repair_markdown_links("\n".join(lines))


def grafana_panel_url(source: object) -> str:
    """Build the exact panel deep link from a validated manifest panel source."""
    source_map = cast("dict[str, object]", source)
    uid = source_map.get("dashboard_uid")
    panel = source_map.get("panel_id")
    if (
        not isinstance(uid, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", uid) is None
        or type(panel) is not int
        or panel < 1
    ):
        raise Failure(CODE_STORAGE_INTEGRITY)
    low, high = source_map.get("from_ms"), source_map.get("to_ms")
    if (
        type(low) is not int
        or type(high) is not int
        or not PANEL_TS_MIN_MS <= cast("int", low) < cast("int", high)
    ):
        raise Failure(CODE_STORAGE_INTEGRITY)
    params: list[tuple[str, str]] = [
        ("orgId", "1"),
        ("from", str(low)),
        ("to", str(high)),
        ("viewPanel", str(panel)),
        ("timezone", "utc"),
        ("forceLogin", "true"),
    ]
    for key, value in sorted(cast("dict[str, object]", source_map.get("variables", {})).items()):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key) is None or SECRET_KEY.search(key):
            raise Failure(CODE_STORAGE_INTEGRITY)
        values = value if isinstance(value, list) else [value]
        params.extend(("var-" + key, str(item)) for item in values)
    return GRAFANA_ORIGIN + "/d/" + quote(cast("str", uid), safe="") + "/_?" + urlencode(params)
