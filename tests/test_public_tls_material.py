"""Only ephemeral TLS material; never use cluster access in these tests."""

from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
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
):
    sk = ec.generate_private_key(ec.SECP256R1())
    dn = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fixture")])
    b = (
        x509.CertificateBuilder()
        .subject_name(dn)
        .issuer_name(dn)
        .public_key(sk.public_key())
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
