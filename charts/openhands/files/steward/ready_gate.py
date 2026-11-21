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
from typing import TypedDict, cast

QUERY = """query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){
url headRefOid state isDraft mergeable
commits(last:100){nodes{commit{oid}} pageInfo{hasPreviousPage}}
reviews(first:100){nodes{id author{login __typename} state body url commit{oid}} pageInfo{hasNextPage}}
comments(first:100){nodes{id author{login __typename} body url} pageInfo{hasNextPage}}
reviewThreads(first:100){nodes{id isResolved comments(first:100){nodes{id author{login __typename} body url} pageInfo{hasNextPage}}} pageInfo{hasNextPage}}
tip:commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){nodes{__typename ... on CheckRun{name status conclusion detailsUrl} ... on StatusContext{context state targetUrl}} pageInfo{hasNextPage}}}}}}
}}}"""


class _NodeList(TypedDict, total=False):
    nodes: list[dict[str, object]]
    pageInfo: dict[str, object]


class _Thread(TypedDict, total=False):
    id: str
    isResolved: bool
    comments: _NodeList


class _ThreadsPage(TypedDict, total=False):
    nodes: list[_Thread]


class _CommitNode(TypedDict, total=False):
    commit: dict[str, object]


class _CommitsPage(TypedDict, total=False):
    nodes: list[_CommitNode]


class _Rollup(TypedDict, total=False):
    contexts: _NodeList


class _PullRequest(TypedDict, total=False):
    url: str
    headRefOid: str
    state: str
    mergeable: str
    isDraft: bool
    reviews: _NodeList
    comments: _NodeList
    reviewThreads: _ThreadsPage
    commits: _CommitsPage
    statusCheckRollup: _Rollup


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


def assess(pr: _PullRequest, reviewers: set[str], handlers: set[str]):
    blockers = []
    if pr.get("state") != "OPEN":
        blockers.append("PR is not open")
    head = pr.get("headRefOid")
    if not isinstance(head, str) or not re.fullmatch("[0-9a-f]{40}", head):
        blockers.append("Missing or invalid current head identity")
    if not reviewers or not handlers:
        blockers.append("Required reviewer and trusted handler identities must be configured")
    if pr.get("mergeable") != "MERGEABLE":
        blockers.append("PR conflicts or mergeability unknown")
    if pr.get("isDraft"):
        blockers.append("PR is still draft")
    checks = (pr.get("statusCheckRollup") or {}).get("contexts", {})
    if not checks.get("nodes"):
        blockers.append("No remote CI evidence")
    for check in checks.get("nodes", []):
        ok = (
            check.get("__typename") == "CheckRun"
            and check.get("status") == "COMPLETED"
            and check.get("conclusion") == "SUCCESS"
        ) or (check.get("__typename") == "StatusContext" and check.get("state") == "SUCCESS")
        if not ok:
            blockers.append("CI not green: " + str(check.get("name") or check.get("context")))
    raw_pr = cast("dict[str, object]", pr)
    sections = [
        (raw_pr.get(k) or {}, "hasNextPage") for k in ("reviews", "comments", "reviewThreads")
    ] + [(raw_pr.get("commits") or {}, "hasPreviousPage"), (checks, "hasNextPage")]
    threads = pr.get("reviewThreads", {}).get("nodes", [])
    sections += [(t.get("comments", {}), "hasNextPage") for t in threads]
    if not all(_complete_connection(section, direction) for section, direction in sections):
        blockers.append("Incomplete pagination; cannot authorize handoff")
    reviews = pr.get("reviews", {}).get("nodes", [])
    observed_bots = {
        cast("dict[str, object]", r.get("author") or {}).get("login")
        for r in reviews
        if cast("dict[str, object]", r.get("author") or {}).get("__typename") == "Bot"
        and cast("dict[str, object]", r.get("author") or {}).get("login") is not None
    }
    for actor in set(reviewers) | cast("set[str]", observed_bots):
        current = [
            r
            for r in reviews
            if cast("dict[str, object]", r.get("author") or {}).get("login") == actor
            and cast("dict[str, object]", r.get("commit") or {}).get("oid") == pr.get("headRefOid")
        ]
        if not current or current[-1].get("state") not in ("APPROVED", "COMMENTED"):
            blockers.append("Bot review incomplete on current head: " + actor)
    if any(r.get("state") == "PENDING" for r in reviews):
        blockers.append("Pending review")
    general = pr.get("comments", {}).get("nodes", [])
    comments = general + [c for t in threads for c in t.get("comments", {}).get("nodes", [])]
    # Review summaries are remarks too; general PR replies can account for them.
    remarks = comments + [r for r in reviews if r.get("body")]
    evidence: dict[object, list[tuple[dict[str, object], dict[str, object]]]] = {}
    for reply in comments:
        if cast("dict[str, object]", reply.get("author") or {}).get("login") not in handlers:
            continue
        body = cast("str", reply.get("body", ""))
        for raw in re.findall(r"<!--\s*rtr:(\{.*?\})\s*-->", body, re.S):
            try:
                item = json.loads(raw)
                evidence.setdefault(item["comment"], []).append((item, reply))
            except (ValueError, KeyError, TypeError):
                pass
    commits = {n["commit"]["oid"] for n in pr.get("commits", {}).get("nodes", [])}
    repo_url = pr.get("url", "").split("/pull/")[0]
    for remark in remarks:
        author = cast("dict[str, object]", remark.get("author") or {})
        is_bot = author.get("__typename") == "Bot" or author.get("login") in reviewers
        # Only protocol replies by the explicitly trusted handler are audit records.
        if not is_bot or (
            author.get("login") in handlers and "<!-- rtr:" in cast("str", remark.get("body", ""))
        ):
            continue
        valid = False
        for item, reply in evidence.get(remark["id"], []):
            if reply.get("id") == remark["id"]:
                continue
            if item.get("decision") == "fixed":
                sha = cast("str", item.get("commit", ""))
                valid |= bool(
                    re.fullmatch("[0-9a-f]{40}", sha)
                    and sha in commits
                    and repo_url + "/commit/" + sha in cast("str", reply.get("body", ""))
                )
            elif item.get("decision") == "irrelevant":
                reason = item.get("reason")
                valid |= isinstance(reason, str) and len(reason.strip()) >= 40
        if not valid:
            blockers.append("Missing evidenced disposition: " + cast("str", remark["id"]))
    for thread in threads:
        bot_thread = any(
            cast("dict[str, object]", c.get("author") or {}).get("__typename") == "Bot"
            or cast("dict[str, object]", c.get("author") or {}).get("login") in reviewers
            for c in thread.get("comments", {}).get("nodes", [])
        )
        if bot_thread and not thread.get("isResolved"):
            blockers.append("Unresolved bot thread: " + thread["id"])
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
        pr.get("tip", {}).get("nodes", [{}])[-1].get("commit", {}).get("statusCheckRollup")
    )
    return pr


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
