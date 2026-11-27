"""Exercise only the built-in formatter through an existing loopback port-forward."""

import argparse
import http.client
import json

HOST = "fq.alchemmist.xyz"
LIMIT = 2048
PATH = "/api/format"
MAX_PORT = 65535
MAX_LENGTH_DIGITS = 5


def _unique(pairs: list[tuple[str, object]]) -> object:
    """Reject a response body that repeats a JSON key."""
    obj = dict(pairs)
    if len(obj) != len(pairs):
        reason = "duplicate response field"
        raise ValueError(reason)
    return obj


def matches(
    response: http.client.HTTPResponse, expected_status: int, expected: dict[str, object]
) -> bool:
    """Require the exact bounded JSON result; redirects, echoes and partial bodies fail."""
    if (
        response.status != expected_status
        or response.getheader("Content-Type", "").partition(";")[0].strip().lower()
        != "application/json"
    ):
        return False
    length = response.getheader("Content-Length")
    if length is not None and (
        not length.isascii()
        or not length.isdecimal()
        or len(length) > MAX_LENGTH_DIGITS
        or int(length) > LIMIT
        or response.getheader("Transfer-Encoding") is not None
    ):
        return False
    raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT or (length is not None and len(raw) != int(length)):
        return False
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        return bool(decoded == expected)
    except (ValueError, RecursionError):
        return False


def probe(port: int) -> bool:
    """Format two fixed snippets over the loopback forward and verify results."""
    if type(port) is not int or not 1 <= port <= MAX_PORT:
        reason = "invalid loopback port"
        raise ValueError(reason)
    # Per-request config avoids looking up or initializing stored configuration.
    for code, expected in [
        ("int   value=1;", "int value = 1;"),
        ("int   other=2;", "int other = 2;"),
    ]:
        request = {
            "code": code + "\n",
            "formatter": "clang-format",
            "config": "BasedOnStyle: LLVM\n",
        }
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=6)
        try:
            conn.request(
                "POST",
                PATH,
                body=json.dumps(request).encode("ascii"),
                headers={
                    "Host": HOST,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            with conn.getresponse() as result:
                if not matches(result, 200, {"formatted": expected + "\n"}):
                    return False
        finally:
            conn.close()
    return True


def main() -> int:
    """Run the formatter probe from the CLI and report one exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-port", type=int, required=True)
    args = parser.parse_args()
    try:
        ok = probe(args.local_port)
    except (ValueError, OSError, http.client.HTTPException):
        ok = False
    print("two distinct formatted results" if ok else "formatter action not confirmed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
