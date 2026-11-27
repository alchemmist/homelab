import base64
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ci.quality import public_issued_leaf as audit


@pytest.fixture
def issued():
    ns, pin, host, sans = audit.OWNERS["wiki"]
    now = datetime.now(UTC).replace(microsecond=0)
    start = now - timedelta(hours=1)
    end = now + timedelta(hours=1)
    key = ec.generate_private_key(ec.SECP256R1())
    sub = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, host)])
    san = x509.SubjectAlternativeName([x509.DNSName(n) for n in sans])
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(sub)
        .add_extension(san, False)
        .sign(key, hashes.SHA256())
    )
    leaf = (
        x509.CertificateBuilder()
        .subject_name(sub)
        .issuer_name(sub)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(start)
        .not_valid_after(end)
        .add_extension(san, False)
        .sign(key, hashes.SHA256())
    )
    enc = lambda x: base64.b64encode(
        x.public_bytes(serialization.Encoding.PEM)
    ).decode()
    catalog = {"hosts": {ns: {host: {"dns": "managed", "tlsSourceName": pin}}}}
    meta = {
        "uid": "cert-uid",
        "name": pin,
        "namespace": ns,
        "generation": 1,
        "resourceVersion": "c1",
    }
    cert = {
        "apiVersion": "cert-manager.io/v1",
        "kind": "Certificate",
        "metadata": meta,
        "spec": {"dnsNames": [host], "secretName": pin, "issuerRef": audit.ISSUER},
        "status": {
            "revision": 1,
            "conditions": [
                {"type": "Ready", "status": "True", "observedGeneration": 1}
            ],
            "notBefore": start.isoformat(),
            "notAfter": end.isoformat(),
        },
    }
    req = {
        "apiVersion": "cert-manager.io/v1",
        "kind": "CertificateRequest",
        "metadata": {
            "name": "req",
            "namespace": ns,
            "uid": "req-uid",
            "resourceVersion": "r1",
            "annotations": {
                "cert-manager.io/certificate-revision": "1",
                "cert-manager.io/certificate-name": pin,
            },
            "ownerReferences": [
                {
                    "controller": True,
                    "kind": "Certificate",
                    "apiVersion": "cert-manager.io/v1",
                    "name": pin,
                    "uid": "cert-uid",
                }
            ],
        },
        "spec": {"issuerRef": audit.ISSUER, "request": enc(csr)},
        "status": {
            "conditions": [
                {"type": "Approved", "status": "True"},
                {"type": "Ready", "status": "True", "reason": "Issued"},
            ],
            "certificate": enc(leaf),
        },
    }
    return catalog, cert, req, now, leaf.fingerprint(hashes.SHA256()).hex()


def test_current_issued_leaf(issued):
    cat, c, r, t, pin = issued
    assert audit.evidence("wiki", cat, [c], [r], t) == (
        "cert-uid",
        "c1",
        "req-uid",
        "r1",
        pin,
    )


@pytest.mark.parametrize(
    "fault",
    [
        "catalog",
        "alias",
        "no-revision",
        "generation",
        "owner",
        "issuer",
        "denied",
        "duplicate",
        "deleting",
        "key",
        "dates",
        "expired",
        "wrong-revision",
        "empty-version",
    ],
)
def test_incomplete_or_mismatched_evidence(issued, fault):
    cat, c, r, t, _ = issued
    reqs = [r]
    if fault == "catalog":
        cat["hosts"]["wiki"].clear()
    elif fault == "alias":
        c["spec"]["dnsNames"].append("unreviewed.invalid")
    elif fault == "no-revision":
        c["status"].pop("revision")
    elif fault == "generation":
        c["metadata"]["generation"] += 1
    elif fault == "owner":
        r["metadata"]["ownerReferences"][0]["uid"] = "stale"
    elif fault == "issuer":
        r["spec"]["issuerRef"] = {}
    elif fault == "denied":
        r["status"]["conditions"].append({"type": "Denied", "status": "True"})
    elif fault == "duplicate":
        reqs.append(deepcopy(r))
    elif fault == "deleting":
        r["metadata"]["deletionTimestamp"] = "now"
    elif fault == "dates":
        c["status"]["notBefore"] = t.isoformat()
    elif fault == "expired":
        t += timedelta(days=1)
    elif fault == "wrong-revision":
        r["metadata"]["annotations"]["cert-manager.io/certificate-revision"] = "2"
    elif fault == "empty-version":
        r["metadata"]["resourceVersion"] = ""
    else:
        other = ec.generate_private_key(ec.SECP256R1())
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([]))
            .sign(other, hashes.SHA256())
        )
        r["spec"]["request"] = base64.b64encode(
            csr.public_bytes(serialization.Encoding.PEM)
        ).decode()
    with pytest.raises(audit.NoEvidence):
        audit.evidence("wiki", cat, [c], reqs, t)


@pytest.mark.parametrize("changed", [False, True])
def test_sweep_never_claims_writer_approval_or_a_rotated_match(
    monkeypatch, capsys, changed
):
    monkeypatch.setattr(sys, "argv", ["audit", "wiki"])
    anchor = ("u", "c1", "r", "r1", "a" * 64)
    obs = iter((anchor, ("u", "c2", "r", "r1", "a" * 64) if changed else anchor))
    monkeypatch.setattr(audit, "observe", lambda owner: next(obs))
    monkeypatch.setattr(audit, "wire", lambda h, ip: "a" * 64)
    assert audit.main() == int(changed)
    doc = json.loads(capsys.readouterr().out)
    assert doc["writerApproved"] is False
    if changed:
        assert "wire" not in doc
    else:
        assert set(doc["wire"].values()) == {"trusted-match"}


def test_validated_issuance_without_independent_approval_cannot_read_a_key(issued):
    from services.public_entry.tls_issued_refresh import issued_refresh

    cat, c, r, t, pin = issued
    anchor = audit.issuance_anchor("wiki", cat, [c], [r], t)
    assert anchor.sha256 == pin
    scope = {anchor.source: anchor.hosts}
    result = issued_refresh(
        scope, {}, lambda _: anchor, lambda _: pytest.fail("unapproved named GET"), t
    )
    assert not result.material and result.withdrawn == {
        anchor.source: "no-writer-approval"
    }


def test_private_issuer_must_be_pinned_independently_of_objects(issued):
    from services.public_entry.tls_issuance import validated_anchor

    _, c, r, t, fp = issued
    ns, pin, _, sans = audit.OWNERS["wiki"]
    ref = (ns, pin)
    names = frozenset(sans)
    local = {**audit.ISSUER, "kind": "Issuer", "name": "fixture-ca"}
    c["spec"]["issuerRef"] = local.copy()
    r["spec"]["issuerRef"] = local.copy()
    assert validated_anchor(ref, names, local, [c], [r], t).sha256 == fp
    for wrong in (
        audit.ISSUER,
        {**local, "group": "other.invalid"},
        {**local, "name": "other"},
        {**local, "kind": "ClusterIssuer"},
    ):
        with pytest.raises(audit.NoEvidence):
            validated_anchor(ref, names, wrong, [c], [r], t)
    del r["status"]["certificate"]
    with pytest.raises(audit.NoEvidence, match="^incomplete-public-material$") as exc:
        validated_anchor(ref, names, local, [c], [r], t)
    assert exc.value.__context__ is None
