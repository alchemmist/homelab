"""GitHub API boundary. No shell commands and no credentials in logs."""

import base64
import json
import re
import urllib.error
import urllib.request
from typing import TypedDict, cast

from .core import (
    COMPARE_PAGE_LIMIT,
    MAX_COMPARE_COMMITS,
    MAX_COMPARE_FILES,
    REPO,
    UPDATES,
    Comparison,
    UnsafeInputError,
)

# GitHub caps the PR body's model-authored reason block before insertion.
MAX_REASON_CHARS = 2_000


class _FileContent(TypedDict):
    encoding: str
    content: str
    sha: str


class _PullRequest(TypedDict):
    html_url: str


class _GitRef(TypedDict):
    object: dict[str, str]


class GitHub:
    """GitHub REST API client for blog updates."""

    def __init__(self, token: str) -> None:
        """Initialize the GitHub client."""
        self.token = token

    def api(self, method: str, path: str, body: object = None) -> object:
        """Call the fixed GitHub API destination with the configured token."""
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
                return json.load(response)
        except urllib.error.HTTPError as exc:
            msg = f"GitHub {method} failed (HTTP {exc.code})"
            raise RuntimeError(msg) from None

    def compare(self, before: str, after: str) -> Comparison:
        """Validate both commit SHAs before any comparison is attempted."""
        for sha in (before, after):
            if not re.fullmatch("[a-f0-9]{40}", sha):
                msg = "Full SHA required"
                raise UnsafeInputError(msg)
        result = cast(
            "Comparison",
            self.api(
                "GET",
                f"compare/{before}...{after}?per_page={COMPARE_PAGE_LIMIT}&page=1",
            ),
        )
        if result.get("status") not in ("ahead", "identical"):
            msg = "Non-forward push requires manual review"
            raise UnsafeInputError(msg)
        # Files are returned on page one only; reject ambiguous/truncated compares.
        # GitHub returns at most 300 files per compare response.
        if len(result.get("files", [])) >= MAX_COMPARE_FILES:
            msg = "Compare file limit exceeded"
            raise UnsafeInputError(msg)
        total = result.get("total_commits", 0)
        if total > MAX_COMPARE_COMMITS:
            msg = "Commit range too large"
            raise UnsafeInputError(msg)
        commits = result.get("commits", [])
        page = 2
        while len(commits) < total:
            extra_page = cast(
                "Comparison",
                self.api(
                    "GET",
                    f"compare/{before}...{after}?per_page={COMPARE_PAGE_LIMIT}&page={page}",
                ),
            )
            extra = extra_page.get("commits", [])
            if not extra:
                msg = "Incomplete commit pagination"
                raise UnsafeInputError(msg)
            commits.extend(extra)
            page += 1
        result["commits"] = commits
        return result

    def read_updates(self, ref: str) -> tuple[str, str]:
        """Read and decode the updates file at the given ref."""
        f = cast("_FileContent", self.api("GET", f"contents/{UPDATES}?ref={ref}"))
        if f.get("encoding") != "base64":
            msg = "Unexpected GitHub content encoding"
            raise UnsafeInputError(msg)
        return base64.b64decode(f["content"]).decode(), f["sha"]

    def propose(
        self, after: str, content: str, reason: str, *, as_draft: bool = False
    ) -> dict[str, str]:
        """Open a pull request carrying the reviewed update content."""
        if not re.fullmatch("[a-f0-9]{40}", after):
            msg = "Full SHA required"
            raise UnsafeInputError(msg)
        branch = "automation/blog-updates-" + after + ("-test" if as_draft else "")
        # Include closed PRs: closing a proposal is an editorial decision, not a retry.
        existing = cast(
            "list[_PullRequest]",
            self.api(
                "GET",
                f"pulls?state=all&head=alchemmist:{branch}&per_page={COMPARE_PAGE_LIMIT}",
            ),
        )
        if existing:
            return {"status": "existing", "url": existing[0]["html_url"]}
        # Pin proposal to the analyzed commit. A later main change cannot be silently overwritten.
        ref = cast("_GitRef", self.api("GET", "git/ref/heads/main"))
        main = ref["object"]["sha"]
        if main != after:
            msg = "main advanced; reanalysis required"
            raise UnsafeInputError(msg)
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
                "title": "docs: add blog Updates entry",
                "head": branch,
                "base": "main",
                "draft": as_draft,
                "body": "Automatically proposed; human review required. No auto-merge.\n\n"
                f"Source commit: https://github.com/{REPO}/commit/{after}\n\n"
                + reason[:MAX_REASON_CHARS],
            },
        )
        return {"status": "created", "url": cast("_PullRequest", pr)["html_url"]}
