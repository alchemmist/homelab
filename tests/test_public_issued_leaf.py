"""Ephemeral-only issued-leaf witnesses: no cluster access, no Secret reads."""

import base64
import json
import sys
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NotRequired, TypedDict

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ci.quality import public_issued_leaf as audit
from ci.quality.blog_validity_baseline import Snapshot, WireSample, measure
from services.public_entry.tls_issuance import (
    AnchorScope,
    NoEvidenceError,
    validated_anchor,
)
from services.public_entry.tls_issued_refresh import issued_refresh
from services.public_entry.tls_selection import Source


class CatalogEntry(TypedDict):
    """One pinned public hostname entry of the entrances catalog."""

    dns: str
    tlsSourceName: str


Catalog = dict[str, dict[str, dict[str, CatalogEntry]]]


class Condition(TypedDict, total=False):
    """One cert-manager style condition row."""

    type: str
    status: str
    reason: NotRequired[str]
    observedGeneration: NotRequired[int]


class CertificateSpec(TypedDict):
    """The reviewed public TLS source bound to a managed Secret."""

    dnsNames: list[str]
    secretName: str
    issuerRef: dict[str, str]


class CertificateMeta(TypedDict):
    """The certificate object identity witnessed together with its resourceVersion."""

    uid: str
    name: str
    namespace: str
    generation: int
    resourceVersion: str


class CertificateStatus(TypedDict, total=False):
    """The current Ready state and validity window of the certificate."""

    revision: int
    conditions: list[Condition]
    notBefore: str
    notAfter: str


class Certificate(TypedDict):
    """One cert-manager Certificate observation."""

    apiVersion: str
    kind: str
    metadata: CertificateMeta
    spec: CertificateSpec
    status: CertificateStatus


class OwnerReference(TypedDict):
    """The controlling owner of a CertificateRequest."""

    controller: bool
    kind: str
    apiVersion: str
    name: str
    uid: str


class RequestMeta(TypedDict, total=False):
    """The request identity plus annotations, owner and lifecycle witness."""

    name: str
    namespace: str
    uid: str
    resourceVersion: str
    annotations: dict[str, str]
    ownerReferences: list[OwnerReference]
    deletionTimestamp: str


class RequestSpec(TypedDict):
    """The declared issuer reference and the submitted CSR."""

    issuerRef: dict[str, str]
    request: str


class RequestStatus(TypedDict, total=False):
    """The Approved/Ready conditions and the issued certificate PEM."""

    conditions: list[Condition]
    certificate: str


class CertificateRequest(TypedDict):
    """One cert-manager CertificateRequest observation."""

    apiVersion: str
    kind: str
    metadata: RequestMeta
    spec: RequestSpec
    status: RequestStatus


@dataclass
class Issue:
    """The full possession-free fixture: catalog, certificate, request and witness."""

    catalog: Catalog
    cert: Certificate
    request: CertificateRequest
    now: datetime
    fingerprint: str


Fault = Callable[[Issue], tuple[list[Certificate], list[CertificateRequest]]]


def _pem(item: x509.Certificate | x509.CertificateSigningRequest) -> str:
    """Encode one ephemeral public object as the base64 PEM the API carries."""
    return base64.b64encode(item.public_bytes(serialization.Encoding.PEM)).decode()


@pytest.fixture
def issued() -> Issue:
    """Build the wiki fixture self-signed out of fresh ephemeral keys."""
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
        .add_extension(san, critical=False)
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
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    catalog: Catalog = {"hosts": {ns: {host: {"dns": "managed", "tlsSourceName": pin}}}}
    meta: CertificateMeta = {
        "uid": "cert-uid",
        "name": pin,
        "namespace": ns,
        "generation": 1,
        "resourceVersion": "c1",
    }
    cert: Certificate = {
        "apiVersion": "cert-manager.io/v1",
        "kind": "Certificate",
        "metadata": meta,
        "spec": {"dnsNames": [host], "secretName": pin, "issuerRef": audit.ISSUER},
        "status": {
            "revision": 1,
            "conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1}],
            "notBefore": start.isoformat(),
            "notAfter": end.isoformat(),
        },
    }
    req: CertificateRequest = {
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
        "spec": {"issuerRef": audit.ISSUER, "request": _pem(csr)},
        "status": {
            "conditions": [
                {"type": "Approved", "status": "True"},
                {"type": "Ready", "status": "True", "reason": "Issued"},
            ],
            "certificate": _pem(leaf),
        },
    }
    return Issue(catalog, cert, req, now, leaf.fingerprint(hashes.SHA256()).hex())


def test_current_issued_leaf(issued: Issue) -> None:
    cat, c, r, t, pin = issued.catalog, issued.cert, issued.request, issued.now, issued.fingerprint
    assert audit.evidence("wiki", cat, [c], [r], t) == (
        "cert-uid",
        "c1",
        "req-uid",
        "r1",
        pin,
    )


def _one(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    """Hand the audit the default, unfaulted object pair lists."""
    return [issue.cert], [issue.request]


def _fault_catalog(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.catalog["hosts"]["wiki"].clear()
    return _one(issue)


def _fault_alias(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.cert["spec"]["dnsNames"].append("unreviewed.invalid")
    return _one(issue)


def _fault_no_revision(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.cert["status"].pop("revision")
    return _one(issue)


def _fault_generation(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.cert["metadata"]["generation"] += 1
    return _one(issue)


def _fault_owner(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.request["metadata"]["ownerReferences"][0]["uid"] = "stale"
    return _one(issue)


def _fault_issuer(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.request["spec"]["issuerRef"] = {}
    return _one(issue)


def _fault_denied(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.request["status"]["conditions"].append({"type": "Denied", "status": "True"})
    return _one(issue)


def _fault_duplicate(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    return [issue.cert], [issue.request, deepcopy(issue.request)]


def _fault_deleting(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.request["metadata"]["deletionTimestamp"] = "now"
    return _one(issue)


def _fault_dates(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.cert["status"]["notBefore"] = issue.now.isoformat()
    return _one(issue)


def _fault_expired(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.now += timedelta(days=1)
    return _one(issue)


def _fault_wrong_revision(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.request["metadata"]["annotations"]["cert-manager.io/certificate-revision"] = "2"
    return _one(issue)


def _fault_empty_version(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    issue.request["metadata"]["resourceVersion"] = ""
    return _one(issue)


def _fault_key(issue: Issue) -> tuple[list[Certificate], list[CertificateRequest]]:
    other = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([]))
        .sign(other, hashes.SHA256())
    )
    issue.request["spec"]["request"] = _pem(csr)
    return _one(issue)


@pytest.mark.parametrize(
    "apply_fault",
    [
        pytest.param(_fault_catalog, id="catalog"),
        pytest.param(_fault_alias, id="alias"),
        pytest.param(_fault_no_revision, id="no-revision"),
        pytest.param(_fault_generation, id="generation"),
        pytest.param(_fault_owner, id="owner"),
        pytest.param(_fault_issuer, id="issuer"),
        pytest.param(_fault_denied, id="denied"),
        pytest.param(_fault_duplicate, id="duplicate"),
        pytest.param(_fault_deleting, id="deleting"),
        pytest.param(_fault_dates, id="dates"),
        pytest.param(_fault_expired, id="expired"),
        pytest.param(_fault_wrong_revision, id="wrong-revision"),
        pytest.param(_fault_empty_version, id="empty-version"),
        pytest.param(_fault_key, id="key"),
    ],
)
def test_incomplete_or_mismatched_evidence(issued: Issue, apply_fault: Fault) -> None:
    """Any one changed reviewed fact withholds the whole issuance decision."""
    certs, reqs = apply_fault(issued)
    with pytest.raises(NoEvidenceError):
        audit.evidence("wiki", issued.catalog, certs, reqs, issued.now)


@pytest.mark.parametrize("changed", [False, True])
def test_sweep_never_claims_writer_approval_or_a_rotated_match(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    changed: bool,
) -> None:
    monkeypatch.setattr(sys, "argv", ["audit", "wiki"])
    anchor = ("u", "c1", "r", "r1", "a" * 64)
    obs = iter((anchor, ("u", "c2", "r", "r1", "a" * 64) if changed else anchor))
    monkeypatch.setattr(audit, "observe", lambda _owner: next(obs))
    monkeypatch.setattr(audit, "wire", lambda _host, _ip: "a" * 64)
    assert audit.main() == int(changed)
    doc = json.loads(capsys.readouterr().out)
    assert doc["writerApproved"] is False
    if changed:
        assert "wire" not in doc
    else:
        assert set(doc["wire"].values()) == {"trusted-match"}


def test_validated_issuance_without_independent_approval_cannot_read_a_key(
    issued: Issue,
) -> None:
    anchor = audit.issuance_anchor(
        "wiki", issued.catalog, [issued.cert], [issued.request], issued.now
    )
    assert anchor.sha256 == issued.fingerprint
    scope: Mapping[Source, frozenset[str]] = {anchor.source: anchor.hosts}

    def get(_ref: Source) -> tuple[int, object]:
        pytest.fail("unapproved named GET")

    result = issued_refresh(scope, {}, lambda _: anchor, get, issued.now)
    assert not result.material
    assert result.withdrawn == {anchor.source: "no-writer-approval"}


def test_private_issuer_must_be_pinned_independently_of_objects(issued: Issue) -> None:
    ns, pin, _, sans = audit.OWNERS["wiki"]
    ref: Source = (ns, pin)
    names = frozenset(sans)
    local: dict[str, str] = {**audit.ISSUER, "kind": "Issuer", "name": "fixture-ca"}
    issued.cert["spec"]["issuerRef"] = local.copy()
    issued.request["spec"]["issuerRef"] = local.copy()
    correct = AnchorScope(ref, names, local)
    assert validated_anchor(correct, [issued.cert], [issued.request], issued.now).sha256 == (
        issued.fingerprint
    )
    for wrong in (
        audit.ISSUER,
        {**local, "group": "other.invalid"},
        {**local, "name": "other"},
        {**local, "kind": "ClusterIssuer"},
    ):
        with pytest.raises(NoEvidenceError):
            validated_anchor(
                AnchorScope(ref, names, wrong), [issued.cert], [issued.request], issued.now
            )
    del issued.request["status"]["certificate"]
    with pytest.raises(NoEvidenceError, match=r"^incomplete-public-material$") as exc:
        validated_anchor(correct, [issued.cert], [issued.request], issued.now)
    assert exc.value.__context__ is None


def _supply[T](items: Iterable[T]) -> tuple[Callable[[], T], Callable[[object], T]]:
    """Hand out one pre-provisioned sample per call, bound outside any loop."""
    iterator = iter(items)

    def read() -> T:
        return next(iterator)

    def wire(_: object) -> T:
        return next(iterator)

    return read, wire


def test_blog_date_correlation_is_not_issuance_or_approval() -> None:
    t = datetime.now(UTC)
    start, created, renew, end = (t + timedelta(days=n) for n in (-2, -1, 1, 2))
    dates: tuple[datetime, datetime, datetime, datetime] = (start, created, renew, end)
    snapshot: Snapshot = (("certificate", "rv", "owner", "v"), dates)
    leaf: WireSample = (b"one", start, end)
    result = measure(lambda: snapshot, lambda _: leaf, "unused", t)
    assert result["trustedHomeLeafDatesMatchStatus"]
    assert result["statusValidityStartsBeforeCertificateCreated"]
    assert not result["issuedLeafMatchEstablished"]
    assert not result["writerApproved"]
    wrong_leaf: WireSample = (b"two", t, end)
    mismatch = measure(lambda: snapshot, lambda _: wrong_leaf, "unused", t)
    assert not mismatch["trustedHomeLeafDatesMatchStatus"]
    replacement: Snapshot = (("replacement",), dates)
    stale_leaf: WireSample = (b"two", start, end)
    for observations, leaves in (
        ([snapshot, replacement], [leaf, leaf]),
        ([snapshot, snapshot], [leaf, stale_leaf]),
    ):
        with pytest.raises(ValueError, match="changed during samples"):
            measure(_supply(observations)[0], _supply(leaves)[1], "unused", t)
