"""Validate public issuance observations against an independently supplied exact scope.

No API access, key material or writer approval. cert-manager issuer references
are compared as declared, not inferred from CertificateRequest or listener data.
"""

import base64
from datetime import datetime

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization

from services.public_entry.tls_issued_refresh import IssuedLeaf
from services.public_entry.tls_material import valid_dns_name


class NoEvidence(ValueError):
    """No unique current issuance can be used as an expected wire leaf."""


def require(ok, reason):
    if not ok:
        raise NoEvidence(reason)


def san_set(obj):
    names = list(
        obj.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    )
    require(all(isinstance(n, x509.DNSName) for n in names), "non-dns-san")
    return sorted(n.value for n in names)


def decode(value):
    require(
        isinstance(value, str) and 0 < len(value) <= 131072, "invalid-public-material"
    )
    return base64.b64decode(value, validate=True)


def validated_anchor(ref, hosts, issuer_ref, certs, requests, now):
    """Convert malformed API/certificate inputs into a local withholding decision."""
    try:
        return _anchor(ref, hosts, issuer_ref, certs, requests, now)
    except NoEvidence:
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
    raise NoEvidence("incomplete-public-material")


def _anchor(ref, sans, issuer_ref, certs, requests, now):
    ns, pin = ref
    require(
        type(sans) is frozenset
        and sans
        and all(valid_dns_name(h) for h in sans)
        and set(issuer_ref) == {"group", "kind", "name"}
        and issuer_ref["group"] == "cert-manager.io"
        and issuer_ref["kind"] in {"Issuer", "ClusterIssuer"}
        and valid_dns_name(issuer_ref["name"]),
        "invalid-issuance-scope",
    )
    matched = [c for c in certs if c.get("spec", {}).get("secretName") == pin]
    require(len(matched) == 1, "ambiguous-or-missing-certificate")
    cert = matched[0]
    m = cert["metadata"]
    spec = cert["spec"]
    st = cert["status"]
    gen = m["generation"]
    require(
        cert["apiVersion"] == "cert-manager.io/v1"
        and cert["kind"] == "Certificate"
        and m["namespace"] == ns
        and m["name"] == pin
        and m.get("uid")
        and not m.get("deletionTimestamp")
        and spec.get("issuerRef") == issuer_ref
        and sorted(spec["dnsNames"]) == sorted(sans),
        "certificate-binding-changed",
    )
    ready = [c for c in st["conditions"] if c["type"] == "Ready"]
    require(
        type(gen) is int
        and len(ready) == 1
        and ready[0]["status"] == "True"
        and ready[0].get("observedGeneration") == gen,
        "certificate-not-current",
    )
    rev = st.get("revision")
    require(type(rev) is int and rev > 0, "missing-current-revision")
    rows = []
    for r in requests:
        rm = r["metadata"]
        ann = rm.get("annotations", {})
        controllers = [
            o for o in rm.get("ownerReferences", []) if o.get("controller") is True
        ]
        if ann.get("cert-manager.io/certificate-revision") != str(rev) or not any(
            o.get("uid") == m["uid"] for o in controllers
        ):
            continue
        require(
            len(controllers) == 1
            and all(
                controllers[0].get(k) == v
                for k, v in {
                    "name": pin,
                    "kind": "Certificate",
                    "apiVersion": "cert-manager.io/v1",
                }.items()
            ),
            "invalid-request-owner",
        )
        rows.append(r)
    require(len(rows) == 1, "ambiguous-or-missing-current-request")
    req = rows[0]
    rm = req["metadata"]
    require(
        req["kind"] == "CertificateRequest"
        and req["apiVersion"] == "cert-manager.io/v1"
        and rm["namespace"] == ns
        and not rm.get("deletionTimestamp")
        and rm["annotations"].get("cert-manager.io/certificate-name") == pin
        and req["spec"].get("issuerRef") == issuer_ref,
        "request-binding-changed",
    )
    conditions = req["status"]["conditions"]
    require(
        all(
            [c["status"] for c in conditions if c["type"] == t] == ["True"]
            for t in ("Approved", "Ready")
        )
        and not any(c["type"] in {"Denied", "InvalidRequest"} for c in conditions)
        and not req["status"].get("failureTime"),
        "request-not-issued",
    )
    require(
        all(
            isinstance(value, str) and value
            for value in (
                m["uid"],
                m["resourceVersion"],
                rm["uid"],
                rm["resourceVersion"],
            )
        ),
        "missing-object-witness",
    )
    csr = x509.load_pem_x509_csr(decode(req["spec"]["request"]))
    leaf = x509.load_pem_x509_certificates(decode(req["status"]["certificate"]))[0]
    require(
        csr.is_signature_valid
        and csr.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        == leaf.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        "csr-key-mismatch",
    )
    require(san_set(csr) == san_set(leaf) == sorted(sans), "issued-san-mismatch")
    require(
        datetime.fromisoformat(st["notBefore"])
        == leaf.not_valid_before_utc
        <= now
        < leaf.not_valid_after_utc
        == datetime.fromisoformat(st["notAfter"]),
        "issued-validity-mismatch",
    )
    return IssuedLeaf(
        ref,
        sans,
        m["uid"],
        m["resourceVersion"],
        rm["uid"],
        rm["resourceVersion"],
        leaf.fingerprint(hashes.SHA256()).hex(),
    )
