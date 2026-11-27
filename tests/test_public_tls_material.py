"""Only ephemeral TLS material; never use cluster access in these tests."""

from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from services.public_entry.tls_material import MaterialRejected, leaf_identity

NOW = datetime.now(UTC)
NAMES = frozenset({"one.invalid", "two.invalid"})


def pair(
    names=NAMES,
    *,
    ca=False,
    purpose=ExtendedKeyUsageOID.SERVER_AUTH,
    signer=None,
    extra_sans=(),
    key=None,
    subject_public=None,
):
    sk = key or ec.generate_private_key(ec.SECP256R1())
    dn = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fixture")])
    b = (
        x509.CertificateBuilder()
        .subject_name(dn)
        .issuer_name(dn)
        .public_key(subject_public or sk.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(minutes=5))
        .not_valid_after(NOW + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [*(x509.DNSName(n) for n in names), *extra_sans]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca, None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([purpose]), critical=False)
    )
    cert = b.sign(signer or sk, hashes.SHA256())
    return sk, cert


def pem(c):
    return c.public_bytes(serialization.Encoding.PEM)


def private(k):
    return k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def test_exact_leaf_and_linked_chain():
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
def test_bad_source_is_rejected_without_parser_or_material_in_diagnostics(fault):
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
        purpose=ExtendedKeyUsageOID.CLIENT_AUTH
        if fault == "purpose"
        else ExtendedKeyUsageOID.SERVER_AUTH,
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
    with pytest.raises(MaterialRejected, match="^TLS source rejected$") as exc:
        leaf_identity(chain, secret, names, now)
    assert exc.value.__context__ is None


def test_matching_dns_entries_do_not_authorize_a_uri_identity():
    key, leaf = pair(extra_sans=(x509.UniformResourceIdentifier("urn:fixture:other"),))
    with pytest.raises(MaterialRejected):
        leaf_identity(pem(leaf), private(key), NAMES, NOW)


def test_completed_refresh_admits_only_independent_owned_sources():
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
    assert select_sources(
        {**owners, stranger: frozenset({"alias.invalid"})}, both, NOW
    ) == {right: wanted[right]}
    assert select_sources(owners, both, NOW) == wanted
    assert "PRIVATE KEY" not in repr(first)


def test_rsa_public_key_identity_uses_the_complete_key():
    sk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _, leaf = pair(key=sk)
    assert (
        leaf_identity(pem(leaf), private(sk), NAMES, NOW)
        == leaf.fingerprint(hashes.SHA256()).hex()
    )
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(MaterialRejected):
        leaf_identity(pem(leaf), private(other), NAMES, NOW)


def test_rsa_same_modulus_with_different_exponent_is_not_the_leaf_key():
    sk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = sk.public_key().public_numbers().n
    other_public = rsa.RSAPublicNumbers(3, n).public_key()
    issuer, ca = pair(ca=True)
    _, leaf = pair(key=sk, subject_public=other_public, signer=issuer)
    with pytest.raises(MaterialRejected):
        leaf_identity(pem(leaf) + pem(ca), private(sk), NAMES, NOW)


def test_exact_refresh_does_not_lose_a_denial_on_later_failure_or_refetch_keys():
    import base64

    from services.public_entry.tls_refresh import refresh

    refs = [("owner", "a"), ("owner", "b"), ("owner", "c")]
    pins = {ref: frozenset({ref[1] + ".invalid"}) for ref in refs}
    replies = {}
    calls = []
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

    def read(ref):
        calls.append(ref)
        return replies[ref]

    def scan():
        calls.clear()
        r = refresh(pins, read, NOW)
        assert calls == refs
        return r

    initial = scan()
    assert set(initial.material) == set(refs) and not initial.withdrawn
    original = dict(replies)
    replies[refs[1]] = ("403", None)
    assert scan().withdrawn == {refs[1]: "invalid-response"}
    replies[refs[0]] = (403, {"message": "sensitive-fixture"})
    replies[refs[1]] = (503, None)
    partial = scan()
    assert partial.withdrawn == {refs[0]: "denied", refs[1]: "unavailable"} and set(
        partial.material
    ) == {refs[2]}
    assert partial.fingerprints[refs[2]] == initial.fingerprints[refs[2]]
    replies[refs[1]] = original[refs[0]]
    assert scan().withdrawn[refs[1]] == "invalid-response"
    replies.clear()
    replies.update(original)
    assert scan().fingerprints == initial.fingerprints
    replies[refs[0]][1]["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    assert scan().withdrawn == {refs[0]: "invalid-response"}
    assert "PRIVATE KEY" not in repr(initial) and "sensitive-fixture" not in str(
        partial.withdrawn
    )


def test_ambiguous_ownership_is_not_fetched_even_when_one_key_would_validate():
    from services.public_entry.tls_refresh import refresh

    owners = {
        ("a", "tls"): frozenset({"same.invalid"}),
        ("b", "tls"): frozenset({"same.invalid"}),
        ("c", "tls"): frozenset(),
    }

    def forbidden(ref):
        raise AssertionError("unexpected key read")

    report = refresh(owners, forbidden, NOW)
    assert (
        not report.material
        and not report.hosts
        and set(report.withdrawn.values()) == {"invalid-ownership"}
    )


def test_truncated_http_response_after_denial_does_not_cancel_completed_batch():
    from http.client import IncompleteRead
    from json import JSONDecodeError

    from services.public_entry.tls_refresh import refresh

    a, b, c = [("owner", n) for n in "abc"]

    def read(ref):
        if ref == a:
            return 403, None
        if ref == b:
            raise IncompleteRead(b"private fixture bytes")
        raise JSONDecodeError("bad reply", "private fixture bytes", 0)

    result = refresh(
        {ref: frozenset({ref[1] + ".invalid"}) for ref in (a, b, c)}, read, NOW
    )
    assert dict(result.withdrawn) == {
        a: "denied",
        b: "unavailable",
        c: "invalid-response",
    }
    assert not result.hosts and not result.material


def test_loopback_listener_witness_distinguishes_withdrawal_from_trust_and_connection_failure(
    tmp_path,
):
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
    seen = []

    def sni(sock, host, context):
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

        def accept():
            for _ in range(7):
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
        assert observe(
            port, scope, {left: "0" * 64, right: fp, gone: fp}, trust=client
        ) == {left: "different-leaf", right: "trusted-match", gone: "missing-leaf"}
        assert observe(port, frozenset({left}), {}) == {left: "untrusted-leaf"}
        worker.join(4)
        assert not worker.is_alive() and len(seen) == 7
    assert observe(port, NAMES, {}) == {name: "unreachable" for name in NAMES}


def test_witness_rejects_out_of_scope_pin_before_probing():
    from services.public_entry.tls_witness import observe

    with pytest.raises(ValueError, match="scope"):
        observe(443, NAMES, {"other.invalid": "0" * 64})


@pytest.mark.parametrize("host", ["a..b", "a.invalid.", ".invalid"])
def test_witness_rejects_empty_hostname_labels(host):
    from services.public_entry.tls_witness import observe

    with pytest.raises(ValueError, match="identity"):
        observe(443, frozenset({host}), {})


def test_witness_timeout_does_not_acknowledge_withdrawal(monkeypatch):
    from services.public_entry import tls_witness

    def stall(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(tls_witness.socket, "create_connection", stall)
    assert tls_witness.observe(443, NAMES, {}) == {host: "timeout" for host in NAMES}


def test_issuance_binding_never_implies_writer_approval_or_reuses_a_denied_source():
    import base64
    from dataclasses import replace

    from services.public_entry.tls_issued_refresh import (
        ApprovedScope,
        IssuedLeaf,
        issued_refresh,
    )

    a, b = ("one", "tls"), ("two", "tls")
    pins = {a: NAMES, b: frozenset({"neighbor.invalid"})}
    grants = {}
    anchors = {}
    docs = {}
    reads = []
    observations = []

    def issue(ref):
        k, c = pair(pins[ref])
        fingerprint = c.fingerprint(hashes.SHA256()).hex()
        anchor = IssuedLeaf(
            ref,
            pins[ref],
            "cert-" + ref[0],
            "rv-A",
            "req-" + ref[0],
            "rv-B",
            fingerprint,
        )
        doc = {
            "kind": "Secret",
            "apiVersion": "v1",
            "type": "kubernetes.io/tls",
            "metadata": {"namespace": ref[0], "name": ref[1]},
            "data": {
                "tls.crt": base64.b64encode(pem(c)).decode(),
                "tls.key": base64.b64encode(private(k)).decode(),
            },
        }
        return anchor, (200, doc)

    for ref in pins:
        anchors[ref], docs[ref] = issue(ref)

    def observe(ref):
        observations.append(ref)
        return anchors[ref]

    def get(ref):
        reads.append(ref)
        return docs[ref]

    def run(obs=observe):
        reads.clear()
        observations.clear()
        return issued_refresh(pins, grants, obs, get, NOW)

    def assert_only_b(result, why):
        assert set(result.material) == set(result.hosts) == set(
            result.fingerprints
        ) == {b} and result.withdrawn == {a: why}

    assert (
        run().withdrawn == {a: "no-writer-approval", b: "no-writer-approval"}
        and reads == observations == []
    )
    grants.update(
        {ref: ApprovedScope(w.certificate_uid, w.hosts) for ref, w in anchors.items()}
    )
    assert (
        set(run().material) == {a, b}
        and reads == [a, b]
        and observations == [a, a, b, b]
    )
    original = anchors[a]
    rotation, newdoc = issue(a)
    docs[a] = newdoc
    assert_only_b(run(), "issued-leaf-mismatch")
    anchors[a] = rotation
    assert set(run().material) == {a, b}
    for before in [
        None,
        replace(rotation, source=b),
        replace(rotation, hosts=frozenset({"one.invalid"})),
        replace(rotation, certificate_uid="replacement"),
        replace(rotation, request_version=""),
    ]:
        anchors[a] = before
        assert_only_b(run(), "no-current-issuance")
        assert reads == [b]
    anchors[a] = rotation
    for after in [
        None,
        original,
        replace(rotation, request_version="after"),
        replace(rotation, certificate_version="after"),
        replace(rotation, request_uid="other"),
    ]:
        it = iter((rotation, after))
        assert_only_b(
            run(lambda ref: next(it) if ref == a else anchors[b]), "issuance-changed"
        )
        assert reads == [a, b]
    docs[a] = (403, None)
    assert_only_b(run(), "denied")
    assert observations == [a, b, b]
    docs[a] = newdoc
    grants[a] = ApprovedScope(rotation.certificate_uid, frozenset({"one.invalid"}))
    assert_only_b(run(), "no-writer-approval")
    assert reads == [b]
    pins[("unapproved", "tls")] = NAMES
    assert run().withdrawn[a] == "invalid-ownership" and reads == [b]


def test_malformed_approved_name_never_triggers_sensitive_io():
    from services.public_entry.tls_issued_refresh import ApprovedScope, issued_refresh

    ref = ("fixture", "tls")
    names = frozenset({"*.invalid"})
    unexpected = lambda _: pytest.fail("invalid SNI triggered I/O")
    result = issued_refresh(
        {ref: names}, {ref: ApprovedScope("c", names)}, unexpected, unexpected, NOW
    )
    assert result.withdrawn == {ref: "invalid-ownership"} and not result.material
