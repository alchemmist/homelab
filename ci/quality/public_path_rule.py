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
    if not isinstance(path, str) or not path.startswith("/") or "//" in path or kind not in {"Prefix", "Exact"}:
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


def source_priority(
    host: str, path: str, kind: str, *, strict_prefix: bool, declared: int = 0
) -> int:
    """Reproduce v3.7.19 Ingress priority for this restricted ASCII matcher subset.

    The caller must establish the original strict-prefix setting. Used only to
    compare candidate routes, not to authorize any change in matching scope.
    Equal-priority intersecting owners still need an explicit decision.
    """
    rule = path_rule(host, path, kind)
    if type(strict_prefix) is not bool or type(declared) is not int:
        raise ValueError("unconfirmed original priority or prefix mode")
    if declared:
        return declared
    if kind == "Prefix" and not strict_prefix:
        rule = f'Host("{host}") && PathPrefix("{path}")'
    # In this validated ASCII subset double quotes in the Kubernetes provider
    # and backticks in the file provider have identical UTF-8 lengths.
    return len(rule.encode("ascii"))


def unchanged_path_matcher(
    host: str, path: str, kind: str, *, source_strict: bool, declared: int = 0
) -> tuple[str, int]:
    """Compile only a provably equivalent single matcher with original precedence.

    No witness sampling or priority override proves equality of path sets. A
    caller must block the host on failure, not drop the row and let a catch-all
    take it. This does not establish parity of a whole router or tied owners.
    """
    priority = source_priority(host, path, kind, strict_prefix=source_strict, declared=declared)
    if kind == "Prefix" and path != "/" and not source_strict:
        # With a trailing slash the segment matcher adds the slashless base;
        # without one the character matcher accepts same-segment extensions.
        raise ValueError("non-root character prefix requires explicit scope review")
    return path_rule(host, path, kind), priority


def unchanged_host_matchers(
    host: str, paths: list[tuple[str, str, int]], *, source_strict: bool
) -> tuple[tuple[str, int], ...]:
    """Return all matchers or none via exception, never a partial catch-all.

    Input is the caller's complete owner-approved path set for one host. No
    router is installed, and this does not address cross-host dependencies.
    """
    if not paths:
        raise ValueError("empty public host path inventory")
    return tuple(
        unchanged_path_matcher(host, path, kind, declared=priority, source_strict=source_strict)
        for path, kind, priority in paths
    )
