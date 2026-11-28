"""Direct writer-grant reporting must stay positive-only and identity-free."""

from collections.abc import Sequence
from typing import cast

import pytest

from ci.quality.public_tls_writer_grants import grants
from ci.quality.public_tls_writer_triage import _SubjectObservation, requester_for, summarize


def obj(kind: str, name: str, ns: str | None = None, **fields: object) -> dict[str, object]:
    """Build one literal RBAC object body for a grant fixture."""
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": kind,
        "metadata": {"name": name, **({"namespace": ns} if ns else {})},
        **fields,
    }


def fixture(
    names: Sequence[str], namespace: str = "school"
) -> tuple[dict[str, object], dict[str, object]]:
    """Build a pinned ClusterRole and its RoleBinding with the given Secret names."""
    role = obj(
        "ClusterRole",
        "operator",
        rules=[
            {
                "apiGroups": ["*"],
                "resources": ["secrets"],
                "verbs": ["*"],
                "resourceNames": names,
            }
        ],
    )
    binding = obj(
        "RoleBinding",
        "editor",
        namespace,
        roleRef={
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "operator",
        },
        subjects=[{"kind": "Group", "name": "operators"}],
    )
    return role, binding


def test_cluster_role_obeys_binding_namespace_and_named_verb_limits() -> None:
    role, b = fixture(["pin"])
    (r,) = grants("school", "pin", [role, b])
    assert r["verbs"] == ["delete", "patch", "update"]
    assert not grants("school", "other", [role, b])
    assert not grants("different", "pin", [role, b])
    role, b = fixture([])
    (r,) = grants("school", "pin", [role, b])
    assert {"create", "deletecollection"} <= set(r["verbs"])
    b["kind"] = "ClusterRoleBinding"
    del cast("dict[str, object]", b["metadata"])["namespace"]
    (r,) = grants("different", "pin", [b, role])
    assert r["binding"] == ["ClusterRoleBinding", None, "editor"]
    with pytest.raises(ValueError, match="incomplete"):
        grants("school", "pin", [b])


def test_local_role_cannot_be_resolved_from_another_namespace() -> None:
    role, b = fixture([])
    cast("dict[str, object]", b["roleRef"])["kind"] = "Role"
    role["kind"] = "Role"
    cast("dict[str, object]", role["metadata"])["namespace"] = "other"
    with pytest.raises(ValueError, match="incomplete"):
        grants("school", "pin", [role, b])
    cast("dict[str, object]", role["metadata"])["namespace"] = "school"
    cast("list[dict[str, object]]", role["rules"])[0]["verbs"] = ["get", "list", "watch"]
    assert not grants("school", "pin", [role, b])


def test_report_deduplicates_verb_union_without_revealing_names() -> None:
    local: dict[str, object] = {"kind": "ServiceAccount", "name": "private-subject"}
    group: dict[str, object] = {"kind": "Group", "name": "system:authenticated"}
    rows: list[_SubjectObservation] = [
        {
            "binding": ["RoleBinding", "school", "one"],
            "subjects": [local, group],
            "verbs": ["patch"],
        },
        {
            "binding": ["RoleBinding", "school", "two"],
            "subjects": [dict(local, namespace="school")],
            "verbs": ["update", "patch"],
        },
    ]
    report = summarize(
        rows,
        {("school", "private-subject")},
        "system:serviceaccount:school:private-subject",
    )
    assert report["subjectClasses"] == {
        "serviceAccountWithRunningPod": 1,
        "clusterWideBuiltinGroup": 1,
    }
    assert report["descriptorsByVerb"] == {"patch": 2, "update": 1}
    assert report["requesterDirectServiceAccountVerbs"] == ["patch", "update"]
    assert not report["writerApproved"]
    assert "private-subject" not in str(report)
    quiet = summarize(rows, set(), "system:serviceaccount:other:private-subject")[
        "requesterDirectServiceAccountVerbs"
    ]
    assert not quiet
    unscoped = dict(rows[0], binding=["ClusterRoleBinding", None, "one"])
    with pytest.raises(ValueError, match="unscoped"):
        summarize([cast("_SubjectObservation", unscoped)], set(), "")


def test_requester_requires_unique_current_owned_revision() -> None:
    cert: dict[str, object] = {
        "metadata": {"uid": "new", "name": "cert", "generation": 2},
        "spec": {"secretName": "pin", "issuerRef": {"name": "issuer"}},
        "status": {
            "revision": 3,
            "conditions": [{"type": "Ready", "status": "True", "observedGeneration": 2}],
        },
    }
    owner = {
        "kind": "Certificate",
        "apiVersion": "cert-manager.io/v1",
        "name": "cert",
        "controller": True,
        "uid": "new",
    }
    req: dict[str, object] = {
        "metadata": {
            "ownerReferences": [owner],
            "annotations": {"cert-manager.io/certificate-revision": "3"},
        },
        "spec": {"issuerRef": {"name": "issuer"}, "username": "fixture"},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }
    assert requester_for("pin", [cert], [req]) == "fixture"
    stale_owner = dict(
        req,
        metadata=dict(
            cast("dict[str, object]", req["metadata"]),
            ownerReferences=[dict(owner, uid="old")],
        ),
    )
    stale_revision = dict(
        req,
        metadata=dict(
            cast("dict[str, object]", req["metadata"]),
            annotations={"cert-manager.io/certificate-revision": "2"},
        ),
    )
    faults: list[tuple[str, Sequence[object], str]] = [
        ("empty request list", [], "not enough values"),
        ("two matching requests", [req, req], "too many values"),
        ("stale owner uid", [stale_owner], "not enough values"),
        ("stale revision", [stale_revision], "not enough values"),
    ]
    for label, candidates, fragment in faults:
        assert label
        with pytest.raises(ValueError, match=fragment):
            requester_for("pin", [cert], candidates)
