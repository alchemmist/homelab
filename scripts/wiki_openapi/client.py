"""GitHub reads for the public bot repo and writes for homelab. No credentials in errors."""

import base64
import json
import urllib.error
import urllib.request
from typing import TypedDict, cast

from .engine import MARKER, PAGE, branch_for, require_sha

BOT = "alchemmist/socrat-bot"
HOME = "alchemmist/homelab"
HTTP_NOT_FOUND = 404
MAX_COMPARE_FILES = 300
MAX_PR_PAGES = 5
PR_PAGE_SIZE = 50
PR_BODY_PREVIEW_CHARS = 800


class GitHubError(Exception):
    """Exception raised when the GitHub API request fails."""


class _Content(TypedDict):
    encoding: str
    content: str
    sha: str


class _PullRequest(TypedDict):
    number: int
    html_url: str
    title: str
    body: str | None
    user: dict[str, object]


class _Ref(TypedDict):
    object: dict[str, str]


class _Comparison(TypedDict, total=False):
    files: list[object]


def _request(
    url: str, token: str | None = None, method: str = "GET", body: object = None
) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "socrat-wiki-openapi",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == HTTP_NOT_FOUND:
            return None
        msg = f"GitHub {method} failed (HTTP {exc.code})"
        raise GitHubError(msg) from None


class BotRepo:
    """GitHub repository client for bot-managed files."""

    def files(self, before: object, after: object) -> list[object]:
        """Fingerprint the changed file set between two commits."""
        require_sha(after)
        if before == "0" * 40:
            commit = cast(
                "_Comparison | None",
                _request(f"https://api.github.com/repos/{BOT}/commits/{after}"),
            )
            if not commit:
                msg = "Commit not found"
                raise GitHubError(msg)
            return commit.get("files") or []
        require_sha(before)
        compared = cast(
            "_Comparison | None",
            _request(f"https://api.github.com/repos/{BOT}/compare/{before}...{after}"),
        )
        if not compared:
            msg = "Compare not found"
            raise GitHubError(msg)
        if len(compared.get("files") or []) >= MAX_COMPARE_FILES:
            msg = "Compare file list truncated"
            raise GitHubError(msg)
        return compared.get("files") or []

    def text(self, sha: object, path: str) -> str:
        """Fetch one of the two allowed files at a commit SHA."""
        require_sha(sha)
        if path not in ("openapi.yaml", "scripts/render_wiki.py"):
            msg = "Unexpected bot path"
            raise GitHubError(msg)
        item = cast(
            "_Content | None",
            _request(f"https://api.github.com/repos/{BOT}/contents/{path}?ref={sha}"),
        )
        if not item or item.get("encoding") != "base64":
            msg = "Bot file missing"
            raise GitHubError(msg)
        return base64.b64decode(item["content"]).decode()


class Homelab:
    """GitHub client for the homelab wiki repository."""

    def __init__(self, token: str) -> None:
        """Bind the client to one short-lived broker token."""
        self.token = token

    def api(self, method: str, path: str, body: object = None) -> object:
        """Call the GitHub API on the pinned repository."""
        return _request(
            f"https://api.github.com/repos/{HOME}/{path}", self.token, method, body
        )

    def read_page(self, ref: str = "main") -> tuple[str, str] | tuple[None, None]:
        """Read the generated wiki page content at the given ref."""
        item = cast("_Content | None", self.api("GET", f"contents/{PAGE}?ref={ref}"))
        if item is None:
            return None, None
        if item.get("encoding") != "base64":
            msg = "Unexpected page encoding"
            raise GitHubError(msg)
        return base64.b64decode(item["content"]).decode(), item["sha"]

    def propose(self, after: object, markdown: str) -> dict[str, object]:
        """Open (or reuse) a pull request with the regenerated page."""
        branch = branch_for(after)
        existing = cast(
            "list[_PullRequest]",
            self.api("GET", f"pulls?state=open&head=alchemmist:{branch}&per_page=20")
            or [],
        )
        if existing:
            return {
                "status": "existing",
                "number": existing[0]["number"],
                "url": existing[0]["html_url"],
            }
        current, _ = self.read_page("main")
        if current == markdown:
            return {"status": "no_change"}
        ref = cast("_Ref", self.api("GET", "git/ref/heads/main"))
        main = ref["object"]["sha"]
        self.api("POST", "git/refs", {"ref": "refs/heads/" + branch, "sha": main})
        _, blob = self.read_page(branch)
        body = {
            "message": "docs: refresh Socrat Bot wiki page from openapi.yaml",
            "branch": branch,
            "content": base64.b64encode(markdown.encode()).decode(),
        }
        if blob:
            body["sha"] = blob
        self.api("PUT", "contents/" + PAGE, body)
        pr = cast(
            "_PullRequest",
            self.api(
                "POST",
                "pulls",
                {
                    "title": "docs: refresh Socrat Bot wiki page",
                    "head": branch,
                    "base": "main",
                    "body": (
                        "Regenerated `wiki/content/platform/socrat-bot.md` from the "
                        "current socrat-bot OpenAPI spec.\n\n"
                        f"Source commit: https://github.com/{BOT}/commit/{after}\n\n"
                        "Human review required. No auto-merge.\n\n" + MARKER
                    ),
                },
            ),
        )
        return {"status": "created", "number": pr["number"], "url": pr["html_url"]}

    def automation_prs(self, keep: object) -> list[dict[str, object]]:
        """List automation PRs other than the one to keep."""
        found, page = [], 1
        while page <= MAX_PR_PAGES:
            batch = cast(
                "list[_PullRequest]",
                self.api("GET", f"pulls?state=open&per_page={PR_PAGE_SIZE}&page={page}")
                or [],
            )
            if not batch:
                break
            for pr in batch:
                if pr.get("number") == keep:
                    continue
                if (
                    MARKER in (pr.get("body") or "")
                    and pr.get("user", {}).get("login") == "socrat-steward[bot]"
                ):
                    found.append(
                        {
                            "number": pr["number"],
                            "title": pr["title"],
                            "body": (pr.get("body") or "")[:PR_BODY_PREVIEW_CHARS],
                            "url": pr["html_url"],
                        }
                    )
            if len(batch) < PR_PAGE_SIZE:
                break
            page += 1
        return found

    def close(self, number: int, survivor: object) -> None:
        """Comment on and close an superseded automation PR."""
        self.api(
            "POST",
            f"issues/{number}/comments",
            {
                "body": (
                    f"Superseded by #{survivor}. The wiki page is regenerated from the "
                    "current OpenAPI spec, so this proposal is stale."
                )
            },
        )
        self.api("PATCH", f"pulls/{number}", {"state": "closed"})
