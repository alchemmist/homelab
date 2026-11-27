"""Render single declared Host/Exact or Host/Prefix selectors for closed rehearsals.

This compiles matchers, not priorities, authorization or a publishable router.
Rule length must not decide precedence when replacing the Kubernetes provider.
"""

import re

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")


def path_rule(host: str, path: str, kind: str) -> str:
    """Keep Kubernetes element-wise Prefix semantics; refuse unsupported literals."""
    if not 0 < len(host) <= 253 or not all(_LABEL.fullmatch(s) for s in host.split(".")):
        raise ValueError("unsupported public DNS name")
    if not path.startswith("/") or "//" in path or kind not in {"Prefix", "Exact"}:
        raise ValueError("unsupported public path or path type")
    segments = path.strip("/").split("/") if path != "/" else []
    if any(not _SEGMENT.fullmatch(s) or s in {".", ".."} for s in segments):
        raise ValueError("unsupported public path segment")
    authority = f"Host(`{host}`)"
    if kind == "Exact":
        return f"{authority} && Path(`{path}`)"
    if path == "/":
        return f"{authority} && PathPrefix(`/`)"
    base = path.rstrip("/")
    return f"{authority} && (Path(`{base}`) || PathPrefix(`{base}/`))"
