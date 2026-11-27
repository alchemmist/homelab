"""Validate one source's TLS material before adding its routers to a snapshot.

No I/O, persistence or trust-store access. The caller supplies names from the
reviewed source inventory, never from the presented certificate. Success is not
proof of browser trust, snapshot application or authorization to read a Secret.
"""

import re
from datetime import datetime
from typing import Never

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_CERT = rb"-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----"
_KEY = rb"-----BEGIN (PRIVATE KEY|EC PRIVATE KEY|RSA PRIVATE KEY)-----\r?\n[A-Za-z0-9+/=\r\n]+-----END \1-----"


class MaterialRejected(ValueError):
    """Safe, fixed diagnostics only; never attach input bytes or parser errors."""


def _reject() -> Never:
    raise MaterialRejected("TLS source rejected")


def valid_dns_name(name: str) -> bool:
    """Only a concrete, lower-case DNS name can enter the reviewed SNI set."""
    return (
        isinstance(name, str)
        and 0 < len(name) <= 253
        and all(_LABEL.fullmatch(label) for label in name.split("."))
    )


def leaf_identity(
    chain_pem: bytes, key_pem: bytes, names: frozenset[str], now: datetime
) -> str:
    """Return only the authorized leaf SHA-256; reject a malformed or unapproved pair."""
    if not names or now.utcoffset() is None:
        _reject()
    if not all(valid_dns_name(n) for n in names):
        _reject()
    if len(chain_pem) > 128 * 1024 or len(key_pem) > 32 * 1024:
        _reject()
    blocks = re.findall(_CERT, chain_pem)
    if (
        not 1 <= len(blocks) <= 8
        or re.sub(_CERT, b"", chain_pem).strip()
        or not re.fullmatch(_KEY, key_pem.strip())
    ):
        _reject()
    try:
        chain = [x509.load_pem_x509_certificate(block) for block in blocks]
        leaf = chain[0]
        sans = leaf.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        if (
            len(sans) != len(names)
            or not all(isinstance(s, x509.DNSName) for s in sans)
            or set(sans.get_values_for_type(x509.DNSName)) != names
        ):
            _reject()
        if any(
            not cert.not_valid_before_utc <= now < cert.not_valid_after_utc
            for cert in chain
        ):
            _reject()
        for child, issuer in zip(chain, chain[1:], strict=False):
            if not issuer.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value.ca:
                _reject()
            child.verify_directly_issued_by(issuer)
        for ext in leaf.extensions:
            if isinstance(ext.value, x509.BasicConstraints) and ext.value.ca:
                _reject()
            if (
                isinstance(ext.value, x509.ExtendedKeyUsage)
                and ExtendedKeyUsageOID.SERVER_AUTH not in ext.value
            ):
                _reject()
        sk = serialization.load_pem_private_key(key_pem, password=None)
        if (
            not isinstance(sk, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey))
            or sk.public_key() != leaf.public_key()
        ):
            _reject()
        return leaf.fingerprint(hashes.SHA256()).hex()
    except (
        ValueError,
        TypeError,
        UnsupportedAlgorithm,
        x509.ExtensionNotFound,
        x509.DuplicateExtension,
        x509.UnsupportedGeneralNameType,
        InvalidSignature,
    ):
        pass
    _reject()
