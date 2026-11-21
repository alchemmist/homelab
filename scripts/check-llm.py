import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import cast

BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "qwen3.8-27b")
TIMEOUT = 180


def require(condition, message):
    if not condition:
        raise ValueError(message)


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    return urllib.request.urlopen(
        urllib.request.Request(f"{BASE_URL}/{path}", data=data, headers=headers),
        timeout=TIMEOUT,
    )


def report(name, started, usage=None):
    tokens = ""
    if usage:
        tokens = (
            f"; tokens in={usage.get('prompt_tokens', '?')}"
            f" out={usage.get('completion_tokens', '?')}"
        )
    print(f"PASS {name}: {time.monotonic() - started:.2f}s{tokens}", flush=True)


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(value)
    mapped: dict[str, object] = {key: item for key, item in value.items() if isinstance(key, str)}
    return mapped


def _list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    raise TypeError(value)


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def _loads(value: object) -> object:
    if not isinstance(value, str):
        raise TypeError(value)
    return cast("object", json.loads(value))


def complete(messages: object, **options: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 256,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        **options,
    }
    with request("chat/completions", payload) as response:
        loaded = json.load(response)
    if not isinstance(loaded, dict):
        raise TypeError(loaded)
    result: dict[str, object] = {
        key: value for key, value in loaded.items() if isinstance(key, str)
    }
    choices = result.get("choices")
    require(isinstance(choices, list) and bool(choices), "Response has no choices")
    if not isinstance(choices, list) or not choices:
        raise TypeError(choices)
    first = choices[0]
    if not isinstance(first, dict):
        raise TypeError(first)
    require(first.get("finish_reason") != "length", "Response was truncated")
    return result


def main():
    require(bool(API_KEY), "LLM_API_KEY must be set")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(f"{BASE_URL}/models", timeout=TIMEOUT):
            raise ValueError("API accepted a request without its bearer key")
    except urllib.error.HTTPError as error:
        require(error.code == 401, f"Expected unauthenticated HTTP 401, received {error.code}")
    report("API authentication", started)

    started = time.monotonic()
    with request("models") as response:
        models = json.load(response)
    require(MODEL in {item["id"] for item in models.get("data", [])}, "Requested model is missing")
    report("model listing", started)

    started = time.monotonic()
    result = complete(
        [
            {
                "role": "user",
                "content": "Write a Python function add(a, b) that returns their sum. Return only the function.",
            }
        ]
    )
    content = _text(_dict(_dict(_list(result["choices"])[0])["message"]).get("content") or "")
    require(
        "def add(" in content and "return" in content and "+" in content,
        "Coding response lacks the requested function",
    )
    report("coding response", started, result.get("usage"))

    started = time.monotonic()
    done = False
    content = ""
    usage = None
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": 64,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    with request("chat/completions", payload) as response:
        require(
            "text/event-stream" in response.headers.get("Content-Type", ""), "Response is not SSE"
        )
        for line in response:
            require(time.monotonic() - started < TIMEOUT, "Streaming exceeded time limit")
            line = line.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done = True
                break
            event = json.loads(data)
            require("error" not in event, "Streaming response contains an error")
            usage = event.get("usage") or usage
            for choice in event.get("choices", []):
                require(choice.get("finish_reason") != "length", "Streaming response was truncated")
                content += choice.get("delta", {}).get("content") or ""
    require(done and bool(content.strip()), "Streaming lacked content or [DONE]")
    report("SSE streaming", started, usage)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": "Use get_weather for current weather. Pass the city name in English. Report its temperature exactly after receiving the result.",
        },
        {
            "role": "user",
            "content": "What is the current weather in Moscow? Use the available tool.",
        },
    ]
    started = time.monotonic()
    result = complete(messages, tools=tools, tool_choice="auto")
    choice = _dict(_list(result["choices"])[0])
    message = _dict(choice["message"])
    calls = _list(message.get("tool_calls") or [])
    require(
        choice.get("finish_reason") == "tool_calls" and len(calls) == 1,
        "Expected one automatic tool call",
    )
    call = _dict(calls[0])
    require(bool(call.get("id")) and call.get("type") == "function", "Invalid tool call envelope")
    require(_dict(call["function"])["name"] == "get_weather", "Unexpected tool name")
    arguments = _loads(_dict(call["function"])["arguments"])
    require(arguments == {"city": "Moscow"}, "Unexpected weather tool arguments")
    report("automatic tool call", started, result.get("usage"))

    messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
    messages.append(
        {
            "role": "tool",
            "tool_call_id": _text(call["id"]),
            "content": json.dumps(
                {
                    "city": "Moscow",
                    "temperature_c": 17,
                    "condition": "sunny",
                    "synthetic_test_data": True,
                }
            ),
        }
    )
    started = time.monotonic()
    result = complete(messages, tools=tools, tool_choice="none")
    message = _dict(_dict(_list(result["choices"])[0])["message"])
    require(
        not message.get("tool_calls") and "17" in _text(message.get("content") or ""),
        "Continuation did not use the supplied tool result",
    )
    report("tool result continuation", started, result.get("usage"))

    if os.environ.get("LLM_TEST_LONG_CONTEXT") == "1":
        started = time.monotonic()
        context = "\n".join(
            f"def function_{index}(value): return value + {index}"
            for index in range(int(os.environ.get("LLM_LONG_CONTEXT_LINES", "700")))
        )
        result = complete(
            [
                {
                    "role": "user",
                    "content": "CONTEXT_CHECK_VALUE = violet-river-7291\n"
                    + context
                    + "\nReturn only the value of CONTEXT_CHECK_VALUE from the beginning of this message.",
                }
            ],
            max_tokens=int(os.environ.get("LLM_LONG_CONTEXT_MAX_OUTPUT_TOKENS", "8192")),
        )
        usage = _dict(result.get("usage") or {})
        require(
            isinstance(tokens := usage.get("prompt_tokens", 0), int)
            and not isinstance(tokens, bool)
            and tokens > 8192,
            "Long-context check did not exceed the old 8K limit",
        )
        require(
            "violet-river-7291"
            in _text(_dict(_dict(_list(result["choices"])[0])["message"]).get("content") or ""),
            "Long-context response did not recover the value from the beginning",
        )
        report("long context", started, usage)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        print(f"FAIL HTTP {error.code}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
        detail = str(error).replace(API_KEY, "[REDACTED]") if API_KEY else str(error)
        print(f"FAIL {detail}", file=sys.stderr)
        sys.exit(1)
