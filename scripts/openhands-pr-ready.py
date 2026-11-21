#!/usr/bin/env python3
"""Read-only, fail-closed PR handoff audit. Never posts, resolves, pushes or merges.

Run in trusted automation, not with a write credential inside a coding sandbox.
Requires gh authentication. Explicit reviewer/handler identities are mandatory.
"""

import argparse
import datetime
import json
import re
import subprocess
from collections.abc import Collection, Mapping

QUERY = """query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){
url headRefOid state isDraft mergeable
commits(last:100){nodes{commit{oid}} pageInfo{hasPreviousPage}}
reviews(first:100){nodes{id author{login __typename} state body url commit{oid}} pageInfo{hasNextPage}}
comments(first:100){nodes{id author{login __typename} body url} pageInfo{hasNextPage}}
reviewThreads(first:100){nodes{id isResolved comments(first:100){nodes{id author{login __typename} body url} pageInfo{hasNextPage}}} pageInfo{hasNextPage}}
tip:commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){nodes{__typename ... on CheckRun{name status conclusion detailsUrl} ... on StatusContext{context state targetUrl}} pageInfo{hasNextPage}}}}}}
}}}"""


def _complete_connection(value: object, direction: str) -> bool:
    """Require explicit native end-of-pagination evidence, not falsy/missing metadata."""
    if not isinstance(value, dict):
        return False
    page = value.get("pageInfo")
    if not isinstance(value.get("nodes"), list) or not isinstance(page, dict):
        return False
    return (
        page.get(direction) is False
        and not page.get("hasNextPage")
        and not page.get("hasPreviousPage")
    )


def _record(value: object) -> dict[str, object]:
    """Return a JSON object record, or an empty record for missing fields."""
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    """Return a JSON array, or an empty array for missing fields."""
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    """Return a string value, or the empty string for non-string fields."""
    return value if isinstance(value, str) else ""


def assess(pr: Mapping[str, object], reviewers: Collection[str], handlers: Collection[str]):
    reviewer_handles = set(reviewers)
    handler_handles = set(handlers)
    blockers: list[str] = []
    if pr.get("state") != "OPEN":
        blockers.append("PR is not open")
    head = pr.get("headRefOid")
    if not isinstance(head, str) or not re.fullmatch("[0-9a-f]{40}", head):
        blockers.append("Missing or invalid current head identity")
    if not reviewer_handles or not handler_handles:
        blockers.append("Required reviewer and trusted handler identities must be configured")
    if pr.get("mergeable") != "MERGEABLE":
        blockers.append("PR conflicts or mergeability unknown")
    if bool(pr.get("isDraft")):
        blockers.append("PR is still draft")
    checks = _record(_record(pr.get("statusCheckRollup")).get("contexts"))
    if not checks.get("nodes"):
        blockers.append("No remote CI evidence")
    for check in [_record(x) for x in _list(checks.get("nodes", []))]:
        ok = (
            check.get("__typename") == "CheckRun"
            and check.get("status") == "COMPLETED"
            and check.get("conclusion") == "SUCCESS"
        ) or (check.get("__typename") == "StatusContext" and check.get("state") == "SUCCESS")
        if not ok:
            blockers.append("CI not green: " + str(check.get("name") or check.get("context")))
    sections: list[tuple[dict[str, object], str]] = [
        (_record(pr.get(k)), "hasNextPage") for k in ("reviews", "comments", "reviewThreads")
    ] + [(_record(pr.get("commits")), "hasPreviousPage"), (checks, "hasNextPage")]
    threads = [_record(x) for x in _list(_record(pr.get("reviewThreads")).get("nodes", []))]
    sections += [(_record(t.get("comments")), "hasNextPage") for t in threads]
    if not all(_complete_connection(section, direction) for section, direction in sections):
        blockers.append("Incomplete pagination; cannot authorize handoff")
    reviews = [_record(x) for x in _list(_record(pr.get("reviews")).get("nodes", []))]
    observed_bots: set[str] = set()
    for r in reviews:
        author = _record(r.get("author"))
        if author.get("__typename") == "Bot":
            login = author.get("login")
            if isinstance(login, str):
                observed_bots.add(login)
    for actor in reviewer_handles | observed_bots:
        current = [
            r
            for r in reviews
            if _record(r.get("author")).get("login") == actor
            and _record(r.get("commit")).get("oid") == pr.get("headRefOid")
        ]
        if not current or current[-1].get("state") not in ("APPROVED", "COMMENTED"):
            blockers.append("Bot review incomplete on current head: " + actor)
    if any(r.get("state") == "PENDING" for r in reviews):
        blockers.append("Pending review")
    general = _list(_record(pr.get("comments")).get("nodes", []))
    comments: list[object] = general + [
        c for t in threads for c in _list(_record(t.get("comments")).get("nodes", []))
    ]
    # Review summaries are remarks too; general PR replies can account for them.
    remarks: list[object] = comments + [r for r in reviews if bool(r.get("body"))]
    evidence: dict[object, list[tuple[dict[str, object], dict[str, object]]]] = {}
    for reply in comments:
        reply_record = _record(reply)
        if _record(reply_record.get("author")).get("login") not in handlers:
            continue
        body = reply_record.get("body", "")
        for raw in re.findall(
            r"<!--\s*rtr:(\{.*?\})\s*-->", body if isinstance(body, str) else "", re.S
        ):
            try:
                item = _record(json.loads(raw))
                evidence.setdefault(item["comment"], []).append((item, reply_record))
            except (ValueError, KeyError, TypeError):
                pass
    commits = {
        _record(_record(n)["commit"])["oid"]
        for n in _list(_record(pr.get("commits")).get("nodes", []))
    }
    repo_url = _text(pr.get("url")).split("/pull/")[0]
    for remark_value in remarks:
        remark = _record(remark_value)
        author = _record(remark.get("author"))
        is_bot = author.get("__typename") == "Bot" or author.get("login") in reviewer_handles
        # Only protocol replies by the explicitly trusted handler are audit records.
        remark_body = remark.get("body", "")
        if not is_bot or (
            author.get("login") in handler_handles
            and isinstance(remark_body, str)
            and "<!-- rtr:" in remark_body
        ):
            continue
        valid = False
        for item, reply in evidence.get(remark.get("id"), []):
            if reply.get("id") == remark.get("id"):
                continue
            if item.get("decision") == "fixed":
                sha = _text(item.get("commit", ""))
                reply_body = reply.get("body", "")
                valid |= bool(
                    re.fullmatch("[0-9a-f]{40}", sha)
                    and sha in commits
                    and isinstance(reply_body, str)
                    and repo_url + "/commit/" + sha in reply_body
                )
            elif item.get("decision") == "irrelevant":
                reason = item.get("reason")
                valid |= bool(isinstance(reason, str) and len(reason.strip()) >= 40)
        if not valid:
            blockers.append("Missing evidenced disposition: " + _text(remark.get("id")))
    for thread in threads:
        bot_thread = any(
            _record(c.get("author")).get("__typename") == "Bot"
            or _record(c.get("author")).get("login") in reviewers
            for c in [_record(x) for x in _list(_record(thread.get("comments")).get("nodes", []))]
        )
        if bot_thread and not bool(thread.get("isResolved")):
            blockers.append("Unresolved bot thread: " + _text(thread.get("id")))
    return {
        "ready_to_review": not blockers,
        "head": pr.get("headRefOid"),
        "state": pr.get("state"),
        "url": pr.get("url"),
        "blockers": blockers,
    }


def fetch(repo: str, number: int):
    owner, name = repo.split("/")
    out = subprocess.check_output(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            "query=" + QUERY,
            "-f",
            "owner=" + owner,
            "-f",
            "repo=" + name,
            "-F",
            "number=" + str(number),
        ],
        text=True,
    )
    response = json.loads(out)
    if response.get("errors"):
        raise RuntimeError("GitHub GraphQL returned errors")
    pr = response["data"]["repository"]["pullRequest"]
    pr["statusCheckRollup"] = (
        pr.get("tip").get("nodes", [{}])[-1].get("commit", {}).get("statusCheckRollup")
    )
    return _record(pr)


_HANDOFF_SNAPSHOT_COUNT = 2


def _error_report(error_name: str) -> int:
    """Emit the existing sanitized CLI failure schema, never exception payloads."""
    print(json.dumps({"ready_to_review": False, "error": error_name}))
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="alchemmist/monori")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--reviewer", action="append", default=[])
    parser.add_argument("--handler", action="append", default=[])
    args = parser.parse_args()
    try:
        report = None
        for _ in range(_HANDOFF_SNAPSHOT_COUNT):
            snapshot = fetch(args.repo, args.pr)
            if report is not None and snapshot["headRefOid"] != report["head"]:
                report["ready_to_review"] = False
                report["blockers"].append("Head changed during audit")
                break
            fresh_report = assess(snapshot, set(args.reviewer), set(args.handler))
            if report is not None and fresh_report != report:
                fresh_report["ready_to_review"] = False
                fresh_report["blockers"].append("PR state changed during audit")
            report = fresh_report
        if report is None:
            return _error_report("RuntimeError")
        report["checked_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ready_to_review"] else 1
    except Exception as exc:
        return _error_report(type(exc).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
