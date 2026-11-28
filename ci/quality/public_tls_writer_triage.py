"""Summarize direct binding subjects without exposing identities or reading keys."""

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from typing import TypedDict, cast

from ci.quality import common
from ci.quality.public_tls_writer_grants import grants
from services.public_entry.tls_issuance import _items, _mapping, _text

MSG_INVALID_BINDING_SUBJECT = "invalid binding subject"
MSG_UNSCOPED_SERVICE_ACCOUNT = "unscoped service account"
MSG_NO_CURRENT_READY_CERTIFICATE = "no current ready certificate"
BUILTIN_CLUSTER_WIDE_GROUPS = {
    "system:authenticated",
    "system:serviceaccounts",
    "system:unauthenticated",
}
SUBJECT_KINDS = {"ServiceAccount", "Group", "User"}
ActivePods = AbstractSet[tuple[str, str]]
Subjects = defaultdict[tuple[str, str, str], set[str]]


class _SubjectObservation(TypedDict):
    """The grant rows summarize consumes: identities and verbs only."""

    binding: list[str | None]
    subjects: list[dict[str, object]]
    verbs: list[str]


def _account_class(name: str, ns: str, active: ActivePods) -> str:
    """Classify one service-account subject by whether a running pod was observed."""
    return (
        "serviceAccountWithRunningPod"
        if (ns, name) in active
        else "serviceAccountWithoutObservedRunningPod"
    )


def _subject_map(rows: Sequence[_SubjectObservation]) -> Subjects:
    """Collect one deduplicated verb set per literal subject descriptor."""
    subjects: Subjects = defaultdict(set)
    for row in rows:
        for subject in row["subjects"]:
            body = _mapping(subject)
            kind = _text(body["kind"])
            name = _text(body["name"])
            if not name or kind not in SUBJECT_KINDS:
                raise ValueError(MSG_INVALID_BINDING_SUBJECT)
            ns = ""
            if kind == "ServiceAccount":
                sourced = subject.get("namespace") or row["binding"][1]
                if not sourced:
                    raise ValueError(MSG_UNSCOPED_SERVICE_ACCOUNT)
                ns = _text(sourced)
            subjects[kind, ns, name].update(row["verbs"])
    return subjects


def summarize(
    rows: Sequence[_SubjectObservation], active: ActivePods, requester: str
) -> dict[str, object]:
    """Group literal RBAC subjects, not people, effective permissions or approvals."""
    subjects = _subject_map(rows)
    counts: Counter[str] = Counter()
    verbs: Counter[str] = Counter()
    requester_verbs: set[str] = set()
    for (kind, ns, name), allowed in subjects.items():
        category = kind
        if kind == "ServiceAccount" and "system:serviceaccount:" + ns + ":" + name == requester:
            requester_verbs.update(allowed)
        if kind == "ServiceAccount":
            category = _account_class(name, ns, active)
        elif kind == "Group" and name in BUILTIN_CLUSTER_WIDE_GROUPS:
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


def _get(*args: str) -> str:
    """Fetch one kubectl JSON view through the audited dispatcher, no failure output."""
    return common.command(["kubectl", "--request-timeout=15s", *args], timeout=60).stdout


def _current_requester(ns: str, source: str) -> str:
    """Attribute the freshest issued request in one namespace to its API caller."""
    certs = json.loads(_get("-n", ns, "get", "certificates", "-o", "json"))["items"]
    requests = json.loads(_get("-n", ns, "get", "certificaterequests", "-o", "json"))["items"]
    return requester_for(source, certs, requests)


def requester_for(source: str, certs: Sequence[object], requests: Sequence[object]) -> str:
    """Attribute a current request, not a Secret write, to its recorded API caller."""
    candidates = []
    for observed in certs:
        obj = _mapping(observed)
        meta = _mapping(obj["metadata"])
        spec = _mapping(obj["spec"])
        if spec["secretName"] == source and not meta.get("deletionTimestamp"):
            candidates.append(obj)
    (cert,) = candidates
    if not any(
        _mapping(condition)["type"] == "Ready"
        and _mapping(condition)["status"] == "True"
        and _mapping(condition).get("observedGeneration")
        == _mapping(cert["metadata"])["generation"]
        for condition in _items(_mapping(cert["status"])["conditions"])
    ):
        raise ValueError(MSG_NO_CURRENT_READY_CERTIFICATE)
    revision = _mapping(cert["status"])["revision"]
    uid = _mapping(cert["metadata"])["uid"]
    matches = []
    for observed in requests:
        r = _mapping(observed)
        meta = _mapping(r["metadata"])
        if (
            not meta.get("deletionTimestamp")
            and _mapping(meta.get("annotations", {}))["cert-manager.io/certificate-revision"]
            == str(revision)
            and any(
                _mapping(owner).get("controller") is True
                and _mapping(owner)["apiVersion"] == "cert-manager.io/v1"
                and _mapping(owner)["kind"] == "Certificate"
                and _mapping(owner)["uid"] == uid
                and _mapping(owner)["name"] == _mapping(cert["metadata"])["name"]
                for owner in _items(meta.get("ownerReferences", []))
            )
            and _mapping(r["spec"])["issuerRef"] == _mapping(_mapping(cert["spec"])["issuerRef"])
            and any(
                _mapping(condition)["type"] == "Ready" and _mapping(condition)["status"] == "True"
                for condition in _items(_mapping(r["status"])["conditions"])
            )
        ):
            matches.append(r)
    (req,) = matches
    return _text(_mapping(req["spec"])["username"])


def main() -> int:
    """Summarize the direct binding subjects of one freshly requested certificate."""
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
            cast("tuple[str, str]", tuple(row.split()))
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
    except (RuntimeError, subprocess.SubprocessError, OSError, KeyError, ValueError, TypeError):
        parser.exit(1, "Incomplete metadata observation; no writer assessment.\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
