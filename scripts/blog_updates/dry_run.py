#!/usr/bin/env python3
"""Read-only evaluation. GitHub data through gh; optional LiteLLM via key file."""

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path

from engine import REPO, UPDATES, Comparison, prepare, validate_decision

p = argparse.ArgumentParser()
p.add_argument("before")
p.add_argument("after")
p.add_argument("--litellm-url", help="OpenAI-compatible base URL, ending in /v1")
p.add_argument("--key-file", type=Path)
p.add_argument("--model", default="qwen3.8-27b")
a = p.parse_args()


def gh_compare(path: str) -> Comparison:
    comparison: Comparison = json.loads(subprocess.check_output(["gh", "api", path], text=True))
    return comparison


compare = gh_compare(f"repos/{REPO}/compare/{a.before}...{a.after}")
# Local git reads the committed snapshot, never uncommitted working-tree changes.
updates = subprocess.check_output(
    ["git", "-C", str(Path.home() / "code/blog"), "show", f"{a.after}:{UPDATES}"],
    text=True,
)
context = prepare(compare, updates)
if context is None:
    print(json.dumps({"skipped": True, "reason": "No relevant files"}))
elif not a.litellm_url:
    print(json.dumps(context, ensure_ascii=False, indent=2))
else:
    if not a.key_file:
        p.error("--key-file required with --litellm-url")
    prompt = (Path(__file__).resolve().parents[2] / "docs/n8n/blog-updates/prompt.md").read_text()
    body = {
        "model": a.model,
        "temperature": 0.1,
        "max_tokens": 1500,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        a.litellm_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + a.key_file.read_text().strip(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        result = json.load(response)
    decision = json.loads(result["choices"][0]["message"]["content"])
    print(json.dumps(validate_decision(decision, context), ensure_ascii=False, indent=2))
