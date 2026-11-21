"""GitHub reads for the public bot repo and writes for homelab. No credentials in errors."""

import base64
import json
import urllib.error
import urllib.request

from engine import MARKER, PAGE, branch_for, require_sha

BOT = "alchemmist/socrat-bot"
HOME = "alchemmist/homelab"


class GitHubError(Exception):
    pass


def _request(
    url: str, token: str | None = None, method: str = "GET", body: object = None
) -> dict[str, object] | list[dict[str, object]] | None:
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
        if exc.code == 404:
            return None
        raise GitHubError(f"GitHub {method} failed (HTTP {exc.code})") from None


class BotRepo:
    def files(self, before: str, after: str) -> list[dict[str, object]]:
        require_sha(after)
        if before == "0" * 40:
            commit = _request(f"https://api.github.com/repos/{BOT}/commits/{after}")
            if not isinstance(commit, dict):
                raise GitHubError("Commit not found")
            files_value = commit.get("files") or []
            if not isinstance(files_value, list):
                reason = "Commit file list missing"
                raise GitHubError(reason)
            return files_value
        require_sha(before)
        compared = _request(f"https://api.github.com/repos/{BOT}/compare/{before}...{after}")
        if not isinstance(compared, dict):
            raise GitHubError("Compare not found")
        files_value = compared.get("files") or []
        if not isinstance(files_value, list):
            reason = "Compare not found"
            raise GitHubError(reason)
        if len(files_value) >= 300:
            raise GitHubError("Compare file list truncated")
        return files_value

    def text(self, sha: str, path: str) -> str:
        require_sha(sha)
        if path not in ("openapi.yaml", "scripts/render_wiki.py"):
            raise GitHubError("Unexpected bot path")
        item = _request(f"https://api.github.com/repos/{BOT}/contents/{path}?ref={sha}")
        if not isinstance(item, dict) or item.get("encoding") != "base64":
            raise GitHubError("Bot file missing")
        return base64.b64decode(str(item["content"])).decode()


class Homelab:
    def __init__(self, token: str) -> None:
        self.token = token

    def api(
        self, method: str, path: str, body: object = None
    ) -> dict[str, object] | list[object] | None:
        value = _request(f"https://api.github.com/repos/{HOME}/{path}", self.token, method, body)
        if isinstance(value, list):
            listed: list[object] = []
            listed.extend(value)
            return listed
        return value

    def read_page(self, ref: str = "main") -> tuple[str | None, str | None]:
        item = self.api("GET", f"contents/{PAGE}?ref={ref}")
        if item is None:
            return None, None
        if not isinstance(item, dict):
            shape = "Unexpected page shape"
            raise GitHubError(shape)
        if item.get("encoding") != "base64":
            encoding = "Unexpected page encoding"
            raise GitHubError(encoding)
        return base64.b64decode(str(item["content"])).decode(), str(item["sha"])

    def propose(self, after: str, markdown: str) -> dict[str, object]:
        branch = branch_for(after)
        existing = self.api("GET", f"pulls?state=open&head=alchemmist:{branch}&per_page=20") or []
        if not isinstance(existing, list):
            shape = "Unexpected pull list shape"
            raise GitHubError(shape)
        if existing:
            first = existing[0]
            if not isinstance(first, dict):
                shape = "Unexpected pull shape"
                raise GitHubError(shape)
            return {
                "status": "existing",
                "number": first["number"],
                "url": first["html_url"],
            }
        current, _ = self.read_page("main")
        if current == markdown:
            return {"status": "no_change"}
        ref = self.api("GET", "git/ref/heads/main")
        if not isinstance(ref, dict):
            shape = "Unexpected ref shape"
            raise GitHubError(shape)
        head_object = ref["object"]
        if not isinstance(head_object, dict):
            shape = "Unexpected object shape"
            raise GitHubError(shape)
        main = head_object.get("sha")
        if not isinstance(main, str):
            shape = "Unexpected object shape"
            raise GitHubError(shape)
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
        pr = self.api(
            "POST",
            "pulls",
            {
                "title": "docs: refresh Socrat Bot wiki page",
                "head": branch,
                "base": "main",
                "body": "Regenerated `wiki/content/platform/socrat-bot.md` from the current socrat-bot OpenAPI spec.\n\n"
                f"Source commit: https://github.com/{BOT}/commit/{after}\n\n"
                "Human review required. No auto-merge.\n\n" + MARKER,
            },
        )
        if not isinstance(pr, dict):
            shape = "Unexpected pull shape"
            raise GitHubError(shape)
        return {"status": "created", "number": pr["number"], "url": pr["html_url"]}

    def automation_prs(self, keep: object) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        page = 1
        while page <= 5:
            batch = self.api("GET", f"pulls?state=open&per_page=50&page={page}") or []
            if not isinstance(batch, list):
                shape = "Unexpected pull list shape"
                raise GitHubError(shape)
            if not batch:
                break
            for pr in batch:
                if not isinstance(pr, dict):
                    shape = "Unexpected pull shape"
                    raise GitHubError(shape)
                if pr.get("number") == keep:
                    continue
                body = pr.get("body") or ""
                user = pr.get("user") or {}
                if (
                    isinstance(body, str)
                    and MARKER in body
                    and isinstance(user, dict)
                    and user.get("login") == "socrat-steward[bot]"
                ):
                    found.append(
                        {
                            "number": pr["number"],
                            "title": pr["title"],
                            "body": body[:800],
                            "url": pr["html_url"],
                        }
                    )
            if len(batch) < 50:
                break
            page += 1
        return found

    def close(self, number: int, survivor: object) -> None:
        self.api(
            "POST",
            f"issues/{number}/comments",
            {
                "body": f"Superseded by #{survivor}. The wiki page is regenerated from the current OpenAPI spec, so this proposal is stale."
            },
        )
        self.api("PATCH", f"pulls/{number}", {"state": "closed"})
