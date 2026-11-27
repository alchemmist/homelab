"""Exercise only the built-in formatter through an existing loopback port-forward."""

import argparse
import http.client
import json

HOST = "fq.alchemmist.xyz"
LIMIT = 2048
PATH = "/api/format"


def _unique(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate response field")
    return obj


def matches(response, expected_status, expected):
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
        or len(length) > 5
        or int(length) > LIMIT
        or response.getheader("Transfer-Encoding") is not None
    ):
        return False
    raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT or (length is not None and len(raw) != int(length)):
        return False
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique) == expected
    except (ValueError, RecursionError):
        return False


def probe(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid loopback port")
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


def main():
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
