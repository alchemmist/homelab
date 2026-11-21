"""Four-node workflow backend: each endpoint performs exactly one semantic stage."""

import json
import os
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import cast

from engine import UnsafeInput, prepare, render, validate_decision, validate_event
from github import GitHub


def context_for(event, github):
    if not validate_event(event):
        return None
    comparison = github.compare(event["before"], event["after"])
    updates, _ = github.read_updates(event["after"])
    context = prepare(comparison, updates)
    return (context, comparison, updates) if context else None


def model(system, data):
    req = urllib.request.Request(
        "http://litellm.llm.svc.cluster.local:4000/v1/chat/completions",
        data=json.dumps(
            {
                "model": "qwen3.8-27b",
                "temperature": 0.1,
                "max_tokens": 1000,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "blog_updates",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["should_update", "reason", "entries"],
                            "properties": {
                                "should_update": {"type": "boolean"},
                                "reason": {"type": "string"},
                                "entries": {
                                    "type": "array",
                                    "maxItems": 5,
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["text", "source_paths"],
                                        "properties": {
                                            "text": {"type": "string", "maxLength": 240},
                                            "source_paths": {
                                                "type": "array",
                                                "minItems": 1,
                                                "items": {"type": "string"},
                                            },
                                        },
                                    },
                                },
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
    with urllib.request.urlopen(req, timeout=360) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def checked_model(call_model, prompt, data, context):
    for attempt in range(2):
        try:
            return validate_decision(call_model(prompt, data), context)
        except (UnsafeInput, json.JSONDecodeError):
            if attempt:
                message = "Model response failed validation after two attempts"
                raise UnsafeInput(message) from None
            prompt += "\nPrevious response failed validation. Return only the exact JSON schema, plain text without URLs or Markdown, and supplied changed file paths."


def _validate_stage(call_model: object, event: object, context: object) -> list[dict[str, object]]:
    """Select only worthwhile announcements for the later stages."""
    prompt = Path(os.environ["PROMPT_FILE"]).read_text()
    prompt += "\nThis is the VALIDATION stage. Select only worthwhile announcements. Entry text is a concise factual outline for a separate writer, not a final publication. Return the specified JSON schema."
    runner = cast("Callable[[object, object], object]", call_model)
    decision = checked_model(runner, prompt, context, context)
    if not decision["should_update"]:
        return []
    return [{"event": event, "selection": decision}]


def _generate_stage(
    call_model: object,
    payload: dict[str, object],
    event: object,
    context: object,
) -> list[dict[str, object]]:
    """Write final announcement entries for the selected changes only."""
    selection = validate_decision(payload["selection"], context)
    if not selection["should_update"]:
        return []
    prompt = Path(os.environ["PROMPT_FILE"]).read_text()
    prompt += "\nThis is the GENERATION stage. Write final concise English announcement entries ONLY for the selected changes. Do not add other topics. Keep source_paths within the selected source_paths. Use the specified JSON schema; you may omit an unsupported selected item."
    runner = cast("Callable[[object, object], object]", call_model)
    decision = checked_model(runner, prompt, {"context": context, "selected": selection}, context)
    allowed = {p for e in selection["entries"] for p in e["source_paths"]}
    if any(p not in allowed for e in decision["entries"] for p in e["source_paths"]):
        message = "Generation introduced an unselected source"
        raise UnsafeInput(message)
    if not decision["should_update"]:
        return []
    return [{"event": event, "decision": decision}]


def stage(name, payload, github=None, call_model=None, write=False):
    github = github or GitHub(os.environ["GITHUB_TOKEN"])
    call_model = call_model or model
    event = payload if name == "validate" else payload["event"]
    snapshot = context_for(event, github)
    if snapshot is None:
        return []
    context, comparison, updates = snapshot
    if name == "validate":
        return _validate_stage(call_model, event, context)
    if name == "generate":
        return _generate_stage(call_model, payload, event, context)
    if name != "create-pr":
        message = "Unknown stage"
        raise UnsafeInput(message)
    decision = validate_decision(payload["decision"], context)
    if not decision["should_update"]:
        return []
    head = next((c for c in comparison["commits"] if c["sha"] == event["after"]), None)
    if not head:
        message = "Missing head commit"
        raise UnsafeInput(message)
    content = render(updates, decision["entries"], head["commit"]["committer"]["date"])
    if content == updates:
        return [{"status": "no_change"}]
    return _publish(github.propose, decision, event["after"], content, write=write)


def _publish(
    propose: object,
    decision: dict[str, object],
    event_after: object,
    content: str,
    *,
    write: bool,
) -> list[dict[str, object]]:
    """Report a dry run or propose the rendered announcement upstream."""
    if not write:
        return [{"status": "dry_run", "entries": decision["entries"], "reason": decision["reason"]}]
    runner = cast("Callable[[object, str, object], dict[str, object]]", propose)
    return [runner(event_after, content, decision["reason"])]
