"""Read-only issued-leaf witness for two reviewed public routes (never reads Secrets).

An Approved CertificateRequest is issuance evidence, NOT approval of writers or
permission to provision a listener. A trusted TLS match alone is not HTTP, local
socket ownership, or a continuous/atomic observation across entrances.
"""

import argparse
import hashlib
import ipaddress
import json
import socket
import ssl
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime

import yaml
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm

from ci.quality import common
from ci.quality.public_web import CATALOG
from services.public_entry.tls_issuance import (
    AnchorScope,
    NoEvidenceError,
    _mapping,
    _text,
    require,
    validated_anchor,
)
from services.public_entry.tls_issued_refresh import IssuedLeaf

# Query only the reviewed frontend SNI; the blog certificate also covers apex.
OWNERS: dict[str, tuple[str, str, str, frozenset[str]]] = {
    "www": (
        "blog",
        "blog-tls",
        "www.alchemmist.xyz",
        frozenset({"www.alchemmist.xyz", "alchemmist.xyz"}),
    ),
    "wiki": (
        "wiki",
        "wiki-tls",
        "wiki.socrat.alchemmist.xyz",
        frozenset({"wiki.socrat.alchemmist.xyz"}),
    ),
}
ISSUER: dict[str, str] = {
    "group": "cert-manager.io",
    "kind": "ClusterIssuer",
    "name": "letsencrypt-http01",
}
KUBE = [
    "kubectl",
    "--context=Socrat",
    "--request-timeout=8s",
]
REQUESTS = ("certificates.cert-manager.io", "certificaterequests.cert-manager.io")
KUBE_TIMEOUT = 12
EXPECTED_SITES = {"home", "nl", "moscow"}
FINGERPRINT_LENGTH = 64
MSG_EXPECTED_MAPPING = "expected a mapping observation"


def issuance_anchor(
    owner: str,
    catalog: Mapping[str, object],
    certs: object,
    requests: object,
    now: datetime,
) -> IssuedLeaf:
    """Read the pinned catalog contract, then validate the current issuance anchor."""
    ns, pin, _, sans = OWNERS[owner]
    require(
        ok={
            n
            for n, p in _mapping(_mapping(catalog["hosts"])[ns]).items()
            if _mapping(p).get("tlsSourceName") == pin
            and _mapping(p).get("dns") == "managed"
            and _mapping(p).get("route", "web") == "web"
        }
        == sans,
        reason="catalog-pin-changed",
    )
    return validated_anchor(AnchorScope((ns, pin), frozenset(sans), ISSUER), certs, requests, now)


def evidence(
    owner: str,
    catalog: Mapping[str, object],
    certs: object,
    requests: object,
    now: datetime,
) -> tuple[str, str, str, str, str]:
    """Summary of the currently pinned, Approved and matching issued leaf."""
    anchor = issuance_anchor(owner, catalog, certs, requests, now)
    return (
        anchor.certificate_uid,
        anchor.certificate_version,
        anchor.request_uid,
        anchor.request_version,
        anchor.sha256,
    )


def observe(owner: str) -> tuple[str, str, str, str, str]:
    """Read the live Certificate/CertificateRequest objects for the chosen route."""
    ns = OWNERS[owner][0]
    lists: list[object] = []
    for resource in REQUESTS:
        raw = common.command([*KUBE, "-n", ns, "get", resource, "-o", "json"], timeout=15)
        lists.append(json.loads(raw.stdout)["items"])
    return evidence(
        owner,
        yaml.safe_load(CATALOG.read_text()),
        lists[0],
        lists[1],
        datetime.now(UTC),
    )


def wire(host: str, ip: str) -> str:
    """One TLS handshake against the reviewed frontend; never trust it further."""
    try:
        with (
            socket.create_connection((ip, 443), timeout=4) as raw,
            ssl.create_default_context().wrap_socket(raw, server_hostname=host) as conn,
        ):
            presented = conn.getpeercert(binary_form=True)
            if presented is None:
                return "tls-failed"
            return hashlib.sha256(presented).hexdigest()
    except ssl.SSLCertVerificationError:
        return "untrusted"
    except ssl.SSLError:
        return "tls-failed"
    except OSError:
        return "not-connected"


def main() -> int:
    """Witness both reviewed routes; narrate wire matches without ever granting writers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner", choices=OWNERS)
    owner = parser.parse_args().owner
    try:
        before = observe(owner)
        cat = yaml.safe_load(CATALOG.read_text())
        peers = _mapping(cat)["replicas"]
        require(ok=set(_mapping(peers)) == EXPECTED_SITES, reason="unexpected-sites")
        samples: dict[str, str] = {}
        for site, rep_obj in _mapping(peers).items():
            rep = _mapping(rep_obj)
            address = _text(rep["publicIP"])
            value = wire(OWNERS[owner][2], str(ipaddress.IPv4Address(address)))
            samples[site] = (
                ("trusted-match" if value == before[-1] else "trusted-different-leaf")
                if len(value) == FINGERPRINT_LENGTH
                else value
            )
        require(ok=observe(owner) == before, reason="changed-during-sweep")
    except NoEvidenceError as e:
        print(json.dumps({"issuance": str(e), "writerApproved": False}))
        return 1
    except (
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        x509.ExtensionNotFound,
        x509.DuplicateExtension,
        UnsupportedAlgorithm,
        subprocess.SubprocessError,
        OSError,
    ):
        print('{"issuance":"incomplete","writerApproved":false}')
        return 1
    print(
        json.dumps(
            {"issuance": "current", "wire": samples, "writerApproved": False}, sort_keys=True
        )
    )
    return int(any(s != "trusted-match" for s in samples.values()))


if __name__ == "__main__":
    raise SystemExit(main())
