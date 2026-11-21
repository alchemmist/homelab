"""Only callable via the trusted signer. Validate mutable GitHub state before each write."""

import hashlib
import json
import re
import runpy
import types
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict, cast

G = runpy.run_path(str(Path(__file__).with_name("ready_gate.py")))
REVIEWERS = {"socrat-steward", "coderabbitai"}
HANDLERS = {"alchemmist"}

Seen = dict[tuple[str, object, object], bool]
Row = dict[str, object]


class Scan(TypedDict):
    """Shared state for scanning one PR snapshot."""

    rows: list[Row]
    seen: Seen
    head: str
    blockers: list[str]


class DisposeCtx(TypedDict):
    """Everything the disposition writer needs from the enclosing lifecycle."""

    api: types.FunctionType
    issue: str
    rows: list[Row]
    head: str
    check: Callable[[object], None]
    owned: types.FunctionType
    n: object
    url: str


def marker_seen(replies: list[dict[str, object]]) -> Seen:
    """Collect disposition markers already posted by the trusted handlers."""
    seen: Seen = {}
    for c in replies:
        auth = cast("dict[str, object]", c.get("author") or {})
        if auth.get("login") not in HANDLERS:
            continue
        for data in re.findall(r"<!-- rtr:(\{[^\n]+?\}) -->", cast("str", c.get("body", ""))):
            try:
                j = json.loads(data)
                seen[(j["comment"], j.get("digest"), j.get("head"))] = True
            except (ValueError, KeyError):
                pass
    return seen


def add_row(
    c: dict[str, object], scan: Scan, *, thread: str | None = None, resolved: bool = False
) -> None:
    """Fold one review/reply into the scanned rows, tracking blockers."""
    rows = scan["rows"]
    seen = scan["seen"]
    head = scan["head"]
    auth = cast("dict[str, object]", c.get("author") or {})
    body = cast("str", c.get("body") or "")
    if not body or (auth.get("__typename") != "Bot" and auth.get("login") not in REVIEWERS):
        return
    digest = hashlib.sha256(body.encode()).hexdigest()
    replied = (c["id"], digest, head) in seen
    if not replied or (thread and not resolved):
        rows.append(
            {
                "id": c["id"],
                "thread": thread,
                "resolved": resolved,
                "replied": replied,
                "author": auth["login"],
                "original": cast("dict[str, object]", c.get("originalCommit") or {}).get("oid"),
                "body": body[:24000],
                "truncated": len(body) > 24000,
                "digest": digest,
                "url": c.get("url"),
            }
        )
        scan["blockers"].append("Current disposition pending: " + cast("str", c["id"]))


def scan_threads(v: dict[str, object], scan: Scan) -> None:
    """Scan comments, reviews and threads, populating rows and blockers."""
    rows = scan["rows"]
    for c in cast(
        "list[dict[str, object]]", cast("dict[str, object]", v["comments"])["nodes"]
    ) + cast("list[dict[str, object]]", cast("dict[str, object]", v["reviews"])["nodes"]):
        add_row(c, scan)
    for t in cast(
        "list[dict[str, object]]", cast("dict[str, object]", v["reviewThreads"])["nodes"]
    ):
        tc = cast("list[dict[str, object]]", cast("dict[str, object]", t["comments"])["nodes"])
        mixed = any(
            cast("dict[str, object]", c.get("author") or {}).get("__typename") != "Bot"
            and not (
                cast("dict[str, object]", c.get("author") or {}).get("login") in HANDLERS
                and "<!-- rtr:" in cast("str", c.get("body", ""))
            )
            for c in tc
        )
        for c in tc:
            add_row(c, scan, thread=cast("str", t["id"]), resolved=bool(t["isResolved"]))
        if mixed and not t["isResolved"]:
            for row in rows:
                if row["thread"] == t["id"]:
                    row["human_discussion"] = True


def snapshot(
    api: types.FunctionType, n: object, head: str, check: Callable[[object], None]
) -> tuple[dict[str, object], list[Row], object]:
    """Pull one consistent review-state snapshot of the PR."""
    q = api(
        "graphql",
        {
            "query": G["QUERY"].replace(
                "reviewThreads(first:100){nodes{id isResolved comments(first:100){nodes{id author",
                "reviewThreads(first:100){nodes{id isResolved comments(first:100){nodes{id "
                "originalCommit{oid} author",
            ),
            "variables": {"owner": "alchemmist", "repo": "monori", "number": n},
        },
    )
    check(not q.get("errors"))
    v = q["data"]["repository"]["pullRequest"]
    check(v["headRefOid"] == head)
    v["statusCheckRollup"] = v["tip"]["nodes"][-1]["commit"]["statusCheckRollup"] or {}
    a = G["assess"](v, REVIEWERS, HANDLERS)
    ctx = v["statusCheckRollup"].get("contexts", {}).get("nodes", [])
    if not any(y.get("name") == "Quality Graph" and y.get("conclusion") == "SUCCESS" for y in ctx):
        a["blockers"].append("Missing successful Quality Graph aggregate")
    # Required gate above is in addition to all visible checks, not a replacement.
    rows: list[Row] = []
    replies = v["comments"]["nodes"] + [
        c for t in v["reviewThreads"]["nodes"] for c in t["comments"]["nodes"]
    ]
    seen = marker_seen(replies)
    scan: Scan = {
        "rows": rows,
        "seen": seen,
        "head": head,
        "blockers": cast("list[str]", a["blockers"]),
    }
    scan_threads(v, scan)
    a["ready_to_review"] = not a["blockers"]
    return a, rows, ctx


def dispose(x: dict[str, object], ctx: DisposeCtx) -> dict[str, object]:
    """Post one reviewed disposition reply; resolve its thread when safe."""
    api = ctx["api"]
    issue = ctx["issue"]
    rows = ctx["rows"]
    head = ctx["head"]
    check = ctx["check"]
    owned = ctx["owned"]
    n = ctx["n"]
    url = ctx["url"]
    r = next((r for r in rows if r["id"] == x["remark"] and r["digest"] == x["digest"]), None)
    check(r is not None and not r.get("human_discussion"))
    r = cast("Row", r)
    decision = x["decision"]
    reason = x["reason"]
    check(
        decision in ("fixed", "irrelevant")
        and isinstance(reason, str)
        and 40 <= len(reason) <= 1100
        and not re.search(r"[@<>\x00-\x1f]|https?://|github_pat_|Bearer", reason, re.IGNORECASE)
    )
    j = {"comment": r["id"], "digest": r["digest"], "head": head, "decision": decision}
    body = cast("str", reason)
    if decision == "fixed":
        check(x["commit"] == head)
        j["commit"] = head
        body += " Fixed in " + url + "/commit/" + head
    else:
        j["reason"] = reason
    body += "\n\n<!-- rtr:" + json.dumps(j, separators=(",", ":")) + " -->"
    owned(n, head)
    if not r["replied"]:
        if r["thread"]:
            res = api(
                "graphql",
                {
                    "query": (
                        "mutation($t:ID!,$b:String!){addPullRequestReviewThreadReply("
                        "input:{pullRequestReviewThreadId:$t,body:$b}){comment{id}}}"
                    ),
                    "variables": {"t": r["thread"], "b": body},
                },
            )
            check(
                res.get("data", {})
                .get("addPullRequestReviewThreadReply", {})
                .get("comment", {})
                .get("id")
            )
        else:
            check(api(issue + "/comments", {"body": f"Regarding {r['url']}: " + body})["id"])
    if r["thread"] and not r["resolved"]:
        # Re-read after reply. Never resolve a thread that has other unanswered remarks.
        remaining = [
            row for row in snapshot(api, n, head, check)[1] if row["thread"] == r["thread"]
        ]
        if any(not row["replied"] or row.get("human_discussion") for row in remaining):
            return {"handled": r["id"], "thread": "awaiting other dispositions", "head": head}
        owned(n, head)
        res = api(
            "graphql",
            {
                "query": (
                    "mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}"
                ),
                "variables": {"t": r["thread"]},
            },
        )
        check(
            res.get("data", {}).get("resolveReviewThread", {}).get("thread", {}).get("isResolved")
        )
    return {"handled": r["id"], "head": head}


def lifecycle(x, api, owned, check):
    n = x["pr"]
    head = x["head"]
    p = owned(n, head)
    check(
        p["head"]["ref"].startswith("openhands/issue-")
        and "mutation-pr" in {l["name"] for l in p["labels"]}
    )
    mode = x["action"]
    issue = f"issues/{n}"
    a, rows, ctx = snapshot(api, n, head, check)
    blockers = cast("list[str]", a["blockers"])
    incomplete = any("pagination" in b for b in blockers)
    url = "https://github.com/alchemmist/monori"
    ready = "mutation-ready"
    if ready in {l["name"] for l in p["labels"]} and not a["ready_to_review"]:
        api(issue + "/labels/" + ready, method="DELETE")
    if mode == "life_snapshot":
        return dict(
            a,
            files=[
                {k: f.get(k, "") for k in ("filename", "status", "patch")}
                for f in api(f"pulls/{n}/files?per_page=20")
            ],
            remarks=rows,
            checks=[
                {
                    "name": c.get("name", c.get("context")),
                    "status": c.get("status", c.get("state")),
                    "conclusion": c.get("conclusion"),
                    "url": c.get("detailsUrl", c.get("targetUrl")),
                }
                for c in cast("list[dict[str, object]]", ctx)
            ],
        )
    check(not incomplete)
    if mode == "life_request":
        bot = x["reviewer"]
        check(bot in REVIEWERS and "Bot review incomplete on current head: " + bot in blockers)
        marker = f"<!-- mutation-review-request:{bot}:{head} -->"
        comments = api(issue + "/comments?per_page=100")
        check(len(comments) < 100)
        previous = [
            c for c in comments if c["user"]["login"] == "alchemmist" and marker in c["body"]
        ]
        if previous:
            return {"requested": False}
        owned(n, head)
        api(
            issue + "/comments",
            {
                "body": ("@coderabbitai review" if bot == "coderabbitai" else "/review")
                + "\n\n"
                + marker
            },
        )
        return {"requested": True}
    if mode == "life_ready":
        check(a["ready_to_review"] and snapshot(api, n, head, check)[0] == a)
        owned(n, head)
        api(issue + "/labels", {"labels": [ready]})
        return {"ready": True, "head": head}
    check(mode == "life_dispose")
    dispose_ctx: DisposeCtx = {
        "api": api,
        "issue": issue,
        "rows": rows,
        "head": head,
        "check": check,
        "owned": owned,
        "n": n,
        "url": url,
    }
    return dispose(x, dispose_ctx)
