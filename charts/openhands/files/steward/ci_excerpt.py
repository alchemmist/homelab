"""Bounded authorized Actions log read. Never forward credential across redirect or return full logs."""

import http.client
import re
from collections.abc import Callable
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import OpenerDirector, Request, build_opener


def open_log(
    op: OpenerDirector, _no_redirect: object, job_id: str, check: Callable[[object], None]
) -> http.client.HTTPResponse | None:
    """Fetch CI job logs, following only allow-listed redirect hosts."""
    req = Request(
        "https://api.github.com/repos/alchemmist/monori/actions/jobs/" + job_id + "/logs",
        headers={
            "Authorization": "Bearer " + Path("/credential/token").read_text().strip(),
            "User-Agent": "mutation-pr-lifecycle",
        },
    )
    try:
        return cast("http.client.HTTPResponse", op.open(req, timeout=10))
    except HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            return None
        loc = e.headers.get("Location", "")
        u = urlparse(loc)
        check(
            u.scheme == "https"
            and not u.username
            and not u.password
            and u.port in (None, 443)
            and (u.hostname or "").endswith(
                (".blob.core.windows.net", ".actions.githubusercontent.com")
            )
        )
        return cast("http.client.HTTPResponse", op.open(Request(loc), timeout=10))


def scan_lines(
    lines: list[str], name: str, dest: str, out: list[str], summaries: list[str]
) -> None:
    """Select failure lines for one file, redacting tokens and links."""
    for line in lines:
        line = re.sub(r"^\S+Z\s+|\x1b\[[0-9;]*m", "", line)
        line = re.sub(r"https?://\S+", "[link]", line)
        if re.search(
            r"token|password|secret|authorization|gh[pousr]_|github_pat_|bearer|cookie|@",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.search(r"failed|error|\b[A-Z]{1,5}\d{3}\b", line, re.IGNORECASE):
            if dest in line and len(out) < 10:
                out.append(name + ": " + line[:220])
            elif len(summaries) < 6:
                summaries.append(name + ": " + line[:180])


def extract(n, head, api, no_redirect, check):
    """Extract CI log excerpts for the changed file of a mutation PR."""
    files = api(f"pulls/{n}/files?per_page=20")
    check(len(files) == 1 and files[0]["status"] == "added")
    dest = files[0]["filename"]
    check(re.fullmatch(r"(ci/tests|server/tests/unit)/test_[\w]+\.py", dest))
    runs = api("commits/" + head + "/check-runs?per_page=100")
    out: list[str] = []
    summaries: list[str] = []
    for r in runs["check_runs"]:
        if r.get("conclusion") != "failure":
            continue
        m = re.fullmatch(
            r"https://github.com/alchemmist/monori/actions/runs/\d+/job/(\d+)",
            r.get("details_url") or "",
        )
        if not m:
            continue
        job = api("actions/jobs/" + m[1])
        check(job["head_sha"] == head)
        op = build_opener(no_redirect())
        resp = open_log(op, no_redirect, m[1], check)
        if resp is None:
            continue
        with resp:
            lines = resp.read(4 * 1024 * 1024).decode("utf8", "replace").splitlines()
        scan_lines(lines, r["name"], dest, out, summaries)
    return {"owned": out, "other": summaries}
