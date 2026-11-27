import pytest

from ci.quality.public_tls_writer_grants import grants


def obj(kind, name, ns=None, **fields):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": kind,
        "metadata": {"name": name, **({"namespace": ns} if ns else {})},
        **fields,
    }


def fixture(names, namespace="school"):
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


def test_cluster_role_obeys_binding_namespace_and_named_verb_limits():
    role, b = fixture(["pin"])
    (r,) = grants("school", "pin", [role, b])
    assert r["verbs"] == ["delete", "patch", "update"]
    assert not grants("school", "other", [role, b])
    assert not grants("different", "pin", [role, b])
    role, b = fixture([])
    (r,) = grants("school", "pin", [role, b])
    assert {"create", "deletecollection"} <= set(r["verbs"])
    b["kind"] = "ClusterRoleBinding"
    del b["metadata"]["namespace"]
    (r,) = grants("different", "pin", [b, role])
    assert r["binding"] == ["ClusterRoleBinding", None, "editor"]
    with pytest.raises(ValueError, match="incomplete"):
        grants("school", "pin", [b])


def test_local_role_cannot_be_resolved_from_another_namespace():
    role, b = fixture([])
    b["roleRef"]["kind"] = "Role"
    role["kind"] = "Role"
    role["metadata"]["namespace"] = "other"
    with pytest.raises(ValueError, match="incomplete"):
        grants("school", "pin", [role, b])
    role["metadata"]["namespace"] = "school"
    role["rules"][0]["verbs"] = ["get", "list", "watch"]
    assert not grants("school", "pin", [role, b])


def test_report_deduplicates_verb_union_without_revealing_names():
    from ci.quality.public_tls_writer_triage import summarize

    local = {"kind": "ServiceAccount", "name": "private-subject"}
    group = {"kind": "Group", "name": "system:authenticated"}
    rows = [
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
    assert not report["writerApproved"] and "private-subject" not in str(report)
    assert not summarize(rows, set(), "system:serviceaccount:other:private-subject")[
        "requesterDirectServiceAccountVerbs"
    ]
    with pytest.raises(ValueError, match="unscoped"):
        summarize(
            [dict(rows[0], binding=["ClusterRoleBinding", None, "one"])], set(), ""
        )


def test_requester_requires_unique_current_owned_revision():
    from ci.quality.public_tls_writer_triage import requester_for

    cert = {
        "metadata": {"uid": "new", "name": "cert", "generation": 2},
        "spec": {"secretName": "pin", "issuerRef": {"name": "issuer"}},
        "status": {
            "revision": 3,
            "conditions": [
                {"type": "Ready", "status": "True", "observedGeneration": 2}
            ],
        },
    }
    owner = {
        "kind": "Certificate",
        "apiVersion": "cert-manager.io/v1",
        "name": "cert",
        "controller": True,
        "uid": "new",
    }
    req = {
        "metadata": {
            "ownerReferences": [owner],
            "annotations": {"cert-manager.io/certificate-revision": "3"},
        },
        "spec": {"issuerRef": {"name": "issuer"}, "username": "fixture"},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }
    assert requester_for("pin", [cert], [req]) == "fixture"
    for requests in [
        [],
        [req, req],
        [
            dict(
                req,
                metadata=dict(
                    req["metadata"], ownerReferences=[dict(owner, uid="old")]
                ),
            )
        ],
        [
            dict(
                req,
                metadata=dict(
                    req["metadata"],
                    annotations={"cert-manager.io/certificate-revision": "2"},
                ),
            )
        ],
    ]:
        with pytest.raises(ValueError):
            requester_for("pin", [cert], requests)
