"""One namespace, one unfiltered Challenge LIST, one completed closed-fixture snapshot.

No transport or publisher. The reader owns the fixed API origin, namespace,
query, byte/time limits and confidentiality of bodies and continuation tokens.
A failed scan is not an empty solver file or an instruction to retain it forever.
"""

from http.client import HTTPException

from ci.quality.public_http01_generation import closed_solver_batch


class IncompleteScan(ValueError):
    """No publishable result; never include API response or cursor in diagnostics."""


def _pages(namespace, read_page):
    cursor = ""
    rv = None
    seen = set()
    objects = []
    uids = set()
    names = set()
    for _ in range(128):
        status, page = read_page(namespace, cursor)
        if (
            type(status) is not int
            or status != 200
            or not isinstance(page, dict)
            or (page.get("apiVersion"), page.get("kind"))
            != ("acme.cert-manager.io/v1", "ChallengeList")
        ):
            break
        meta = page["metadata"]
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
            or len(cursor) > 16384
            or (cursor and cursor in seen)
            or len(objects) + len(items) > 4096
        ):
            break
        rv = version
        for item in items:
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


def scan_namespace(namespace, approved_hosts, read_page, read_children, pod_network):
    """Build only after a terminal LIST page and complete child observations.

    `read_children(challenge)` returns (Ingress, Service, Pod, slices) or raises
    on interrupted/ambiguous reads. Explicitly observed absence can be represented
    with empty objects and an empty slice list. Never translate an API error to
    absence. Only the independent allowlist for this namespace is eligible.
    """
    try:
        if (
            not isinstance(namespace, str)
            or not namespace
            or not isinstance(approved_hosts, frozenset)
        ):
            raise IncompleteScan
        entries = []
        for item in _pages(namespace, read_page):
            spec = item["spec"]
            host = spec["dnsName"]
            typ = spec["type"]
            if typ != "HTTP-01" or host not in approved_hosts:
                continue
            m = item["metadata"]
            expected = (namespace, m["name"], m["uid"], host)
            ing, svc, pod, slices = read_children(item)
            entries.append((expected, item, ing, svc, pod, slices))
        return closed_solver_batch(entries, pod_network)
    except (KeyError, ValueError, TypeError, AttributeError, HTTPException, OSError, StopIteration):
        pass
    raise IncompleteScan("incomplete solver observations; no snapshot")
