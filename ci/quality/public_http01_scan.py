"""One namespace, one unfiltered Challenge LIST, one completed closed-fixture snapshot.

No transport or publisher. The reader owns the fixed API origin, namespace,
query, byte/time limits and confidentiality of bodies and continuation tokens.
A failed scan is not an empty solver file or an instruction to retain it forever.
"""

from collections.abc import Callable
from http.client import HTTPException
from ipaddress import IPv4Network

from ci.quality.public_http01_generation import Observation, closed_solver_batch

Page = tuple[int, dict[str, object]]
Children = tuple[dict[str, object], dict[str, object], dict[str, object], list[dict[str, object]]]
ReadPage = Callable[[str, str], Page]
ReadChildren = Callable[[dict[str, object]], Children]

MAX_PAGES = 128
MAX_CURSOR_BYTES = 16384
MAX_OBJECTS = 4096
HTTP_OK = 200


class IncompleteScan(ValueError):
    """No publishable result; never include API response or cursor in diagnostics."""


def _pages(namespace: str, read_page: ReadPage) -> list[dict[str, object]]:
    cursor = ""
    rv: object = None
    seen: set[str] = set()
    objects: list[dict[str, object]] = []
    uids: set[object] = set()
    names: set[object] = set()
    for _ in range(MAX_PAGES):
        status, page = read_page(namespace, cursor)
        if (
            isinstance(status, bool)
            or status != HTTP_OK
            or (page.get("apiVersion"), page.get("kind"))
            != ("acme.cert-manager.io/v1", "ChallengeList")
        ):
            break
        meta = page["metadata"]
        if not isinstance(meta, dict):
            raise IncompleteScan
        version = meta["resourceVersion"]
        items = page["items"]
        cursor = meta.get("continue", "")
        if (
            not isinstance(version, str)
            or not version
            or version == "0"
            or (rv is not None and rv != version)
            or not isinstance(items, list)
            or not isinstance(cursor, str)
            or len(cursor) > MAX_CURSOR_BYTES
            or (cursor and cursor in seen)
            or len(objects) + len(items) > MAX_OBJECTS
        ):
            break
        rv = version
        for item in items:
            if not isinstance(item, dict):
                raise IncompleteScan
            m = item["metadata"]
            uid = m["uid"]
            name = m["name"]
            if (
                item["kind"] != "Challenge"
                or item["apiVersion"] != page["apiVersion"]
                or m["namespace"] != namespace
                or not isinstance(uid, str)
                or not uid
                or not isinstance(name, str)
                or not name
                or uid in uids
                or name in names
            ):
                raise IncompleteScan
            uids.add(uid)
            names.add(name)
            objects.append(item)
        if not cursor:
            if meta.get("remainingItemCount", 0) != 0:
                break
            return objects
        seen.add(cursor)
    raise IncompleteScan


def scan_namespace(
    namespace: str,
    approved_hosts: frozenset[str],
    read_page: ReadPage,
    read_children: ReadChildren,
    pod_network: IPv4Network,
) -> dict[str, object]:
    """Build only after a terminal LIST page and complete child observations.

    `read_children(challenge)` returns (Ingress, Service, Pod, slices) or raises
    on interrupted/ambiguous reads. Explicitly observed absence can be represented
    with empty objects and an empty slice list. Never translate an API error to
    absence. Only the independent allowlist for this namespace is eligible.
    """
    try:
        if not namespace:
            raise IncompleteScan
        entries: list[Observation] = []
        for item in _pages(namespace, read_page):
            spec = item["spec"]
            if not isinstance(spec, dict):
                raise IncompleteScan
            host = spec["dnsName"]
            typ = spec["type"]
            if typ != "HTTP-01" or not isinstance(host, str) or host not in approved_hosts:
                continue
            m = item["metadata"]
            if not isinstance(m, dict):
                raise IncompleteScan
            name = m["name"]
            uid = m["uid"]
            if not isinstance(name, str) or not isinstance(uid, str):
                raise IncompleteScan
            expected = (namespace, name, uid, host)
            ing, svc, pod, slices = read_children(item)
            entries.append((expected, item, ing, svc, pod, slices))
        return closed_solver_batch(entries, pod_network)
    except (KeyError, ValueError, TypeError, AttributeError, HTTPException, OSError, StopIteration):
        pass
    msg = "incomplete solver observations; no snapshot"
    raise IncompleteScan(msg)
