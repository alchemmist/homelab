"""Read-only blog chronology. Matching dates are NOT issued-leaf or writer evidence."""

import hashlib
import ipaddress
import json
import socket
import ssl
import subprocess
from datetime import UTC, datetime

import yaml
from cryptography import x509

from ci.quality.public_issued_leaf import CATALOG, ISSUER, OWNERS

NS, PIN, HOST, NAMES = OWNERS["www"]


def get(resource):
    return json.loads(
        subprocess.check_output(
            [
                "kubectl",
                "--context=Socrat",
                "--request-timeout=8s",
                "-n",
                NS,
                "get",
                resource,
                "-o",
                "json",
            ],
            timeout=12,
            stderr=subprocess.DEVNULL,
        )
    )


def snapshot():
    c = get("certificate/" + PIN)
    i = get("ingress/blog")
    requests = get("certificaterequests.cert-manager.io")
    return chronology(c, i, requests["items"])


def chronology(c, i, requests):
    m = c["metadata"]
    im = i["metadata"]
    s = c["status"]
    spec = c["spec"]
    refs = [r for r in m["ownerReferences"] if r.get("controller") is True]
    tls = i["spec"]["tls"]
    ready = [x for x in s["conditions"] if x["type"] == "Ready"]
    witness = tuple(o[k] for o in (m, im) for k in ("uid", "resourceVersion"))
    if not (
        all(isinstance(v, str) and v for v in witness)
        and m["namespace"] == im["namespace"] == NS
        and m["name"] == spec["secretName"] == PIN
        and im["name"] == "blog"
        and not any(x.get("deletionTimestamp") for x in (m, im))
        and len(refs) == 1
        and refs[0]["uid"] == im["uid"]
        and refs[0]["apiVersion"] == i["apiVersion"] == "networking.k8s.io/v1"
        and refs[0]["kind"] == i["kind"] == "Ingress"
        and refs[0]["name"] == im["name"]
        and c["kind"] == "Certificate"
        and c["apiVersion"] == "cert-manager.io/v1"
        and spec["issuerRef"] == ISSUER
        and sorted(spec["dnsNames"]) == sorted(NAMES)
        and len(tls) == 1
        and tls[0]["secretName"] == PIN
        and sorted(tls[0]["hosts"]) == sorted(NAMES)
        and len(ready) == 1
        and ready[0]["status"] == "True"
        and ready[0]["observedGeneration"] == m["generation"]
        and "revision" not in s
        and not requests
    ):
        raise ValueError("baseline changed")
    return witness, tuple(
        datetime.fromisoformat(v)
        for v in (s["notBefore"], m["creationTimestamp"], s["renewalTime"], s["notAfter"])
    )


def public_leaf(ip):
    with (
        socket.create_connection((str(ipaddress.IPv4Address(ip)), 443), timeout=4) as raw,
        ssl.create_default_context().wrap_socket(raw, server_hostname=HOST) as conn,
    ):
        der = conn.getpeercert(binary_form=True)
        c = x509.load_der_x509_certificate(der)
        return hashlib.sha256(der).digest(), c.not_valid_before_utc, c.not_valid_after_utc


def measure(read, wire, ip, now):
    before = read()
    first = wire(ip)
    after = read()
    second = wire(ip)
    if before != after or first != second:
        raise ValueError("changed during samples")
    start, created, renew, end = before[1]
    return {
        "ownerIngressMatches": True,
        "currentRevisionAbsent": True,
        "namespaceRequestCount": 0,
        "trustedHomeLeafDatesMatchStatus": first[1:] == (start, end),
        "statusValidityStartsBeforeCertificateCreated": start < created,
        "renewalScheduledInFuture": now < renew < end,
        "issuedLeafMatchEstablished": False,
        "writerApproved": False,
    }


def main():
    try:
        result = measure(
            snapshot,
            public_leaf,
            yaml.safe_load(CATALOG.read_text())["replicas"]["home"]["publicIP"],
            datetime.now(UTC),
        )
    except (KeyError, IndexError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        print('{"baseline":"not-established"}')
        return 1
    print(json.dumps(result, sort_keys=True))
    return int(not result["trustedHomeLeafDatesMatchStatus"])


if __name__ == "__main__":
    raise SystemExit(main())
