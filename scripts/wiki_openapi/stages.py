"""One stage per n8n node. Rendering uses the generator committed next to the spec."""

import json
import os
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from engine import UnsafeInput, page_ok, select_closable, spec_changed
from github import BotRepo, Homelab


def model(system: str, data: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        "http://litellm.llm.svc.cluster.local:4000/v1/chat/completions",
        data=json.dumps(
            {
                "model": "qwen3.8-27b",
                "temperature": 0,
                "max_tokens": 400,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "close_prs",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["close"],
                            "properties": {
                                "close": {"type": "array", "items": {"type": "integer"}}
                            },
                        },
                    },
                },
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
            }
        ).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["LITELLM_KEY"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=360) as response:
        content = json.load(response)["choices"][0]["message"]["content"]
        value: dict[str, object] = json.loads(content)
        return value


class _BotRepo(Protocol):
    """Structural type of the bot repository API used by rendering."""

    def files(self, before: str, after: str) -> list[dict[str, object]]:
        """Return the changed bot files between two commits."""
        ...

    def text(self, sha: str, path: str) -> str:
        """Raw file text at a bot commit."""
        ...


class _Homelab(Protocol):
    """Structural type of the authenticated homelab GitHub API used here."""

    def api(self, method: str, path: str, body: object = ...) -> object:
        """Perform an authenticated homelab API call."""
        ...

    def propose(self, after: str, markdown: str) -> dict[str, object]:
        """Propose a wiki update pull request."""
        ...

    def automation_prs(self, keep: object) -> list[dict[str, object]]:
        """Open automation pull requests older than the survivor."""
        ...

    def close(self, number: int, survivor: object) -> None:
        """Close one automation pull request."""
        ...


def render_page(after: str, bot: _BotRepo) -> str:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "openapi.yaml").write_text(bot.text(after, "openapi.yaml"))
        scripts = root / "scripts"
        scripts.mkdir()
        script = scripts / "render_wiki.py"
        script.write_text(bot.text(after, "scripts/render_wiki.py"))
        target = root / "page.md"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        run = subprocess.run(
            ["python3", str(script), str(target)],
            cwd=directory,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if run.returncode:
            raise UnsafeInput("Wiki renderer failed")
        value: str = page_ok(target.read_text())
        return value


def stage(
    name: str,
    payload: dict[str, object],
    *,
    bot: _BotRepo | None = None,
    homelab: _Homelab | None = None,
    call_model: Callable[[str, dict[str, object]], dict[str, object]] | None = None,
    write: bool = False,
) -> list[dict[str, object]]:
    bot = bot or BotRepo()
    if name == "check":
        event = payload.get("body", payload)
        if not isinstance(event, dict) or event.get("ref") != "refs/heads/main":
            return []
        if not spec_changed(
            event, bot.files(str(event.get("before", "")), str(event.get("after", "")))
        ):
            return []
        return [{"before": event["before"], "after": event["after"]}]
    after = str(payload.get("after"))
    if name == "render":
        return [{"after": after, "markdown": render_page(after, bot)}]
    homelab = homelab or Homelab(
        Path(os.environ.get("GITHUB_TOKEN_FILE", "/var/run/github/token")).read_text().strip()
    )
    if name == "create-pr":
        markdown = page_ok(payload.get("markdown"))
        if not write:
            return [{"after": after, "status": "dry_run"}]
        result = homelab.propose(after, markdown)
        result["after"] = after
        return [result]
    if name != "close-older":
        raise UnsafeInput("Unknown stage")
    if not write or payload.get("status") == "dry_run":
        return []
    keep = payload.get("number")
    candidates = homelab.automation_prs(keep)
    if not candidates:
        return [payload]
    call_model = call_model or model
    prompt = (
        "You close stale GitHub pull requests. Every candidate was opened by socrat-steward "
        "to refresh the Socrat Bot wiki page from openapi.yaml. Close a candidate only when it is "
        "that same kind of refresh and is older or redundant relative to the survivor. "
        'Never invent numbers. Return JSON {"close": [numbers]}.'
    )
    decision = call_model(
        prompt, {"survivor": keep, "status": payload.get("status"), "candidates": candidates}
    )
    closed = []
    for number_raw in select_closable(decision, candidates, keep):
        number = int(number_raw)
        if keep:
            homelab.close(number, keep)
        else:
            homelab.api("PATCH", f"pulls/{number}", {"state": "closed"})
        closed.append(number)
    return [{**payload, "closed": closed}]
