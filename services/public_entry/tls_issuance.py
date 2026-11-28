"""Validate public issuance observations against an independently supplied exact scope.

No API access, key material or writer approval. cert-manager issuer references
are compared as declared, not inferred from CertificateRequest or listener data.
"""

import base64
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization

from services.public_entry.tls_issued_refresh import IssuedLeaf
from services.public_entry.tls_material import valid_dns_name
from services.public_entry.tls_selection import Source

MAX_PEM_LENGTH = 131072
MSG_EXPECTED_ITERABLE = "expected an iterable observation"
MSG_EXPECTED_MAPPING = "expected a mapping observation"
MSG_EXPECTED_TEXT = "expected a text field"
MSG_INCOMPLETE = "incomplete-public-material"


class NoEvidenceError(ValueError):
    """No unique current issuance can be used as an expected wire leaf."""


@dataclass(frozen=True)
class AnchorScope:
    """The exact source, SAN set and declared issuer an anchor is checked against."""

    source: Source
    hosts: frozenset[str]
    issuer_ref: Mapping[str, str]


def require(*, ok: bool, reason: str) -> None:
    """Withhold the whole decision whenever one reviewed fact is missing."""
    if not ok:
        raise NoEvidenceError(reason)


def _items(value: object) -> Iterable[object]:
    """Runtime narrowing of a caller-supplied observation to an iterable."""
    if not isinstance(value, Iterable):
        raise TypeError(MSG_EXPECTED_ITERABLE)
    return value


def _mapping(value: object) -> Mapping[str, object]:
    """Runtime narrowing of a caller-supplied observation to a mapping."""
    if not isinstance(value, dict):
        raise TypeError(MSG_EXPECTED_MAPPING)
    return value


def _text(value: object) -> str:
    """Runtime narrowing of a caller-supplied field to a string."""
    if not isinstance(value, str):
        raise TypeError(MSG_EXPECTED_TEXT)
    return value


def san_set(obj: x509.CertificateSigningRequest | x509.Certificate) -> list[str]:
    """Every extension name must be a reviewed DNS name, nothing else."""
    names = list(obj.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
    require(
        ok=all(isinstance(n, x509.DNSName) for n in names),
        reason="non-dns-san",
    )
    return sorted(n.value for n in names)


def decode(value: object) -> bytes:
    """Only bounded, strictly base64 public material may be decoded."""
    if not isinstance(value, str):
        invalid_material = "invalid-public-material"
        raise NoEvidenceError(invalid_material)
    require(
        ok=0 < len(value) <= MAX_PEM_LENGTH,
        reason="invalid-public-material",
    )
    return base64.b64decode(value, validate=True)


def validated_anchor(
    scope: AnchorScope,
    certs: object,
    requests: object,
    now: datetime,
) -> IssuedLeaf:
    """Convert malformed API/certificate inputs into a local withholding decision."""
    try:
        return _anchor(scope, certs, requests, now)
    except NoEvidenceError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        OverflowError,
        x509.ExtensionNotFound,
        x509.DuplicateExtension,
        x509.UnsupportedGeneralNameType,
        UnsupportedAlgorithm,
    ):
        pass
    raise NoEvidenceError(MSG_INCOMPLETE)


def _anchor(scope: AnchorScope, certs: object, requests: object, now: datetime) -> IssuedLeaf:
    ref, sans, issuer_ref = scope.source, scope.hosts, scope.issuer_ref
    ns, pin = ref
    require(
        ok=(
            type(sans) is frozenset
            and bool(sans)
            and all(valid_dns_name(h) for h in sans)
            and set(issuer_ref) == {"group", "kind", "name"}
            and issuer_ref["group"] == "cert-manager.io"
            and issuer_ref["kind"] in {"Issuer", "ClusterIssuer"}
            and valid_dns_name(issuer_ref["name"])
        ),
        reason="invalid-issuance-scope",
    )
    matched = [
        c for c in _items(certs) if _mapping(_mapping(c).get("spec", {})).get("secretName") == pin
    ]
    require(ok=len(matched) == 1, reason="ambiguous-or-missing-certificate")
    cert = _mapping(matched[0])
    m = _mapping(cert["metadata"])
    spec = _mapping(cert["spec"])
    st = _mapping(cert["status"])
    gen = m["generation"]
    dns_names = list(_items(spec["dnsNames"]))
    require(
        ok=(
            cert["apiVersion"] == "cert-manager.io/v1"
            and cert["kind"] == "Certificate"
            and m["namespace"] == ns
            and m["name"] == pin
            and bool(m.get("uid"))
            and not m.get("deletionTimestamp")
            and spec.get("issuerRef") == issuer_ref
            and all(isinstance(n, str) for n in dns_names)
            and sorted(n for n in dns_names if isinstance(n, str)) == sorted(sans)
        ),
        reason="certificate-binding-changed",
    )
    ready = [_mapping(c) for c in _items(st["conditions"]) if _mapping(c)["type"] == "Ready"]
    require(
        ok=(
            type(gen) is int
            and len(ready) == 1
            and ready[0]["status"] == "True"
            and ready[0].get("observedGeneration") == gen
        ),
        reason="certificate-not-current",
    )
    rev = st.get("revision")
    require(ok=type(rev) is int and rev > 0, reason="missing-current-revision")
    rows = []
    for candidate in _items(requests):
        row = _mapping(candidate)
        head = _mapping(row["metadata"])
        ann = _mapping(head.get("annotations", {}))
        controllers = [
            _mapping(o)
            for o in _items(head.get("ownerReferences", []))
            if _mapping(o).get("controller") is True
        ]
        if ann.get("cert-manager.io/certificate-revision") != str(rev) or not any(
            o.get("uid") == m["uid"] for o in controllers
        ):
            continue
        require(
            ok=(
                len(controllers) == 1
                and all(
                    controllers[0].get(k) == v
                    for k, v in {
                        "name": pin,
                        "kind": "Certificate",
                        "apiVersion": "cert-manager.io/v1",
                    }.items()
                )
            ),
            reason="invalid-request-owner",
        )
        rows.append(row)
    require(ok=len(rows) == 1, reason="ambiguous-or-missing-current-request")
    req = rows[0]
    rm = _mapping(req["metadata"])
    require(
        ok=(
            req["kind"] == "CertificateRequest"
            and req["apiVersion"] == "cert-manager.io/v1"
            and rm["namespace"] == ns
            and not rm.get("deletionTimestamp")
            and _mapping(rm["annotations"]).get("cert-manager.io/certificate-name") == pin
            and _mapping(req["spec"]).get("issuerRef") == issuer_ref
        ),
        reason="request-binding-changed",
    )
    conditions = _mapping(req["status"])["conditions"]
    require(
        ok=(
            all(
                [_mapping(c)["status"] for c in _items(conditions) if _mapping(c)["type"] == t]
                == ["True"]
                for t in ("Approved", "Ready")
            )
            and not any(
                _mapping(c)["type"] in {"Denied", "InvalidRequest"} for c in _items(conditions)
            )
            and not _mapping(req["status"]).get("failureTime")
        ),
        reason="request-not-issued",
    )
    witnesses = (m["uid"], m["resourceVersion"], rm["uid"], rm["resourceVersion"])
    require(
        ok=all(isinstance(w, str) and w for w in witnesses),
        reason="missing-object-witness",
    )
    certificate_uid = _text(witnesses[0])
    certificate_version = _text(witnesses[1])
    request_uid = _text(witnesses[2])
    request_version = _text(witnesses[3])
    csr = x509.load_pem_x509_csr(decode(_mapping(req["spec"])["request"]))
    leaf = x509.load_pem_x509_certificates(decode(_mapping(req["status"])["certificate"]))[0]
    require(
        ok=(
            csr.is_signature_valid
            and csr.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            == leaf.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        ),
        reason="csr-key-mismatch",
    )
    require(
        ok=san_set(csr) == san_set(leaf) == sorted(sans),
        reason="issued-san-mismatch",
    )
    require(
        ok=(
            datetime.fromisoformat(_text(st["notBefore"]))
            == leaf.not_valid_before_utc
            <= now
            < leaf.not_valid_after_utc
            == datetime.fromisoformat(_text(st["notAfter"]))
        ),
        reason="issued-validity-mismatch",
    )
    return IssuedLeaf(
        ref,
        sans,
        certificate_uid,
        certificate_version,
        request_uid,
        request_version,
        leaf.fingerprint(hashes.SHA256()).hex(),
    )
