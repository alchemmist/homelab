"""Read-only blog chronology. Matching dates are NOT issued-leaf or writer evidence."""

import hashlib
import ipaddress
import json
import socket
import ssl
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import yaml
from cryptography import x509

from ci.quality import common
from ci.quality.public_issued_leaf import ISSUER, OWNERS
from ci.quality.public_web import CATALOG
from services.public_entry.tls_issuance import _items, _mapping, _text

NS, PIN, HOST, NAMES = OWNERS["www"]

KUBE = ["kubectl", "--context=Socrat", "--request-timeout=8s", "-n", NS]
KUBE_TIMEOUT = 15
MSG_BASELINE_CHANGED = "baseline changed"
MSG_CHANGED_DURING_SAMPLES = "changed during samples"

Witness = tuple[object, ...]
Snapshot = tuple[Witness, tuple[datetime, datetime, datetime, datetime]]
WireSample = tuple[bytes, datetime, datetime]


def get(resource: str) -> Mapping[str, object]:
    """Read one namespaced resource through the audited command dispatcher."""
    row: Mapping[str, object] = json.loads(
        common.command([*KUBE, "get", resource, "-o", "json"], timeout=KUBE_TIMEOUT).stdout
    )
    return row


def snapshot() -> Snapshot:
    """Capture the blog certificate/ingress chronology and its request count."""
    cert = get("certificate/" + PIN)
    ingress = get("ingress/blog")
    requests = get("certificaterequests.cert-manager.io")
    return chronology(cert, ingress, requests["items"])


def _witness_ok(witness: Witness) -> bool:
    """Every witness field must be a non-empty string."""
    return all(isinstance(v, str) and v for v in witness)


def _owner_ok(
    m: Mapping[str, object],
    im: Mapping[str, object],
    spec: Mapping[str, object],
    refs: list[Mapping[str, object]],
    ingress: Mapping[str, object],
) -> bool:
    """Require the certificate to be named and controlled by the blog ingress."""
    return (
        m["namespace"] == im["namespace"] == NS
        and m["name"] == spec["secretName"] == PIN
        and im["name"] == "blog"
        and not any(x.get("deletionTimestamp") for x in (m, im))
        and len(refs) == 1
        and refs[0]["uid"] == im["uid"]
        and refs[0]["apiVersion"] == ingress["apiVersion"] == "networking.k8s.io/v1"
        and refs[0]["kind"] == ingress["kind"] == "Ingress"
        and refs[0]["name"] == im["name"]
    )


def _spec_ok(
    cert: Mapping[str, object],
    spec: Mapping[str, object],
    tls: list[Mapping[str, object]],
) -> bool:
    """Require the spec bindings, SAN set and single TLS entry to be unchanged."""
    return (
        cert["kind"] == "Certificate"
        and cert["apiVersion"] == "cert-manager.io/v1"
        and spec["issuerRef"] == ISSUER
        and all(isinstance(n, str) for n in _items(spec["dnsNames"]))
        and sorted(n for n in _items(spec["dnsNames"]) if isinstance(n, str)) == sorted(NAMES)
        and len(tls) == 1
        and tls[0]["secretName"] == PIN
        and all(isinstance(h, str) for h in _items(tls[0]["hosts"]))
        and sorted(h for h in _items(tls[0]["hosts"]) if isinstance(h, str)) == sorted(NAMES)
    )


def _status_ok(
    s: Mapping[str, object],
    m: Mapping[str, object],
    ready: list[Mapping[str, object]],
    requests: object,
) -> bool:
    """Require a current Ready state with no revision or request present."""
    return (
        len(ready) == 1
        and ready[0]["status"] == "True"
        and ready[0]["observedGeneration"] == m["generation"]
        and "revision" not in s
        and not requests
    )


def chronology(c: object, i: object, requests: object) -> Snapshot:
    """Produce the identity witness and validity dates only for the pinned baseline."""
    cert = _mapping(c)
    ingress = _mapping(i)
    m = _mapping(cert["metadata"])
    im = _mapping(ingress["metadata"])
    s = _mapping(cert["status"])
    spec = _mapping(cert["spec"])
    refs = [
        _mapping(r) for r in _items(m["ownerReferences"]) if _mapping(r).get("controller") is True
    ]
    tls = [_mapping(t) for t in _items(_mapping(ingress["spec"])["tls"])]
    ready = [_mapping(x) for x in _items(s["conditions"]) if _mapping(x)["type"] == "Ready"]
    witness: Witness = (
        m["uid"],
        m["resourceVersion"],
        im["uid"],
        im["resourceVersion"],
    )
    if not (
        _witness_ok(witness)
        and _owner_ok(m, im, spec, refs, ingress)
        and _spec_ok(cert, spec, tls)
        and _status_ok(s, m, ready, requests)
    ):
        raise ValueError(MSG_BASELINE_CHANGED)
    dates: tuple[datetime, datetime, datetime, datetime] = (
        datetime.fromisoformat(_text(s["notBefore"])),
        datetime.fromisoformat(_text(m["creationTimestamp"])),
        datetime.fromisoformat(_text(s["renewalTime"])),
        datetime.fromisoformat(_text(m["notAfter"])),
    )
    return witness, dates


def public_leaf(ip: object) -> WireSample:
    """One TLS handshake against the blog front; never read Secret objects."""
    address = _text(ip)
    with (
        socket.create_connection((str(ipaddress.IPv4Address(address)), 443), timeout=4) as raw,
        ssl.create_default_context().wrap_socket(raw, server_hostname=HOST) as conn,
    ):
        der = conn.getpeercert(binary_form=True)
        if der is None:
            missing_leaf = "no peer certificate presented"
            raise OSError(missing_leaf)
        leaf = x509.load_der_x509_certificate(der)
        return hashlib.sha256(der).digest(), leaf.not_valid_before_utc, leaf.not_valid_after_utc


def measure(
    read: Callable[[], Snapshot],
    wire: Callable[[object], WireSample],
    ip: object,
    now: datetime,
) -> dict[str, bool | int]:
    """Correlate two stable samples; matching dates are still not issuance evidence."""
    before = read()
    first = wire(ip)
    after = read()
    second = wire(ip)
    if before != after or first != second:
        raise ValueError(MSG_CHANGED_DURING_SAMPLES)
    start, created, renew, end = before[1]
    return {
        "ownerIngressMatches": True,
        "currentRevisionAbsent": True,
        "namespaceRequestCount": 0,
        "trustedHomeLeafDatesMatchStatus": first[1:] == (start, end),
        "statusValidityStartsBeforeCertificateCreated": start < created,
        "renewalScheduledInFuture": now < renew < end,
        "issuedLeafMatchEstablished": False,
        "writerApproved": False,
    }


def main() -> int:
    """Report the blog chronology baseline; never claim issuance or writer approval."""
    try:
        result = measure(
            snapshot,
            public_leaf,
            _mapping(_mapping(_mapping(yaml.safe_load(CATALOG.read_text()))["replicas"])["home"])[
                "publicIP"
            ],
            datetime.now(UTC),
        )
    except (
        RuntimeError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ):
        print('{"baseline":"not-established"}')
        return 1
    print(json.dumps(result, sort_keys=True))
    verdict = result["trustedHomeLeafDatesMatchStatus"]
    return int(not verdict)


if __name__ == "__main__":
    raise SystemExit(main())
