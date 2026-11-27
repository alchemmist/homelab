"""Read-only issued-leaf witness for two reviewed public routes (never reads Secrets).

An Approved CertificateRequest is issuance evidence, NOT approval of writers or
permission to provision a listener. A trusted TLS match alone is not HTTP, local
socket ownership, or a continuous/atomic observation across entrances.
"""

import argparse
import base64
import hashlib
import ipaddress
import json
import socket
import ssl
import subprocess
from datetime import UTC, datetime

import yaml
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization

from ci.quality.public_web import CATALOG
from services.public_entry.tls_issued_refresh import IssuedLeaf

# Query only the reviewed frontend SNI; the blog certificate also covers apex.
OWNERS = {
    "www": ("blog", "blog-tls", "www.alchemmist.xyz", {"www.alchemmist.xyz", "alchemmist.xyz"}),
    "wiki": ("wiki", "wiki-tls", "wiki.socrat.alchemmist.xyz", {"wiki.socrat.alchemmist.xyz"}),
}
ISSUER = {"group": "cert-manager.io", "kind": "ClusterIssuer", "name": "letsencrypt-http01"}


class NoEvidence(ValueError):
    """No unique current issuance can be used as an expected wire leaf."""


def require(ok, reason):
    if not ok:
        raise NoEvidence(reason)


def san_set(obj):
    names = list(obj.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
    require(all(isinstance(n, x509.DNSName) for n in names), "non-dns-san")
    return sorted(n.value for n in names)


def decode(value):
    require(isinstance(value, str) and 0 < len(value) <= 131072, "invalid-public-material")
    return base64.b64decode(value, validate=True)


def evidence(owner, catalog, certs, requests, now):
    ns, pin, _, sans = OWNERS[owner]
    require(
        {
            n
            for n, p in catalog["hosts"][ns].items()
            if p.get("tlsSourceName") == pin
            and p.get("dns") == "managed"
            and p.get("route", "web") == "web"
        }
        == sans,
        "catalog-pin-changed",
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
        and spec.get("issuerRef") == ISSUER
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
        controllers = [o for o in rm.get("ownerReferences", []) if o.get("controller") is True]
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
        and req["spec"].get("issuerRef") == ISSUER,
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
            for value in (m["uid"], m["resourceVersion"], rm["uid"], rm["resourceVersion"])
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
    return (
        m["uid"],
        m["resourceVersion"],
        rm["uid"],
        rm["resourceVersion"],
        leaf.fingerprint(hashes.SHA256()).hex(),
    )


def issuance_anchor(owner, catalog, certs, requests, now):
    """Adapt validated public evidence, never a writer grant, for an in-memory rehearsal."""
    ns, pin, _, sans = OWNERS[owner]
    return IssuedLeaf((ns, pin), frozenset(sans), *evidence(owner, catalog, certs, requests, now))


def observe(owner):
    ns = OWNERS[owner][0]
    lists = []
    for resource in ("certificates.cert-manager.io", "certificaterequests.cert-manager.io"):
        raw = subprocess.check_output(
            [
                "kubectl",
                "--context=Socrat",
                "--request-timeout=8s",
                "-n",
                ns,
                "get",
                resource,
                "-o",
                "json",
            ],
            timeout=12,
            stderr=subprocess.DEVNULL,
        )
        lists.append(json.loads(raw)["items"])
    return evidence(owner, yaml.safe_load(CATALOG.read_text()), *lists, datetime.now(UTC))


def wire(host, ip):
    try:
        with (
            socket.create_connection((ip, 443), timeout=4) as raw,
            ssl.create_default_context().wrap_socket(raw, server_hostname=host) as conn,
        ):
            return hashlib.sha256(conn.getpeercert(binary_form=True)).hexdigest()
    except ssl.SSLCertVerificationError:
        return "untrusted"
    except ssl.SSLError:
        return "tls-failed"
    except OSError:
        return "not-connected"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner", choices=OWNERS)
    owner = parser.parse_args().owner
    try:
        before = observe(owner)
        cat = yaml.safe_load(CATALOG.read_text())
        peers = cat["replicas"]
        require(set(peers) == {"home", "nl", "moscow"}, "unexpected-sites")
        samples = {}
        for site, rep in peers.items():
            value = wire(OWNERS[owner][2], str(ipaddress.IPv4Address(rep["publicIP"])))
            samples[site] = (
                ("trusted-match" if value == before[-1] else "trusted-different-leaf")
                if len(value) == 64
                else value
            )
        require(observe(owner) == before, "changed-during-sweep")
    except NoEvidence as e:
        print(json.dumps({"issuance": str(e), "writerApproved": False}))
        return 1
    except (
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
