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
from datetime import UTC, datetime

import yaml
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm

from ci.quality.public_web import CATALOG
from services.public_entry.tls_issuance import NoEvidence, require, validated_anchor

# Query only the reviewed frontend SNI; the blog certificate also covers apex.
OWNERS = {
    "www": ("blog", "blog-tls", "www.alchemmist.xyz", {"www.alchemmist.xyz", "alchemmist.xyz"}),
    "wiki": ("wiki", "wiki-tls", "wiki.socrat.alchemmist.xyz", {"wiki.socrat.alchemmist.xyz"}),
}
ISSUER = {"group": "cert-manager.io", "kind": "ClusterIssuer", "name": "letsencrypt-http01"}


def issuance_anchor(owner, catalog, certs, requests, now):
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
    return validated_anchor((ns, pin), frozenset(sans), ISSUER, certs, requests, now)


def evidence(owner, catalog, certs, requests, now):
    anchor = issuance_anchor(owner, catalog, certs, requests, now)
    return (
        anchor.certificate_uid,
        anchor.certificate_version,
        anchor.request_uid,
        anchor.request_version,
        anchor.sha256,
    )


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
