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
from services.public_entry.tls_selection import Source, SourceMaterial


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


@dataclass(frozen=True)
class _Batch:
    """The three reviewed callbacks/bounds one sweep runs with."""

    issuance: Callable[[Source], IssuedLeaf | None]
    get: ExactGet
    now: datetime


def _current(
    issuance: Callable[[Source], IssuedLeaf | None],
    ref: Source,
    hosts: frozenset[str],
    grant: ApprovedScope,
) -> IssuedLeaf | None:
    """Accept only an anchor bound to this source, grant and a sha256 shape."""
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
    if not all(
        v for v in (w.certificate_version, w.request_uid, w.request_version)
    ) or not re.fullmatch("[0-9a-f]{64}", w.sha256):
        return None
    return w


def _ownership_reason(counts: Counter[str], hosts: frozenset[str]) -> str | None:
    """Refuse unreviewed or ambiguous ownership of any host."""
    if not hosts or any(counts[h] != 1 or not valid_dns_name(h) for h in hosts):
        return "invalid-ownership"
    return None


def _grant_reason(grant: ApprovedScope | None, hosts: frozenset[str]) -> str | None:
    """Refuse a missing or alias-narrowed independent writer review."""
    if (
        not isinstance(grant, ApprovedScope)
        or type(grant.hosts) is not frozenset
        or grant.hosts != hosts
        or not grant.certificate_uid
    ):
        return "no-writer-approval"
    return None


def _accepted(
    batch: _Batch, ref: Source, hosts: frozenset[str], grant: ApprovedScope
) -> tuple[SourceMaterial, str] | str:
    """Sweep one approved source and return either refusal or matter and fingerprint."""
    first = _current(batch.issuance, ref, hosts, grant)
    if first is None:
        return "no-current-issuance"
    single = refresh({ref: hosts}, batch.get, batch.now)
    if ref in single.withdrawn:
        return single.withdrawn[ref]
    if single.fingerprints[ref] != first.sha256:
        return "issued-leaf-mismatch"
    if _current(batch.issuance, ref, hosts, grant) != first:
        return "issuance-changed"
    return single.material[ref], first.sha256


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
    counts: Counter[str] = Counter(h for hosts in pins.values() for h in hosts)
    material: dict[Source, SourceMaterial] = {}
    accepted: dict[Source, frozenset[str]] = {}
    fingerprints: dict[Source, str] = {}
    withdrawn: dict[Source, str] = {}
    batch = _Batch(issuance, get, now)
    for ref, hosts in sorted(pins.items()):
        grant = grants.get(ref)
        reason = _ownership_reason(counts, hosts)
        if reason is None:
            reason = _grant_reason(grant, hosts)
        if reason is None and grant is not None:
            outcome = _accepted(batch, ref, hosts, grant)
            if isinstance(outcome, str):
                reason = outcome
            else:
                material[ref] = outcome[0]
                accepted[ref] = hosts
                fingerprints[ref] = outcome[1]
        if reason is not None:
            withdrawn[ref] = reason
    return Refresh(
        MappingProxyType(material),
        MappingProxyType(accepted),
        MappingProxyType(fingerprints),
        MappingProxyType(withdrawn),
    )
