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


def _author(entry: dict[str, object]) -> dict[str, object]:
    return cast("dict[str, object]", entry.get("author") or {})


def _connection_entries(pr: dict[str, object], key: str) -> list[dict[str, object]]:
    return cast(
        "list[dict[str, object]]", cast("dict[str, object]", pr.get(key, {})).get("nodes", [])
    )


def _state_blockers(
    pr: dict[str, object], reviewers: set[str], handlers: set[str], blockers: list[str]
) -> None:
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


def _ci_blockers(pr: dict[str, object], blockers: list[str]) -> None:
    rollup = cast("dict[str, object]", pr.get("statusCheckRollup") or {})
    checks = cast("dict[str, object]", rollup.get("contexts", {}))
    if not checks.get("nodes"):
        blockers.append("No remote CI evidence")
    for check in cast("list[dict[str, object]]", checks.get("nodes", [])):
        ok = (
            check.get("__typename") == "CheckRun"
            and check.get("status") == "COMPLETED"
            and check.get("conclusion") == "SUCCESS"
        ) or (check.get("__typename") == "StatusContext" and check.get("state") == "SUCCESS")
        if not ok:
            blockers.append("CI not green: " + str(check.get("name") or check.get("context")))


def _pagination_blockers(
    pr: dict[str, object], checks: dict[str, object], blockers: list[str]
) -> None:
    sections = [
        (cast("dict[str, object]", pr.get(k, {})), "hasNextPage")
        for k in ("reviews", "comments", "reviewThreads")
    ] + [
        (cast("dict[str, object]", pr.get("commits", {})), "hasPreviousPage"),
        (checks, "hasNextPage"),
    ]
    threads = cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", pr.get("reviewThreads", {})).get("nodes", []),
    )
    sections += [(cast("dict[str, object]", t.get("comments", {})), "hasNextPage") for t in threads]
    if not all(_complete_connection(section, direction) for section, direction in sections):
        blockers.append("Incomplete pagination; cannot authorize handoff")


def _review_blockers(pr: dict[str, object], reviewers: set[str], blockers: list[str]) -> None:
    reviews = _connection_entries(pr, "reviews")
    observed_bots = {
        _author(r).get("login") for r in reviews if _author(r).get("__typename") == "Bot"
    }
    for actor in set(reviewers) | (observed_bots - {None}):
        current = [
            r
            for r in reviews
            if _author(r).get("login") == actor
            and cast("dict[str, object]", r.get("commit") or {}).get("oid") == pr.get("headRefOid")
        ]
        if not current or current[-1].get("state") not in ("APPROVED", "COMMENTED"):
            blockers.append("Bot review incomplete on current head: " + cast("str", actor))
    if any(r.get("state") == "PENDING" for r in reviews):
        blockers.append("Pending review")


def _comment_evidence(
    comments: list[dict[str, object]], handlers: set[str]
) -> dict[str, list[tuple[object, dict[str, object]]]]:
    evidence: dict[str, list[tuple[object, dict[str, object]]]] = {}
    for reply in comments:
        if _author(reply).get("login") not in handlers:
            continue
        for raw in re.findall(
            r"<!--\s*rtr:(\{.*?\})\s*-->", cast("str", reply.get("body", "")), re.DOTALL
        ):
            try:
                item = json.loads(raw)
                evidence.setdefault(item["comment"], []).append((item, reply))
            except (ValueError, KeyError, TypeError):
                pass
    return evidence


class DispositionCtx(TypedDict):
    """Evidence gathered for the disposition scan of one PR."""

    evidence: dict[str, list[tuple[object, dict[str, object]]]]
    commits: set[str]
    repo_url: str
    handlers: set[str]
    reviewers: set[str]


def _disposition_blockers(
    remarks: list[dict[str, object]], ctx: DispositionCtx, blockers: list[str]
) -> None:
    evidence = ctx["evidence"]
    commits = ctx["commits"]
    repo_url = ctx["repo_url"]
    handlers = ctx["handlers"]
    reviewers = ctx["reviewers"]
    for remark in remarks:
        author = _author(remark)
        is_bot = author.get("__typename") == "Bot" or cast("str", author.get("login")) in reviewers
        # Only protocol replies by the explicitly trusted handler are audit records.
        if not is_bot or (
            author.get("login") in handlers and "<!-- rtr:" in cast("str", remark.get("body", ""))
        ):
            continue
        valid = False
        for item, reply in evidence.get(cast("str", remark["id"]), []):
            if reply.get("id") == remark["id"]:
                continue
            if cast("dict[str, object]", item).get("decision") == "fixed":
                sha = cast("str", cast("dict[str, object]", item).get("commit", ""))
                valid |= bool(
                    re.fullmatch("[0-9a-f]{40}", sha)
                    and sha in commits
                    and repo_url + "/commit/" + sha in cast("str", reply.get("body", ""))
                )
            elif cast("dict[str, object]", item).get("decision") == "irrelevant":
                valid |= (
                    isinstance(cast("dict[str, object]", item).get("reason"), str)
                    and len(cast("str", cast("dict[str, object]", item)["reason"]).strip()) >= 40
                )
        if not valid:
            blockers.append("Missing evidenced disposition: " + cast("str", remark["id"]))


def _thread_blockers(
    threads: list[dict[str, object]], reviewers: set[str], blockers: list[str]
) -> None:
    for thread in threads:
        bot_thread = any(
            _author(c).get("__typename") == "Bot" or _author(c).get("login") in reviewers
            for c in cast(
                "list[dict[str, object]]",
                cast("dict[str, object]", thread.get("comments", {})).get("nodes", []),
            )
        )
        if bot_thread and not thread.get("isResolved"):
            blockers.append("Unresolved bot thread: " + cast("str", thread["id"]))


def assess(pr, reviewers, handlers):
    pr_dict = cast("dict[str, object]", pr)
    blockers: list[str] = []
    _state_blockers(pr_dict, set(reviewers), set(handlers), blockers)
    _ci_blockers(pr_dict, blockers)
    rollup = cast("dict[str, object]", pr_dict.get("statusCheckRollup") or {})
    checks = cast("dict[str, object]", rollup.get("contexts", {}))
    _pagination_blockers(pr_dict, checks, blockers)
    threads = cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", pr_dict.get("reviewThreads", {})).get("nodes", []),
    )
    _review_blockers(pr_dict, set(reviewers), blockers)
    general = _connection_entries(pr_dict, "comments")
    comments = general + [
        c
        for t in threads
        for c in cast(
            "list[dict[str, object]]",
            cast("dict[str, object]", t.get("comments", {})).get("nodes", []),
        )
    ]
    # Review summaries are remarks too; general PR replies can account for them.
    remarks = comments + [r for r in _connection_entries(pr_dict, "reviews") if r.get("body")]
    evidence = _comment_evidence(comments, set(handlers))
    commits = {
        cast("str", cast("dict[str, object]", n["commit"])["oid"])
        for n in _connection_entries(pr_dict, "commits")
    }
    repo_url = cast("str", pr_dict.get("url", "")).split("/pull/")[0]
    disposition_ctx: DispositionCtx = {
        "evidence": evidence,
        "commits": commits,
        "repo_url": repo_url,
        "handlers": set(handlers),
        "reviewers": set(reviewers),
    }
    _disposition_blockers(remarks, disposition_ctx, blockers)
    _thread_blockers(threads, set(reviewers), blockers)
    return {
        "ready_to_review": not blockers,
        "head": pr_dict.get("headRefOid"),
        "state": pr_dict.get("state"),
        "url": pr_dict.get("url"),
        "blockers": blockers,
    }


def fetch(repo, number):
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
        report["checked_at"] = datetime.datetime.now(datetime.UTC).isoformat()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ready_to_review"] else 1
    except (
        ValueError, KeyError, TypeError, RuntimeError, OSError,
        subprocess.SubprocessError, IndexError,
    ) as exc:
        return _error_report(type(exc).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
