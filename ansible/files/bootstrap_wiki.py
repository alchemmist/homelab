import argparse
import json
import subprocess


def kubectl(*args, payload=None):
    result = subprocess.run(
        ["k3s", "kubectl", *args],
        input=None if payload is None else json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def resource(kind, name, namespace=None, api_version="v1", **fields):
    metadata = {"name": name}
    if namespace:
        metadata["namespace"] = namespace
    return {"apiVersion": api_version, "kind": kind, "metadata": metadata, **fields}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", default="wiki-publish")
    parser.add_argument("--gitrepo-name", default="wiki")
    parser.add_argument("--git-secret", default="")
    parser.add_argument("--registry-secret-namespace", default="blog")
    parser.add_argument("--registry-secret-name", default="ghcr-pull")
    args = parser.parse_args()
    cluster = json.loads(kubectl("-n", "fleet-local", "get", "clusters.fleet.cattle.io", "local", "-o", "json"))
    agent_namespace = cluster["spec"]["agentNamespace"]
    if args.git_secret:
        secret = json.loads(kubectl("-n", "fleet-local", "get", "secret", args.git_secret, "-o", "json"))
        if secret["type"] not in ("kubernetes.io/basic-auth", "kubernetes.io/ssh-auth"):
            raise ValueError("Fleet Git authentication requires a basic-auth or ssh-auth secret")
    registry = json.loads(kubectl("-n", args.registry_secret_namespace, "get", "secret", args.registry_secret_name, "-o", "json"))
    if registry["type"] != "kubernetes.io/dockerconfigjson":
        raise ValueError("The registry source must be a dockerconfigjson secret")
    resources = [
        resource("Namespace", "wiki"),
        resource("ServiceAccount", "wiki-deployer", agent_namespace),
        resource("Role", "wiki-deployer", "wiki", "rbac.authorization.k8s.io/v1", rules=[
            {"apiGroups": [""], "resources": ["secrets", "configmaps", "services", "persistentvolumeclaims"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
            {"apiGroups": [""], "resources": ["pods", "events"], "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["apps"], "resources": ["deployments", "replicasets"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
            {"apiGroups": ["networking.k8s.io"], "resources": ["ingresses", "networkpolicies"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
            {"apiGroups": ["policy"], "resources": ["poddisruptionbudgets"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
        ]),
        resource("RoleBinding", "wiki-deployer", "wiki", "rbac.authorization.k8s.io/v1",
                 roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "wiki-deployer"},
                 subjects=[{"kind": "ServiceAccount", "name": "wiki-deployer", "namespace": agent_namespace}]),
        resource("Secret", "ghcr-pull", "wiki", type=registry["type"], data=registry["data"]),
    ]
    spec = {
        "repo": args.repository,
        "branch": args.branch,
        "paths": ["bundle"],
        "serviceAccount": "wiki-deployer",
        "targetNamespace": "wiki",
        "pollingInterval": "1m",
        "deleteNamespace": False,
        "targets": [{"name": "local", "clusterSelector": {"matchLabels": {"name": "local"}}}],
    }
    if args.git_secret:
        spec["clientSecretName"] = args.git_secret
    resources.append(resource("GitRepo", args.gitrepo_name, "fleet-local", "fleet.cattle.io/v1alpha1", spec=spec))
    for item in resources:
        print(kubectl("apply", "-f", "-", payload=item).strip())


if __name__ == "__main__":
    main()
