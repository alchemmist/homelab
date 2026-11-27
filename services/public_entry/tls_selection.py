"""Select independently valid TLS sources for one completed private refresh."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from services.public_entry.tls_material import MaterialRejected, leaf_identity

Source = tuple[str, str]  # Namespace and Secret name; not a flattened identifier.


@dataclass(frozen=True, repr=False)
class SourceMaterial:
    """Key-bearing values: no generated repr; never serialize for diagnostics."""

    chain: bytes = field(repr=False)
    key: bytes = field(repr=False)


def select_sources(
    ownership: Mapping[Source, frozenset[str]],
    material: Mapping[Source, SourceMaterial],
    now: datetime,
) -> dict[Source, str]:
    """Return source/fingerprint pairs only; missing and ambiguous sources are absent.

    Input must describe a completed scan. This function neither fetches keys nor
    decides when an interrupted refresh is publishable. A host claimed by two
    sources cannot be repaired by picking the source that happened to validate.
    """
    counts = Counter(host for hosts in ownership.values() for host in hosts)
    accepted = {}
    for ref, names in ownership.items():
        pair = material.get(ref)
        if pair is None or any(counts[host] != 1 for host in names):
            continue
        try:
            accepted[ref] = leaf_identity(pair.chain, pair.key, names, now)
        except MaterialRejected:
            continue
    return accepted
