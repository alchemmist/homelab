"""In-memory issuance-bound refresh. No API transport, grants, key files or publisher."""

import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
from types import MappingProxyType

from services.public_entry.tls_material import valid_dns_name
from services.public_entry.tls_refresh import ExactGet, Refresh, refresh
from services.public_entry.tls_selection import Source


@dataclass(frozen=True)
class ApprovedScope:
    """Caller-provided independent writer review for this source/owner and alias set."""

    certificate_uid: str
    hosts: frozenset[str]


@dataclass(frozen=True)
class IssuedLeaf:
    """From a separately validated issuance read, never from the Secret being tested."""

    source: Source
    hosts: frozenset[str]
    certificate_uid: str
    certificate_version: str
    request_uid: str
    request_version: str
    sha256: str


def issued_refresh(
    ownership: Mapping[Source, frozenset[str]],
    approvals: Mapping[Source, ApprovedScope],
    issuance: Callable[[Source], IssuedLeaf | None],
    get: ExactGet,
    now: datetime,
) -> Refresh:
    """Withhold all aliases together. Never substitute issuance evidence for approval.

    The callback must establish current Certificate/request provenance, signed CSR,
    SANs, dates and expected leaf (as in the read-only issued-leaf audit). Versions
    are opaque. Stability across these samples is not a freshness lease or atomicity.
    """
    pins = {ref: frozenset(hosts) for ref, hosts in ownership.items()}
    grants = dict(approvals)
    counts = Counter(h for hosts in pins.values() for h in hosts)
    material = {}
    accepted = {}
    fingerprints = {}
    withdrawn = {}

    def current(ref, hosts, grant):
        try:
            w = issuance(ref)
        except (OSError, HTTPException, ValueError):
            return None
        if (
            not isinstance(w, IssuedLeaf)
            or w.source != ref
            or type(w.hosts) is not frozenset
            or w.hosts != hosts
            or w.certificate_uid != grant.certificate_uid
        ):
            return None
        if (
            not all(
                isinstance(v, str) and v
                for v in (w.certificate_version, w.request_uid, w.request_version)
            )
            or not isinstance(w.sha256, str)
            or not re.fullmatch("[0-9a-f]{64}", w.sha256)
        ):
            return None
        return w

    for ref, hosts in sorted(pins.items()):
        grant = grants.get(ref)
        if not hosts or any(counts[h] != 1 or not valid_dns_name(h) for h in hosts):
            withdrawn[ref] = "invalid-ownership"
            continue
        if (
            not isinstance(grant, ApprovedScope)
            or type(grant.hosts) is not frozenset
            or grant.hosts != hosts
            or not isinstance(grant.certificate_uid, str)
            or not grant.certificate_uid
        ):
            withdrawn[ref] = "no-writer-approval"
            continue
        first = current(ref, hosts, grant)
        if first is None:
            withdrawn[ref] = "no-current-issuance"
            continue
        single = refresh({ref: hosts}, get, now)
        if ref in single.withdrawn:
            withdrawn[ref] = single.withdrawn[ref]
            continue
        if single.fingerprints[ref] != first.sha256:
            withdrawn[ref] = "issued-leaf-mismatch"
            continue
        if current(ref, hosts, grant) != first:
            withdrawn[ref] = "issuance-changed"
            continue
        material[ref] = single.material[ref]
        accepted[ref] = hosts
        fingerprints[ref] = first.sha256
    return Refresh(
        MappingProxyType(material),
        MappingProxyType(accepted),
        MappingProxyType(fingerprints),
        MappingProxyType(withdrawn),
    )
