import argparse
import base64
import io
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont


BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "qwen3.8-27b")
TIMEOUT = 300
CODE_WORDS = ("APPLE", "RIVER", "CLOUD", "HOUSE", "CHAIR", "TRAIN", "PLANT", "LEMON", "MANGO", "TIGER", "ZEBRA", "PANDA", "MUSIC", "ROBOT", "WATER", "STONE", "LIGHT", "BREAD", "BEACH", "GREEN")


def make_code():
    return secrets.choice(CODE_WORDS)


def make_image(code, large=False):
    if large:
        image = Image.frombytes("RGB", (1280, 1024), os.urandom(1280 * 1024 * 3))
    else:
        image = Image.new("RGB", (768, 256), "white")
    draw = ImageDraw.Draw(image)
    if large:
        draw.rectangle((320, 432, 960, 592), fill="white")
    font = ImageFont.load_default(size=96)
    draw.text((image.width // 2, image.height // 2), code, fill="black", font=font, anchor="mm")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


def complete(name, messages, expected, minimum_request_bytes=0):
    started = time.monotonic()
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 128,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    encoded_payload = json.dumps(payload).encode()
    if len(encoded_payload) <= minimum_request_bytes:
        raise ValueError(f"{name}: request must exceed {minimum_request_bytes} bytes, got {len(encoded_payload)}")
    print(f"REQUEST {name}: {len(encoded_payload)} bytes", flush=True)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=encoded_payload, headers=headers
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        result = json.load(response)
    choice = result["choices"][0]
    content = choice["message"].get("content") or ""
    normalized = "".join(content.upper().split())
    if choice.get("finish_reason") == "length" or not all(code in normalized for code in expected):
        raise ValueError(f"{name}: expected synthetic codes {expected}, received {content[:160]!r}")
    usage = result.get("usage") or {}
    print(
        f"PASS {name}: {time.monotonic() - started:.2f}s; "
        f"tokens in={usage.get('prompt_tokens', '?')} out={usage.get('completion_tokens', '?')}",
        flush=True,
    )
    return {"role": "assistant", "content": content}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--large", action="store_true", help="Also test nine images in a request exceeding 4 MiB")
    args = parser.parse_args()
    if not API_KEY:
        raise ValueError("LLM_API_KEY must be set")
    codes = [make_code() for _ in range(2)]
    while codes[0] == codes[1]:
        codes[1] = make_code()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Read the word printed in this image. Return only that word."},
        make_image(codes[0]),
    ]}]
    answer = complete("single image OCR", messages, codes[:1])
    messages.extend([
        answer,
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_synthetic_read_file", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"/synthetic/second.png"}'},
        }]},
        {"role": "tool", "tool_call_id": "call_synthetic_read_file",
         "content": "The image returned by read_file is attached in the next user message."},
        {"role": "user", "content": [
            {"type": "text", "text": "This is the read_file image result. Return the codes from both images in chronological order, separated by a space."},
            make_image(codes[1]),
        ]},
    ])
    complete("two-image tool result continuation", messages, codes)
    if args.large:
        large_messages = []
        history_codes = []
        while len(history_codes) < 9:
            code = make_code()
            if code not in history_codes:
                history_codes.append(code)
        for index, code in enumerate(history_codes):
            large_messages.append({"role": "user", "content": [
                {"type": "text", "text": "Read only the code in this latest image. Return only the code."},
                make_image(code, large=index == 0),
            ]})
            if index < len(history_codes) - 1:
                large_messages.append({"role": "assistant", "content": code})
        complete("nine-image history over 4 MiB", large_messages, history_codes[-1:], minimum_request_bytes=4 * 1024 * 1024)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        print(f"FAIL HTTP {error.code}", file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"FAIL {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
