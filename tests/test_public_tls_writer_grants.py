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
