"""Summarize direct binding subjects without exposing identities or reading keys."""

import argparse
import json
import subprocess
from collections import Counter, defaultdict

from ci.quality.public_tls_writer_grants import grants


def summarize(rows, active, requester):
    """Group literal RBAC subjects, not people, effective permissions or approvals."""
    subjects = defaultdict(set)
    for row in rows:
        for subject in row["subjects"]:
            kind, name = subject["kind"], subject["name"]
            if not name or kind not in {"ServiceAccount", "Group", "User"}:
                raise ValueError("invalid binding subject")
            ns = None
            if kind == "ServiceAccount":
                ns = subject.get("namespace") or row["binding"][1]
                if not ns:
                    raise ValueError("unscoped service account")
            subjects[kind, ns, name].update(row["verbs"])
    counts = Counter()
    verbs = Counter()
    requester_verbs = set()
    for (kind, ns, name), allowed in subjects.items():
        category = kind
        if kind == "ServiceAccount":
            category = (
                "serviceAccountWithRunningPod"
                if (ns, name) in active
                else "serviceAccountWithoutObservedRunningPod"
            )
            if "system:serviceaccount:" + ns + ":" + name == requester:
                requester_verbs.update(allowed)
        elif kind == "Group" and name in {
            "system:authenticated",
            "system:serviceaccounts",
            "system:unauthenticated",
        }:
            category = "clusterWideBuiltinGroup"
        elif kind == "Group" and name.startswith("system:serviceaccounts:"):
            category = "namespaceServiceAccountsGroup"
        counts[category] += 1
        verbs.update(allowed)
    return {
        "directBindings": len(rows),
        "distinctSubjectDescriptors": len(subjects),
        "subjectClasses": dict(counts),
        "descriptorsByVerb": dict(verbs),
        "requesterDirectServiceAccountVerbs": sorted(requester_verbs),
        "writerApproved": False,
    }


def _get(*args):
    return subprocess.check_output(
        ["kubectl", "--request-timeout=15s", *args],
        timeout=60,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _current_requester(ns, source):
    certs = json.loads(_get("-n", ns, "get", "certificates", "-o", "json"))["items"]
    requests = json.loads(_get("-n", ns, "get", "certificaterequests", "-o", "json"))["items"]
    return requester_for(source, certs, requests)


def requester_for(source, certs, requests):
    """Attribute a current request, not a Secret write, to its recorded API caller."""
    (cert,) = [
        c
        for c in certs
        if c["spec"]["secretName"] == source and not c["metadata"].get("deletionTimestamp")
    ]
    if not any(
        c["type"] == "Ready"
        and c["status"] == "True"
        and c.get("observedGeneration") == cert["metadata"]["generation"]
        for c in cert["status"]["conditions"]
    ):
        raise ValueError("no current ready certificate")
    revision = cert["status"]["revision"]
    uid = cert["metadata"]["uid"]
    (req,) = [
        r
        for r in requests
        if not r["metadata"].get("deletionTimestamp")
        and r["metadata"].get("annotations", {}).get("cert-manager.io/certificate-revision")
        == str(revision)
        and any(
            o.get("controller") is True
            and o["apiVersion"] == "cert-manager.io/v1"
            and o["kind"] == "Certificate"
            and o["uid"] == uid
            and o["name"] == cert["metadata"]["name"]
            for o in r["metadata"].get("ownerReferences", [])
        )
        and r["spec"]["issuerRef"] == cert["spec"]["issuerRef"]
        and any(c["type"] == "Ready" and c["status"] == "True" for c in r["status"]["conditions"])
    ]
    return req["spec"]["username"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("source")
    args = parser.parse_args()
    try:
        requester = _current_requester(args.namespace, args.source)
        objects = json.loads(
            _get("get", "roles,rolebindings,clusterroles,clusterrolebindings", "-A", "-o", "json")
        )["items"]
        active = {
            tuple(row.split())
            for row in _get(
                "get",
                "pods",
                "-A",
                "--field-selector=status.phase=Running",
                "-o",
                "custom-columns=NS:.metadata.namespace,SA:.spec.serviceAccountName",
                "--no-headers",
            ).splitlines()
        }
        report = summarize(grants(args.namespace, args.source, objects), active, requester)
    except (subprocess.SubprocessError, OSError, KeyError, ValueError, TypeError):
        parser.exit(1, "Incomplete metadata observation; no writer assessment.\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
