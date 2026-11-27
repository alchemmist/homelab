"""One closed, in-memory TLS refresh. No Kubernetes transport, cache or publisher."""

import base64
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from services.public_entry.tls_selection import Source, SourceMaterial, select_sources

# The transport must apply its own byte and time limits before parsing JSON.
ExactGet = Callable[[Source], tuple[int, object]]


@dataclass(frozen=True, repr=False)
class Refresh:
    """The certs and router eligibility must be derived from this same completed batch."""

    material: Mapping[Source, SourceMaterial] = field(repr=False)
    hosts: Mapping[Source, frozenset[str]]
    fingerprints: Mapping[Source, str]
    withdrawn: Mapping[Source, str]


def _decode(ref: Source, doc: object) -> SourceMaterial | None:
    if (
        not isinstance(doc, dict)
        or doc.get("kind") != "Secret"
        or doc.get("apiVersion") != "v1"
        or doc.get("type") != "kubernetes.io/tls"
    ):
        return None
    meta = doc.get("metadata")
    data = doc.get("data")
    if (
        not isinstance(meta, dict)
        or (meta.get("namespace"), meta.get("name")) != ref
        or meta.get("deletionTimestamp") is not None
        or not isinstance(data, dict)
    ):
        return None
    fields = []
    for key, limit in [("tls.crt", 128 * 1024), ("tls.key", 32 * 1024)]:
        text = data.get(key)
        if not isinstance(text, str) or not text or len(text) > 4 * ((limit + 2) // 3):
            return None
        try:
            decoded = base64.b64decode(text, validate=True)
        except ValueError:
            return None
        if len(decoded) > limit:
            return None
        fields.append(decoded)
    return SourceMaterial(*fields)


def refresh(
    ownership: Mapping[Source, frozenset[str]], get: ExactGet, now: datetime
) -> Refresh:
    """Call only reviewed exact refs. A later per-source failure cannot undo a denial.

    Transient failures omit the affected source too (availability tradeoff).
    Programmer failures propagate; loop/transport termination is not a completed
    withdrawal snapshot. No consumer acknowledgement or freshness fence is implied.
    """
    pins = {ref: frozenset(hosts) for ref, hosts in ownership.items()}
    counts = Counter(host for hosts in pins.values() for host in hosts)
    received = {}
    withheld = {}
    for ref in sorted(pins):
        if not pins[ref] or any(counts[h] != 1 for h in pins[ref]):
            withheld[ref] = "invalid-ownership"
            continue
        try:
            status, doc = get(ref)
        except OSError:
            withheld[ref] = "unavailable"
            continue
        if type(status) is not int or not 100 <= status <= 599:
            withheld[ref] = "invalid-response"
            continue
        if status != 200:
            withheld[ref] = {403: "denied", 404: "missing"}.get(status, "unavailable")
            continue
        pair = _decode(ref, doc)
        if pair is None:
            withheld[ref] = "invalid-response"
            continue
        received[ref] = pair
    fingerprints = select_sources(pins, received, now)
    for ref in received.keys() - fingerprints.keys():
        withheld[ref] = "invalid-material-or-ownership"
    return Refresh(
        MappingProxyType({ref: received[ref] for ref in fingerprints}),
        MappingProxyType({ref: pins[ref] for ref in fingerprints}),
        MappingProxyType(fingerprints),
        MappingProxyType(withheld),
    )
