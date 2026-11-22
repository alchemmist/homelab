"""One stage per n8n node. Rendering uses the generator committed next to the spec."""

import json
import os
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from engine import UnsafeInput, page_ok, select_closable, spec_changed
from github import BotRepo, Homelab


class PageBot(Protocol):
    """Bot repo reads used by a stage. Test doubles only need these methods."""

    def files(self, before: object, after: object) -> Iterable[object] | None:
        """Return compare or commit file entries."""
        ...

    def text(self, sha: object, path: str) -> str:
        """Return one allowed file at sha."""
        ...


class WikiRepo(Protocol):
    """Homelab writes used by a stage."""

    def propose(self, after: object, markdown: str) -> object:
        """Open or reuse the wiki refresh pull request."""
        ...

    def automation_prs(self, keep: object) -> Sequence[Mapping[str, object]]:
        """List older automation pull requests."""
        ...

    def close(self, number: int, survivor: object) -> None:
        """Close one pull request as superseded."""
        ...

    def api(self, method: str, path: str, body: object = ...) -> object:
        """Call the homelab GitHub API."""
        ...


def model(system: str, data: object) -> object:
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
        return json.loads(json.load(response)["choices"][0]["message"]["content"])


def render_page(after: object, bot: PageBot) -> str:
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
        return page_ok(target.read_text())


def stage(
    name: str,
    payload: Mapping[str, object],
    bot: PageBot | None = None,
    homelab: WikiRepo | None = None,
    call_model: Callable[[str, object], object] | None = None,
    *,
    write: bool = False,
) -> list[Mapping[str, object]]:
    bot = bot or BotRepo()
    if name == "check":
        event = payload.get("body", payload)
        if not isinstance(event, dict) or event.get("ref") != "refs/heads/main":
            return []
        if not spec_changed(event, bot.files(event.get("before", ""), event.get("after", ""))):
            return []
        return [{"before": event["before"], "after": event["after"]}]
    after = payload.get("after")
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
        if not isinstance(result, dict):
            raise UnsafeInput("GitHub proposal returned invalid data")
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
    for number in select_closable(decision, candidates, keep):
        if keep:
            homelab.close(number, keep)
        else:
            homelab.api("PATCH", f"pulls/{number}", {"state": "closed"})
        closed.append(number)
    return [{**payload, "closed": closed}]
