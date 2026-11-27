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
    assert leaf_identity(pem(leaf), private(sk), NAMES, NOW) == leaf.fingerprint(hashes.SHA256()).hex()
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
