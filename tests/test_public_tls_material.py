"""Only ephemeral TLS material; never use cluster access in these tests."""

from base64 import b64encode
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple, Never

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from services.public_entry.tls_issued_refresh import (
    ApprovedScope,
    IssuedLeaf,
    issued_refresh,
)
from services.public_entry.tls_material import MaterialRejectedError, leaf_identity
from services.public_entry.tls_refresh import Refresh

NOW = datetime.now(UTC)
NAMES = frozenset({"one.invalid", "two.invalid"})
PrivateFixtureKey = ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey
Ref = tuple[str, str]
Reply = tuple[int, dict[str, object] | None]


class Extras(NamedTuple):
    """Optional certificate extensions for the pair() fixture."""

    purpose: x509.ObjectIdentifier = ExtendedKeyUsageOID.SERVER_AUTH
    extra_sans: tuple[x509.GeneralName, ...] = ()


class Material(NamedTuple):
    """Explicit private key plus optional public key substitution for pair()."""

    key: PrivateFixtureKey
    subject_public: ec.EllipticCurvePublicKey | rsa.RSAPublicKey | None = None


DEFAULT_EXTRAS = Extras()
ACCEPT_ROUNDS = 7


def pair(
    names: frozenset[str] | list[str] | set[str] = NAMES,
    *,
    ca: bool = False,
    signer: PrivateFixtureKey | None = None,
    extras: Extras = DEFAULT_EXTRAS,
    material: Material | None = None,
) -> tuple[PrivateFixtureKey, x509.Certificate]:
    sk = material.key if material else ec.generate_private_key(ec.SECP256R1())
    dn = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fixture")])
    b = (
        x509.CertificateBuilder()
        .subject_name(dn)
        .issuer_name(dn)
        .public_key(material.subject_public or sk.public_key() if material else sk.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(minutes=5))
        .not_valid_after(NOW + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([*(x509.DNSName(n) for n in names), *extras.extra_sans]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca, None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([extras.purpose]), critical=False)
    )
    cert = b.sign(signer or sk, hashes.SHA256())
    return sk, cert


def pem(c: x509.Certificate) -> bytes:
    return c.public_bytes(serialization.Encoding.PEM)


def private(k: PrivateFixtureKey) -> bytes:
    return k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def test_exact_leaf_and_linked_chain() -> None:
    issuer, ca = pair(ca=True)
    key, leaf = pair(signer=issuer)
    assert (
        leaf_identity(pem(leaf) + pem(ca), private(key), NAMES, NOW)
        == leaf.fingerprint(hashes.SHA256()).hex()
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "wildcard",
        "wrong-key",
        "trailing",
        "second-key",
        "expired",
        "not-yet",
        "ca",
        "purpose",
        "unrelated-chain",
        "not-ca-issuer",
        "duplicate-san",
        "invalid-name",
        "naive",
    ],
)
def test_bad_source_is_rejected_without_parser_or_material_in_diagnostics(fault: str) -> None:
    key, c = pair(
        {"one.invalid"}
        if fault == "missing"
        else NAMES | {"extra.invalid"}
        if fault == "extra"
        else ["*.invalid", "two.invalid"]
        if fault == "wildcard"
        else ["one.invalid", "two.invalid", "two.invalid"]
        if fault == "duplicate-san"
        else NAMES,
        ca=fault == "ca",
        extras=Extras(
            ExtendedKeyUsageOID.CLIENT_AUTH
            if fault == "purpose"
            else ExtendedKeyUsageOID.SERVER_AUTH
        ),
    )
    chain = pem(c)
    secret = private(key)
    now = NOW
    names = NAMES
    if fault == "wrong-key":
        secret = private(pair()[0])
    elif fault == "trailing":
        chain += b"bad trailing content"
    elif fault == "second-key":
        secret += secret
    elif fault == "expired":
        now += timedelta(hours=2)
    elif fault == "not-yet":
        now -= timedelta(hours=2)
    elif fault == "unrelated-chain":
        chain += pem(pair(ca=True)[1])
    elif fault == "not-ca-issuer":
        chain += pem(c)
    elif fault == "invalid-name":
        names = frozenset({"*.invalid"})
    elif fault == "naive":
        now = now.replace(tzinfo=None)
    with pytest.raises(MaterialRejectedError, match=r"^TLS source rejected$") as exc:
        leaf_identity(chain, secret, names, now)
    assert exc.value.__context__ is None


def test_matching_dns_entries_do_not_authorize_a_uri_identity() -> None:
    extra = Extras(extra_sans=(x509.UniformResourceIdentifier("urn:fixture:other"),))
    key, leaf = pair(extras=extra)
    with pytest.raises(MaterialRejectedError):
        leaf_identity(pem(leaf), private(key), NAMES, NOW)


def test_completed_refresh_admits_only_independent_owned_sources() -> None:
    from services.public_entry.tls_selection import SourceMaterial, select_sources

    left, right, stranger = ("one", "tls"), ("two", "tls"), ("unreviewed", "tls")
    a, b = frozenset({"one.invalid", "alias.invalid"}), frozenset({"two.invalid"})
    ak, ac = pair(a)
    bk, bc = pair(b)
    first = SourceMaterial(pem(ac), private(ak))
    second = SourceMaterial(pem(bc), private(bk))
    wanted = {
        left: ac.fingerprint(hashes.SHA256()).hex(),
        right: bc.fingerprint(hashes.SHA256()).hex(),
    }
    owners = {left: a, right: b}
    both = {left: first, right: second, stranger: first}
    assert select_sources(owners, both, NOW) == wanted
    for mats in (
        {right: second},
        {**both, left: SourceMaterial(first.chain, second.key)},
        {**both, left: second},
    ):
        assert select_sources(owners, mats, NOW) == {right: wanted[right]}
    assert select_sources({**owners, stranger: frozenset({"alias.invalid"})}, both, NOW) == {
        right: wanted[right]
    }
    assert select_sources(owners, both, NOW) == wanted
    assert "PRIVATE KEY" not in repr(first)


def test_rsa_public_key_identity_uses_the_complete_key() -> None:
    sk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _, leaf = pair(material=Material(key=sk))
    assert (
        leaf_identity(pem(leaf), private(sk), NAMES, NOW) == leaf.fingerprint(hashes.SHA256()).hex()
    )
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(MaterialRejectedError):
        leaf_identity(pem(leaf), private(other), NAMES, NOW)


def test_rsa_same_modulus_with_different_exponent_is_not_the_leaf_key() -> None:
    sk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = sk.public_key().public_numbers().n
    other_public = rsa.RSAPublicNumbers(3, n).public_key()
    issuer, ca = pair(ca=True)
    _, leaf = pair(signer=issuer, material=Material(key=sk, subject_public=other_public))
    with pytest.raises(MaterialRejectedError):
        leaf_identity(pem(leaf) + pem(ca), private(sk), NAMES, NOW)


def test_exact_refresh_does_not_lose_a_denial_on_later_failure_or_refetch_keys() -> None:
    import base64

    from services.public_entry.tls_refresh import Refresh, refresh

    refs: list[Ref] = [("owner", "a"), ("owner", "b"), ("owner", "c")]
    pins = {ref: frozenset({ref[1] + ".invalid"}) for ref in refs}
    replies: dict[Ref, Reply] = {}
    calls: list[Ref] = []
    for ref, names in pins.items():
        k, c = pair(names)
        replies[ref] = (
            200,
            {
                "kind": "Secret",
                "apiVersion": "v1",
                "type": "kubernetes.io/tls",
                "metadata": {"namespace": ref[0], "name": ref[1]},
                "data": {
                    "tls.crt": base64.b64encode(pem(c)).decode(),
                    "tls.key": base64.b64encode(private(k)).decode(),
                },
            },
        )

    def read(ref: Ref) -> Reply:
        calls.append(ref)
        return replies[ref]

    def scan() -> Refresh:
        calls.clear()
        r = refresh(pins, read, NOW)
        assert calls == refs
        return r

    initial = scan()
    assert set(initial.material) == set(refs)
    assert not initial.withdrawn
    original = dict(replies)
    # bool is an int subclass: it defeats an isinstance-only guard, exercising
    # the exact type() check in refresh. It must classify as invalid-response.
    replies[refs[1]] = (True, None)
    assert scan().withdrawn == {refs[1]: "invalid-response"}
    replies[refs[0]] = (403, {"message": "sensitive-fixture"})
    replies[refs[1]] = (503, None)
    partial = scan()
    assert partial.withdrawn == {refs[0]: "denied", refs[1]: "unavailable"}
    assert set(partial.material) == {refs[2]}
    assert partial.fingerprints[refs[2]] == initial.fingerprints[refs[2]]
    replies[refs[1]] = original[refs[0]]
    assert scan().withdrawn[refs[1]] == "invalid-response"
    replies.clear()
    replies.update(original)
    assert scan().fingerprints == initial.fingerprints
    stale = replies[refs[0]][1]
    assert isinstance(stale, dict)
    metadata = stale["metadata"]
    assert isinstance(metadata, dict)
    metadata["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    assert scan().withdrawn == {refs[0]: "invalid-response"}
    assert "PRIVATE KEY" not in repr(initial)
    assert "sensitive-fixture" not in str(partial.withdrawn)


def test_ambiguous_ownership_is_not_fetched_even_when_one_key_would_validate() -> None:
    from services.public_entry.tls_refresh import refresh

    owners = {
        ("a", "tls"): frozenset({"same.invalid"}),
        ("b", "tls"): frozenset({"same.invalid"}),
        ("c", "tls"): frozenset(),
    }

    def forbidden(_ref: Ref) -> Never:
        msg = "unexpected key read"
        raise AssertionError(msg)

    report = refresh(owners, forbidden, NOW)
    assert not report.material
    assert not report.hosts
    assert set(report.withdrawn.values()) == {"invalid-ownership"}


def test_truncated_http_response_after_denial_does_not_cancel_completed_batch() -> None:
    from http.client import IncompleteRead
    from json import JSONDecodeError

    from services.public_entry.tls_refresh import refresh

    a, b, c = [("owner", n) for n in "abc"]

    def read(ref: Ref) -> tuple[int, object]:
        if ref == a:
            return 403, None
        if ref == b:
            chunk = b"private fixture bytes"
            raise IncompleteRead(chunk)
        msg = "bad reply"
        raise JSONDecodeError(msg, "private fixture bytes", 0)

    result = refresh({ref: frozenset({ref[1] + ".invalid"}) for ref in (a, b, c)}, read, NOW)
    assert dict(result.withdrawn) == {
        a: "denied",
        b: "unavailable",
        c: "invalid-response",
    }
    assert not result.hosts
    assert not result.material


def test_loopback_listener_witness_distinguishes_withdrawal_from_trust_and_connection_failure(
    tmp_path: Path,
) -> None:
    import socket
    import ssl
    import threading

    from services.public_entry.tls_witness import observe

    key, cert = pair()
    kp = tmp_path / "key"
    cp = tmp_path / "cert"
    kp.write_bytes(private(key))
    cp.write_bytes(pem(cert))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cp, kp)
    client = ssl.create_default_context(cafile=str(cp))
    fp = cert.fingerprint(hashes.SHA256()).hex()
    gone = "gone.invalid"
    left, right = sorted(NAMES)
    seen: list[str] = []

    def sni(_sock: ssl.SSLObject, host: str, _context: ssl.SSLContext) -> int | None:
        seen.append(host)
        if host == gone:
            return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
        return None

    server.sni_callback = sni
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)
        port = listener.getsockname()[1]

        def accept() -> None:
            for _ in range(ACCEPT_ROUNDS):
                raw, _ = listener.accept()
                with raw:
                    try:
                        with server.wrap_socket(raw, server_side=True):
                            pass
                    except ssl.SSLError:
                        pass

        worker = threading.Thread(target=accept, daemon=True)
        worker.start()
        scope = NAMES | {gone}
        assert observe(port, scope, {left: fp}, trust=client) == {
            left: "trusted-match",
            right: "unexpected-leaf",
            gone: "strict-rejection",
        }
        assert observe(port, scope, {left: "0" * 64, right: fp, gone: fp}, trust=client) == {
            left: "different-leaf",
            right: "trusted-match",
            gone: "missing-leaf",
        }
        assert observe(port, frozenset({left}), {}) == {left: "untrusted-leaf"}
        worker.join(4)
        assert not worker.is_alive()
        assert len(seen) == ACCEPT_ROUNDS
    assert observe(port, NAMES, {}) == dict.fromkeys(NAMES, "unreachable")


def test_witness_rejects_out_of_scope_pin_before_probing() -> None:
    from services.public_entry.tls_witness import observe

    with pytest.raises(ValueError, match="scope"):
        observe(443, NAMES, {"other.invalid": "0" * 64})


@pytest.mark.parametrize("host", ["a..b", "a.invalid.", ".invalid"])
def test_witness_rejects_empty_hostname_labels(host: str) -> None:
    from services.public_entry.tls_witness import observe

    with pytest.raises(ValueError, match="identity"):
        observe(443, frozenset({host}), {})


def test_witness_timeout_does_not_acknowledge_withdrawal(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.public_entry import tls_witness

    def stall(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError

    import socket

    monkeypatch.setattr(socket, "create_connection", stall)
    assert tls_witness.observe(443, NAMES, {}) == dict.fromkeys(NAMES, "timeout")


ANOTHER_SOURCE = ("one", "tls")
NEIGHBOR_SOURCE = ("two", "tls")


@dataclass
class IssuanceCase:
    """Mutable issued-leaf fixture state; every test rebuilds it from scratch."""

    pins: dict[Ref, frozenset[str]]
    grants: dict[Ref, ApprovedScope]
    anchors: dict[Ref, IssuedLeaf | None]
    docs: dict[Ref, tuple[int, dict[str, object] | None]]
    reads: list[Ref]
    observations: list[Ref]


def _issue(case: IssuanceCase, ref: Ref) -> tuple[IssuedLeaf, tuple[int, dict[str, object]]]:
    """Build one reviewed anchor/Secret pair for a pinned source."""
    key, cert = pair(case.pins[ref])
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
    anchor = IssuedLeaf(
        ref,
        case.pins[ref],
        "cert-" + ref[0],
        "rv-A",
        "req-" + ref[0],
        "rv-B",
        fingerprint,
    )
    doc: dict[str, object] = {
        "kind": "Secret",
        "apiVersion": "v1",
        "type": "kubernetes.io/tls",
        "metadata": {"namespace": ref[0], "name": ref[1]},
        "data": {
            "tls.crt": b64encode(pem(cert)).decode(),
            "tls.key": b64encode(private(key)).decode(),
        },
    }
    return anchor, (200, doc)


def _new_case() -> IssuanceCase:
    """Build the two pinned sources with current anchors and readable documents."""
    case = IssuanceCase(
        {ANOTHER_SOURCE: NAMES, NEIGHBOR_SOURCE: frozenset({"neighbor.invalid"})},
        {},
        {},
        {},
        [],
        [],
    )
    for ref in case.pins:
        case.anchors[ref], case.docs[ref] = _issue(case, ref)
    return case


def _observe(case: IssuanceCase, ref: Ref) -> IssuedLeaf | None:
    """Record the sweep probe and answer with the case's current anchor."""
    case.observations.append(ref)
    return case.anchors[ref]


def _fetch(case: IssuanceCase, ref: Ref) -> tuple[int, object]:
    """Record the credential-less read and answer with the case's document."""
    case.reads.append(ref)
    return case.docs[ref]


def _refresh(case: IssuanceCase, obs: Callable[[Ref], IssuedLeaf | None] | None = None) -> Refresh:
    """Run one refresh sweep with fresh read/observation records."""
    case.reads.clear()
    case.observations.clear()
    observer: Callable[[Ref], IssuedLeaf | None] = (
        (lambda ref: _observe(case, ref)) if obs is None else obs
    )
    return issued_refresh(case.pins, case.grants, observer, lambda ref: _fetch(case, ref), NOW)


def _grant_reviewed(case: IssuanceCase) -> None:
    """Approve exactly the anchors currently presented by the sources."""
    case.grants.update(
        {
            ref: ApprovedScope(anchor.certificate_uid, anchor.hosts)
            for ref, anchor in case.anchors.items()
            if anchor is not None
        }
    )


def _assert_only_neighbor(result: Refresh, why: str) -> None:
    """Withhold the first source for exactly `why` while the neighbor stands."""
    assert set(result.material) == set(result.hosts)
    assert set(result.material) == set(result.fingerprints)
    assert set(result.fingerprints) == {NEIGHBOR_SOURCE}
    assert result.withdrawn == {ANOTHER_SOURCE: why}


def test_issuance_binding_requires_independent_writer_approval() -> None:
    case = _new_case()
    result = _refresh(case)
    assert result.withdrawn == {
        ANOTHER_SOURCE: "no-writer-approval",
        NEIGHBOR_SOURCE: "no-writer-approval",
    }
    assert case.reads == []
    assert case.observations == []
    _grant_reviewed(case)
    assert set(_refresh(case).material) == {ANOTHER_SOURCE, NEIGHBOR_SOURCE}
    assert case.reads == [ANOTHER_SOURCE, NEIGHBOR_SOURCE]
    assert case.observations == [
        ANOTHER_SOURCE,
        ANOTHER_SOURCE,
        NEIGHBOR_SOURCE,
        NEIGHBOR_SOURCE,
    ]


def test_issued_leaf_rotation_rebinds_only_on_the_current_anchor() -> None:
    case = _new_case()
    _grant_reviewed(case)
    rotation, newdoc = _issue(case, ANOTHER_SOURCE)
    case.docs[ANOTHER_SOURCE] = newdoc
    _assert_only_neighbor(_refresh(case), "issued-leaf-mismatch")
    case.anchors[ANOTHER_SOURCE] = rotation
    assert set(_refresh(case).material) == {ANOTHER_SOURCE, NEIGHBOR_SOURCE}


def _rotated_case() -> tuple[IssuanceCase, IssuedLeaf, IssuedLeaf]:
    """Build a case where the first source rotated and both sources are approved."""
    case = _new_case()
    _grant_reviewed(case)
    original = case.anchors[ANOTHER_SOURCE]
    assert original is not None
    rotation, newdoc = _issue(case, ANOTHER_SOURCE)
    case.docs[ANOTHER_SOURCE] = newdoc
    case.anchors[ANOTHER_SOURCE] = rotation
    return case, rotation, original


def test_stale_anchors_are_not_current_issuance() -> None:
    case, rotation, _original = _rotated_case()
    for before in (
        None,
        replace(rotation, source=NEIGHBOR_SOURCE),
        replace(rotation, hosts=frozenset({"one.invalid"})),
        replace(rotation, certificate_uid="replacement"),
        replace(rotation, request_version=""),
    ):
        case.anchors[ANOTHER_SOURCE] = before
        _assert_only_neighbor(_refresh(case), "no-current-issuance")
        assert case.reads == [NEIGHBOR_SOURCE]


def test_issuance_change_during_sweep_withdraws_the_changed_source() -> None:
    case, rotation, original = _rotated_case()
    for after in (
        None,
        original,
        replace(rotation, request_version="after"),
        replace(rotation, certificate_version="after"),
        replace(rotation, request_uid="other"),
    ):
        rotation_iter = iter((rotation, after))

        def swap(ref: Ref, _it: Iterator[IssuedLeaf | None] = rotation_iter) -> IssuedLeaf | None:
            """Answer the source's anchor, then the (possibly changed) re-read."""
            return next(_it) if ref == ANOTHER_SOURCE else case.anchors[NEIGHBOR_SOURCE]

        _assert_only_neighbor(_refresh(case, swap), "issuance-changed")
        assert case.reads == [ANOTHER_SOURCE, NEIGHBOR_SOURCE]


def test_denied_or_narrowed_grants_are_never_reused_as_approval() -> None:
    case, rotation, _original = _rotated_case()
    newdoc = case.docs[ANOTHER_SOURCE]
    case.docs[ANOTHER_SOURCE] = (403, None)
    _assert_only_neighbor(_refresh(case), "denied")
    assert case.observations == [ANOTHER_SOURCE, NEIGHBOR_SOURCE, NEIGHBOR_SOURCE]
    case.docs[ANOTHER_SOURCE] = newdoc
    case.grants[ANOTHER_SOURCE] = ApprovedScope(
        rotation.certificate_uid, frozenset({"one.invalid"})
    )
    _assert_only_neighbor(_refresh(case), "no-writer-approval")
    assert case.reads == [NEIGHBOR_SOURCE]


def test_unapproved_source_pin_is_invalid_ownership() -> None:
    case, rotation, _original = _rotated_case()
    case.grants[ANOTHER_SOURCE] = ApprovedScope(
        rotation.certificate_uid, frozenset({"one.invalid"})
    )
    case.pins[("unapproved", "tls")] = NAMES
    result = _refresh(case)
    assert result.withdrawn[ANOTHER_SOURCE] == "invalid-ownership"
    assert case.reads == [NEIGHBOR_SOURCE]


def test_malformed_approved_name_never_triggers_sensitive_io() -> None:
    from services.public_entry.tls_issued_refresh import ApprovedScope, issued_refresh

    ref = ("fixture", "tls")
    names = frozenset({"*.invalid"})

    def unexpected(_ref: Ref) -> Never:
        pytest.fail("invalid SNI triggered I/O")

    result = issued_refresh(
        {ref: names}, {ref: ApprovedScope("c", names)}, unexpected, unexpected, NOW
    )
    assert result.withdrawn == {ref: "invalid-ownership"}
    assert not result.material
