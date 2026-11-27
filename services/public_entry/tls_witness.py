"""Observe one closed listener, never a public fallback or a key-bearing API.

Each name is a distinct fresh TCP/TLS connection. A sweep is not atomic, an
application check, an enforcement mechanism or a freshness deadline.
"""

import hashlib
import re
import socket
import ssl
from collections.abc import Mapping

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def observe(
    port: int,
    reviewed: frozenset[str],
    admitted: Mapping[str, str],
    *,
    trust: ssl.SSLContext | None = None,
) -> dict[str, str]:
    """Require trusted pinned leaves on admitted hosts, strict rejection elsewhere.

    `reviewed` includes withdrawn aliases; it must come from independent
    ownership, never from just the published snapshot. An injected context is
    for explicit fixture trust. No application request or key data is sent.
    """
    pins = dict(admitted)
    if (
        type(port) is not int
        or not 1 <= port <= 65535
        or not reviewed
        or not pins.keys() <= reviewed
    ):
        raise ValueError("invalid listener witness scope")
    if any(
        not isinstance(h, str)
        or len(h) > 253
        or not all(_LABEL.fullmatch(s) for s in h.split("."))
        for h in reviewed
    ) or any(
        not isinstance(v, str) or not re.fullmatch("[0-9a-f]{64}", v)
        for v in pins.values()
    ):
        raise ValueError("invalid listener witness identity")
    ctx = trust if trust is not None else ssl.create_default_context()
    if not ctx.check_hostname or ctx.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("verified client context required")
    result = {}
    for host in sorted(reviewed):
        try:
            with (
                socket.create_connection(("127.0.0.1", port), timeout=3) as raw,
                ctx.wrap_socket(raw, server_hostname=host) as conn,
            ):
                fingerprint = hashlib.sha256(
                    conn.getpeercert(binary_form=True)
                ).hexdigest()
                result[host] = (
                    "unexpected-leaf"
                    if host not in pins
                    else "trusted-match"
                    if fingerprint == pins[host]
                    else "different-leaf"
                )
        except ssl.SSLCertVerificationError:
            result[host] = "untrusted-leaf"
        except ssl.SSLError as exc:
            if exc.reason == "TLSV1_UNRECOGNIZED_NAME":
                result[host] = (
                    "strict-rejection" if host not in pins else "missing-leaf"
                )
            else:
                result[host] = "tls-error"
        except TimeoutError:
            result[host] = "timeout"
        except OSError:
            result[host] = "unreachable"
    return result
