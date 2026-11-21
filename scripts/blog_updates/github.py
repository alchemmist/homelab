"""GitHub API boundary. No shell commands and no credentials in logs."""

import base64
import json
import re
import urllib.error
import urllib.request
from typing import cast

from engine import REPO, UPDATES, UnsafeInput


class GitHub:
    def __init__(self, token):
        self.token = token

    def api(self, method, path, body=None) -> dict[str, object]:
        # All destinations are fixed; model input never controls API paths.
        request = urllib.request.Request(
            "https://api.github.com/repos/" + REPO + "/" + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                document: dict[str, object] = json.load(response)
                return document
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub {method} failed (HTTP {exc.code})") from None

    def compare(self, before, after) -> dict[str, object]:
        for sha in (before, after):
            if not re.fullmatch("[a-f0-9]{40}", sha):
                raise UnsafeInput("Full SHA required")
        result = self.api("GET", f"compare/{before}...{after}?per_page=100&page=1")
        if result.get("status") not in ("ahead", "identical"):
            raise UnsafeInput("Non-forward push requires manual review")
        # Files are returned on page one only; reject ambiguous/truncated compares.
        files = cast("list[object]", result.get("files", []))
        if len(files) >= 300:
            raise UnsafeInput("Compare file limit exceeded")
        total = cast("int", result.get("total_commits", 0))
        if total > 1000:
            raise UnsafeInput("Commit range too large")
        commits = cast("list[dict[str, object]]", result.get("commits", []))
        page = 2
        while len(commits) < total:
            extra = cast(
                "list[dict[str, object]]",
                self.api("GET", f"compare/{before}...{after}?per_page=100&page={page}").get(
                    "commits", []
                ),
            )
            if not extra:
                raise UnsafeInput("Incomplete commit pagination")
            commits.extend(extra)
            page += 1
        result["commits"] = commits
        return result

    def read_updates(self, ref) -> tuple[str, str]:
        f = self.api("GET", f"contents/{UPDATES}?ref={ref}")
        if f.get("encoding") != "base64":
            raise UnsafeInput("Unexpected GitHub content encoding")
        content = cast("str", f["content"])
        sha = cast("str", f["sha"])
        return base64.b64decode(content).decode(), sha

    def propose(self, after, content, reason, draft=False) -> dict[str, object]:
        if not re.fullmatch("[a-f0-9]{40}", after):
            raise UnsafeInput("Full SHA required")
        branch = "automation/blog-updates-" + after + ("-test" if draft else "")
        # Include closed PRs: closing a proposal is an editorial decision, not a retry.
        existing = cast(
            "list[dict[str, object]]",
            self.api("GET", f"pulls?state=all&head=alchemmist:{branch}&per_page=100"),
        )
        if existing:
            return {"status": "existing", "url": existing[0]["html_url"]}
        # Pin proposal to the analyzed commit. A later main change cannot be silently overwritten.
        main_ref = cast("dict[str, object]", self.api("GET", "git/ref/heads/main")["object"])
        main_sha = cast("str", main_ref["sha"])
        if main_sha != after:
            raise UnsafeInput("main advanced; reanalysis required")
        original, _ = self.read_updates(after)
        if content == original:
            return {"status": "no_change"}
        # Ref creation is an atomic idempotency lock: a competing delivery fails closed.
        self.api("POST", "git/refs", {"ref": "refs/heads/" + branch, "sha": after})
        _, file_sha = self.read_updates(branch)
        self.api(
            "PUT",
            "contents/" + UPDATES,
            {
                "message": "docs: propose reader-facing blog updates",
                "branch": branch,
                "sha": file_sha,
                "content": base64.b64encode(content.encode()).decode(),
            },
        )
        pr = self.api(
            "POST",
            "pulls",
            {
                "title": "docs: add reader Updates entry",
                "head": branch,
                "base": "main",
                "draft": draft,
                "body": "Automatically proposed; human review required. No auto-merge.\n\n"
                f"Source commit: https://github.com/{REPO}/commit/{after}\n\n" + reason[:2000],
            },
        )
        return {"status": "created", "url": pr["html_url"]}
