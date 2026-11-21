#!/usr/bin/env python3
"""Inventory-driven existing-cluster NetBird onboarding. Plan by default; workloads exclusively owned by Argo CD.

Run on the trusted K3s controller. Never log API bodies, credentials or subprocess
output. Persistent cluster/node/PVC/deployment/peer bindings prohibit replacement
or re-enrollment by friendly name. Uncertain writes stop for operator inspection.
"""

import argparse
import fcntl
import ipaddress
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import override

NS = "netbird-host-peers"
ADMIN = "netbird-internal-admins"
DEST = "netbird-node-agents"
NETWORK = "wireguard-internal"
SERVICE = "homelab-netbird-node-automation"
BASE = "https://netbird.socrat.alchemmist.xyz/api/"


def as_str(value: object) -> str:
    """Return a string JSON value, failing loudly on malformed structure."""
    if not isinstance(value, str):
        error = "string JSON value required"
        raise TypeError(error)
    return value


def require(ok: object, message: str) -> None:
    if not ok:
        raise ValueError(message)


def atomic(path: Path, value: object) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def validate_config(c: Mapping[str, object]) -> Mapping[str, object]:
    image = as_str(c["image"])
    require(
        re.fullmatch(r"netbirdio/netbird:0\.82\.0@sha256:[a-f0-9]{64}", image) is not None,
        "pinned client required",
    )
    nodes = as_record(c["nodes"])
    require(bool(nodes), "inventory nodes required")
    ips: list[str] = []
    for name, value in nodes.items():
        require(
            re.fullmatch(r"socrat-[0-9]+", as_str(name)) is not None, "invalid inventory node name"
        )
        if isinstance(value, (str, int)):
            ip = ipaddress.ip_address(value)
        else:
            error = "WG host address must be a string"
            raise TypeError(error)
        require(
            ip.version == 4
            and ip in ipaddress.ip_network("10.250.0.0/24")
            and int(str(ip).split(".")[-1]) not in (0, 255),
            "explicit WG host address required",
        )
        ips.append(str(ip))
    require(len(ips) == len(set(ips)), "duplicate WG addresses")
    reserved_list = as_list(c.get("reserved_addresses"))
    reserved: set[str] = set()
    for v in reserved_list:
        if not isinstance(v, (str, int)):
            error = "reserved WG address must be a string or int"
            raise TypeError(error)
        reserved.add(str(ipaddress.ip_address(v)))
    require(not set(ips) & reserved, "node address collides with a human/device WG client")
    kernel_only_nodes = as_list(c.get("kernel_only_nodes", []))
    require(
        {str(v) for v in kernel_only_nodes} <= {str(k) for k in nodes},
        "kernel-only nodes must be admitted inventory nodes",
    )
    return c


def manifests(
    host: str, image: str, *, enrollment: bool = False, kernel_only: bool = False
) -> list[dict[str, object]]:
    require(re.fullmatch(r"socrat-[0-9]+", host) is not None, "invalid node")
    name = "machine-" + host
    labels = {"app": name}
    env = {
        "NB_MANAGEMENT_URL": BASE[:-5],
        "NB_HOSTNAME": name,
        "NB_INTERFACE_NAME": "nb-host",
        "NB_WIREGUARD_PORT": "51871",
        "NB_DISABLE_CLIENT_ROUTES": "true",
        "NB_DISABLE_SERVER_ROUTES": "false",
        "NB_DISABLE_DNS": "true",
        "NB_DISABLE_IPV6": "true",
        "NB_DISABLE_FIREWALL": "false",
        "NB_ALLOW_SERVER_SSH": "false",
        "NB_CONFIG": "/etc/netbird/config.json",
        "NB_LOG_LEVEL": "warn",
        "NB_LOG_FILE": "/dev/null",
        "NB_ENABLE_CAPTURE": "false",
    }
    container_env: list[dict[str, object]] = [{"name": k, "value": v} for k, v in env.items()]
    volume_mounts: list[dict[str, object]] = [
        {"name": "state", "mountPath": "/etc/netbird"},
        {"name": "tun", "mountPath": "/dev/net/tun"},
    ]
    container = {
        "name": "peer",
        "image": image,
        "env": container_env,
        "resources": {
            "requests": {"memory": "32Mi", "cpu": "10m"},
            "limits": {"memory": "96Mi", "cpu": "500m"},
        },
        "securityContext": {
            "runAsUser": 0,
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"], "add": ["NET_ADMIN", "NET_RAW", "BPF"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "volumeMounts": volume_mounts,
    }
    if kernel_only:
        # A fresh Docker entrypoint starts an interactive SSO `up` and races
        # the one-off controller enrollment. Run only the service daemon.
        container["command"] = ["netbird"]
        container["args"] = ["service", "run"]
        volume_mounts[:] = [v for v in volume_mounts if v["name"] != "tun"]
    if enrollment:
        container_env.append(
            {
                "name": "NB_SETUP_KEY",
                "valueFrom": {"secretKeyRef": {"name": name + "-enrollment", "key": "setup-key"}},
            }
        )
    tolerations: list[dict[str, object]] = [
        {
            "key": "homelab.io/bootstrap",
            "operator": "Equal",
            "value": "true",
            "effect": "NoSchedule",
        }
    ]
    volumes: list[dict[str, object]] = [
        {"name": "state", "persistentVolumeClaim": {"claimName": name}},
        {
            "name": "tun",
            "hostPath": {"path": "/dev/net/tun", "type": "CharDevice"},
        },
    ]
    pod_spec: dict[str, object] = {
        "hostNetwork": True,
        "dnsPolicy": "ClusterFirstWithHostNet",
        "automountServiceAccountToken": False,
        "nodeSelector": {"kubernetes.io/hostname": host},
        "tolerations": tolerations,
        "containers": [container],
        "volumes": volumes,
    }
    documents: list[dict[str, object]] = [
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": name, "namespace": NS},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "local-path",
                "resources": {"requests": {"storage": "64Mi"}},
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": NS},
            "spec": {
                "replicas": 1,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": pod_spec,
                },
            },
        },
    ]

    if kernel_only:
        volumes[:] = [v for v in volumes if v["name"] != "tun"]
        tolerations.append(
            {
                "key": "homelab.io/no-nfs",
                "operator": "Equal",
                "value": "true",
                "effect": "NoSchedule",
            }
        )
    return documents


def policy_body(source: object, resource: object) -> dict[str, object]:
    name = "admin-wg-" + str(resource)
    return {
        "name": name,
        "enabled": True,
        "description": "Inventory node /32; native SSH authentication still required",
        "rules": [
            {
                "name": "admin-to-wg-node",
                "enabled": True,
                "action": "accept",
                "protocol": "all",
                "bidirectional": False,
                "sources": [source],
                "destinationResource": {"id": resource, "type": "host"},
            }
        ],
    }


def as_record(value: object) -> dict[str, object]:
    """Return a JSON object record, failing loudly on malformed structure."""
    if not isinstance(value, dict):
        error = "structured JSON record required"
        raise TypeError(error)
    return value


def as_list(value: object) -> list[object]:
    """Return a JSON array, failing loudly on malformed structure."""
    if not isinstance(value, list):
        error = "structured JSON array required"
        raise TypeError(error)
    return value


def member_ids(group: Mapping[str, object]) -> set[object]:
    peer_list = group.get("peers")
    return {
        p["id"] if isinstance(p, dict) else p
        for p in (as_list(peer_list) if peer_list is not None else [])
    }


def unique(items: Iterable[Mapping[str, object]], key: str, value: object) -> Mapping[str, object]:
    found = [v for v in items if v.get(key) == value]
    require(len(found) == 1, "missing or ambiguous " + key)
    return found[0]


def policy_ok(
    p: Mapping[str, object],
    admin: object,
    resource: object | None = None,
    group: object | None = None,
) -> bool:
    rules = p.get("rules")
    if not p.get("enabled") or not isinstance(rules, list) or len(rules) != 1:
        return False
    r = rules[0]
    src = {v["id"] if isinstance(v, dict) else v for v in (r.get("sources") or [])}
    dst = {v["id"] if isinstance(v, dict) else v for v in (r.get("destinations") or [])}
    return bool(
        r.get("enabled")
        and r.get("action") == "accept"
        and r.get("protocol") == "all"
        and r.get("bidirectional") is False
        and not r.get("ports")
        and src == {admin}
        and as_record(r.get("destinationResource") or {}).get("id") == resource
        and (resource is None or as_record(r["destinationResource"]).get("type") == "host")
        and dst == ({group} if group is not None else set())
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    @override
    def redirect_request(self, *a: object, **kw: object) -> urllib.request.Request | None:
        return None


class Runtime:
    def __init__(self, folder: Path, config: Mapping[str, object], *, apply: bool = False) -> None:
        self.folder, self.config, self.apply = folder, validate_config(config), apply
        self.k = [
            "env",
            "K3S_CONFIG_FILE=/dev/null",
            "kubectl",
            "--kubeconfig",
            "/etc/rancher/k3s/k3s.yaml",
        ]
        require(folder.stat().st_uid == os.geteuid(), "state directory owner mismatch")
        self.auth_path = folder / "credential.json"
        require(not self.auth_path.is_symlink(), "credential symlink refused")
        self.auth = json.loads(self.auth_path.read_text())
        require(not self.auth_path.stat().st_mode & 0o077, "credential permissions")
        self.state_path = folder / "bindings.json"
        require(not self.state_path.is_symlink(), "bindings symlink refused")
        self.state = (
            json.loads(self.state_path.read_text()) if self.state_path.exists() else {"nodes": {}}
        )
        require(
            not self.state.get("pending"),
            "uncertain previous write: inspect private bindings; no blind replay",
        )
        self.changed = False

    def api(self, method: str, path: str, body: object | None = None) -> object | None:
        req = urllib.request.Request(
            BASE + path,
            method=method,
            headers={
                "Authorization": "Token " + self.auth["token"],
                "Content-Type": "application/json",
            },
            data=None if body is None else json.dumps(body).encode(),
        )
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
            b = response.read()
            return json.loads(b) if b else None

    def kub(
        self,
        args: Sequence[str],
        obj: Mapping[str, object] | None = None,
        *,
        optional: bool = False,
        stdin: bytes | None = None,
    ) -> bytes:
        args = list(args)
        operation = args[2] if args[:1] == ["-n"] else args[0]
        require(
            operation in ("get", "exec", "wait", "rollout", "delete"),
            "Kubernetes deployment mutations are exclusive to Argo CD",
        )
        if operation == "rollout":
            require(
                (args[2:] if args[:1] == ["-n"] else args)[1] == "status",
                "only read-only rollout status is permitted",
            )
        if operation == "delete":
            preconditions = obj.get("preconditions", {}) if obj is not None else {}
            if not (
                args[:2] == ["delete", "--raw"]
                and args[2].startswith("/api/v1/namespaces/" + NS + "/pods/")
                and obj is not None
                and obj.get("kind") == "DeleteOptions"
                and isinstance(preconditions, dict)
                and bool(preconditions.get("uid"))
                and bool(preconditions.get("resourceVersion"))
            ):
                error = "only UID-bound operational pod restart is permitted"
                raise ValueError(error)
        if optional:
            args += ["--ignore-not-found"]
        p = subprocess.run(
            self.k + args,
            input=stdin
            if stdin is not None
            else (None if obj is None else json.dumps(obj).encode()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
        )
        require(
            p.returncode == 0,
            "Kubernetes operation failed; inspect locally without dumping secrets",
        )
        return p.stdout

    def get(self, kind: str, name: str, ns: str = NS, *, optional: bool = False) -> object | None:
        out = self.kub(["-n", ns, "get", kind, name, "-o", "json"], optional=optional)
        return json.loads(out) if out.strip() else None

    def save(self) -> None:
        atomic(self.state_path, self.state)

    def write(self, method: str, path: str, body: object | None = None) -> object | None:
        require(self.apply, "plan attempted mutation")
        require(not self.state.get("pending"), "uncertain previous write")
        self.state["pending"] = {"method": method, "path": path}
        self.save()
        response = self.api(method, path, body)
        del self.state["pending"]
        self.save()
        self.changed = True
        return response

    @staticmethod
    def require_argocd(obj: object) -> None:
        meta = as_record(as_record(obj)["metadata"])
        annotations = as_record(meta.get("annotations", {}))
        labels = as_record(meta.get("labels", {}))
        require(
            str(annotations.get("argocd.argoproj.io/tracking-id", "")).startswith("netbird:")
            or labels.get("app.kubernetes.io/instance") == "netbird",
            "workload/PVC must already be owned by the root-managed netbird Argo CD Application",
        )

    def restart_without_key(self, host: str, deployment: Mapping[str, object]) -> None:
        # Operational acceptance restart only: never edit/create a workload spec.
        pods = json.loads(
            self.kub(["-n", NS, "get", "pods", "-l", "app=machine-" + host, "-o", "json"])
        )["items"]
        require(len(pods) == 1, "ambiguous agent pod; no restart")
        pod = pods[0]
        owners = pod["metadata"].get("ownerReferences", [])
        require(
            len(owners) == 1 and owners[0]["kind"] == "ReplicaSet" and owners[0].get("controller"),
            "unexpected agent pod owner",
        )
        rs = self.get("replicaset", owners[0]["name"])
        rs_meta = as_record(as_record(rs)["metadata"])
        deployment_uid = as_record(deployment["metadata"])["uid"]
        require(
            rs_meta["uid"] == owners[0]["uid"]
            and any(
                isinstance(v, dict)
                and v.get("kind") == "Deployment"
                and v.get("uid") == deployment_uid
                and v.get("controller")
                for v in as_list(rs_meta.get("ownerReferences", []))
            ),
            "pod/deployment UID binding changed",
        )
        self.kub(
            [
                "delete",
                "--raw",
                "/api/v1/namespaces/" + NS + "/pods/" + pod["metadata"]["name"],
                "-f",
                "-",
            ],
            {
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "preconditions": {
                    "uid": pod["metadata"]["uid"],
                    "resourceVersion": pod["metadata"]["resourceVersion"],
                },
            },
        )
        self.kub(
            ["-n", NS, "wait", "--for=delete", "pod/" + pod["metadata"]["name"], "--timeout=90s"]
        )
        self.kub(["-n", NS, "rollout", "status", "deployment/machine-" + host, "--timeout=120s"])
        self.kub(
            [
                "-n",
                NS,
                "exec",
                "deployment/machine-" + host,
                "--",
                "sh",
                "-c",
                "timeout 45 netbird status --check ready",
            ]
        )

    def enroll_argocd_agent(
        self,
        host: str,
        node: Mapping[str, object],
        deployment: Mapping[str, object],
        pvc: Mapping[str, object],
    ) -> tuple[Mapping[str, object], Mapping[str, object]] | None:
        self.require_argocd(deployment)
        self.require_argocd(pvc)
        peers = self.api("GET", "peers")
        require(
            not any(
                isinstance(p, dict)
                and (p.get("hostname") == host or p.get("name") == "machine-" + host)
                for p in as_list(peers if peers is not None else [])
            ),
            "orphan existing peer: no name adoption",
        )
        raw = json.loads(
            self.kub(
                [
                    "-n",
                    NS,
                    "exec",
                    "deployment/machine-" + host,
                    "--",
                    "netbird",
                    "status",
                    "--json",
                ]
            )
        )
        require(
            raw.get("daemonStatus") == "NeedsLogin" and not raw.get("netbirdIp"),
            "only a fresh unregistered Argo CD agent can be enrolled; never reset an identity",
        )
        if not self.apply:
            return None
        self.state["nodes"][host] = {
            "phase": "enrolling",
            "node_uid": as_record(node["metadata"])["uid"],
            "address": as_record(self.config["nodes"])[host],
            "deployment_uid": as_record(deployment["metadata"])["uid"],
            "pvc_uid": as_record(pvc["metadata"])["uid"],
        }
        self.save()
        key = as_record(
            self.write(
                "POST",
                "setup-keys",
                {
                    "name": "inventory-" + host,
                    "type": "one-off",
                    "expires_in": 600,
                    "usage_limit": 1,
                    "auto_groups": [],
                    "ephemeral": False,
                    "allow_extra_dns_labels": False,
                },
            )
        )
        self.state["nodes"][host]["setup_key_id"] = key["id"]
        self.save()
        try:
            # v0.82 reads --setup-key-file using os.ReadFile. Send bytes over the
            # authenticated exec stdin stream, never argv, env, Git or a Secret.
            self.kub(
                [
                    "-n",
                    NS,
                    "exec",
                    "-i",
                    "deployment/machine-" + host,
                    "--",
                    "netbird",
                    "up",
                    "--setup-key-file",
                    "/dev/stdin",
                ],
                stdin=str(key["key"]).encode(),
            )
            self.kub(
                [
                    "-n",
                    NS,
                    "exec",
                    "deployment/machine-" + host,
                    "--",
                    "sh",
                    "-c",
                    "timeout 45 netbird status --check ready",
                ]
            )
            peer, status = self.peer_for_status(host)
        finally:
            self.state["cleanup"] = {"setup_key_id": key["id"], "node": host, "revoked": False}
            self.save()
            retired = as_record(
                self.api(
                    "PUT", "setup-keys/" + str(key["id"]), {"revoked": True, "auto_groups": []}
                )
            )
            require(bool(retired["revoked"]), "setup-key retirement failed")
            self.state["cleanup"]["revoked"] = True
            self.save()
        self.restart_without_key(host, deployment)
        again, second = self.peer_for_status(host)
        require(
            bool(peer["id"] == again["id"] and status == second),
            "identity changed on key-free restart",
        )
        require(
            as_record(as_record(self.get("deployment", "machine-" + host))["metadata"])["uid"]
            == as_record(deployment["metadata"])["uid"]
            and as_record(as_record(self.get("pvc", "machine-" + host))["metadata"])["uid"]
            == as_record(pvc["metadata"])["uid"],
            "Argo CD workload or storage replaced during enrollment",
        )
        return peer, status

    def guard(self) -> list[dict[str, object]]:
        app = as_record(self.get("application", "netbird", ns="argocd"))
        spec = as_record(app["spec"])
        source = as_record(spec.get("source", {}))
        meta = as_record(app["metadata"])
        annotations = as_record(meta.get("annotations", {}))
        labels = as_record(meta.get("labels", {}))
        require(
            spec.get("project") == "default"
            and source.get("path") == "charts/netbird"
            and source.get("targetRevision") == "main"
            and source.get("repoURL") == "https://github.com/alchemmist/homelab.git"
            and (
                str(annotations.get("argocd.argoproj.io/tracking-id", "")).startswith("root:")
                or labels.get("app.kubernetes.io/instance") == "root"
            ),
            "root-managed GitOps Application required; do not create one manually",
        )
        groups = self.api("GET", "groups")
        group_records = [as_record(g) for g in as_list(groups if groups is not None else [])]
        self.admin = unique(group_records, "name", ADMIN)
        self.group = unique(group_records, "name", DEST)
        require(
            self.admin["issued"] == "jwt" and not bool(self.admin.get("resources")),
            "real JWT admin source required",
        )
        require(
            self.group["issued"] == "api" and not bool(self.group.get("resources")),
            "dedicated machine destinations required",
        )
        network_list = self.api("GET", "networks")
        net = unique(
            [as_record(x) for x in as_list(network_list if network_list is not None else [])],
            "name",
            NETWORK,
        )
        self.network = str(net["id"])
        router_list = as_list(self.api("GET", "networks/" + self.network + "/routers"))
        require(len(router_list) == 1, "single native router required")
        router = as_record(router_list[0])
        require(
            not bool(router.get("peer"))
            and router.get("peer_groups") == [self.group["id"]]
            and bool(router.get("enabled"))
            and bool(router.get("masquerade"))
            and router.get("metric") == 80,
            "native group-router drift",
        )
        cluster = as_record(
            as_record(self.get("namespace", "kube-system", ns="default"))["metadata"]
        )["uid"]
        namespace = as_record(as_record(self.get("namespace", NS, ns="default"))["metadata"])["uid"]
        binding = {
            "cluster_uid": cluster,
            "namespace_uid": namespace,
            "network_id": self.network,
            "router_id": router["id"],
            "admin_id": self.admin["id"],
            "group_id": self.group["id"],
        }
        require(
            self.state.get("scope", binding) == binding, "cluster/account/scope binding changed"
        )
        self.state["scope"] = binding
        policies = self.api("GET", "policies")
        policy_list = [as_record(p) for p in as_list(policies if policies is not None else [])]
        all_id = unique(group_records, "name", "All")["id"]
        for policy in policy_list:
            for rule in [as_record(r) for r in as_list(policy.get("rules", []))]:
                sources = rule.get("sources")
                destinations = rule.get("destinations")
                if (
                    bool(policy.get("enabled"))
                    and bool(rule.get("enabled"))
                    and rule.get("action") == "accept"
                ):
                    endpoints = as_list(sources if sources is not None else []) + as_list(
                        destinations if destinations is not None else []
                    )
                    require(
                        all_id not in {g["id"] if isinstance(g, dict) else g for g in endpoints},
                        "All-device grant violates enrollment default deny",
                    )
        require(
            any(policy_ok(p, self.admin["id"], group=self.group["id"]) for p in policy_list),
            "admin own-node INPUT policy missing or broadened",
        )
        return policy_list

    def status(self, host: str) -> dict[str, object]:
        value = json.loads(
            self.kub(
                [
                    "-n",
                    NS,
                    "exec",
                    "deployment/machine-" + host,
                    "--",
                    "netbird",
                    "status",
                    "--json",
                ]
            )
        )
        require(value["daemonStatus"] == "Connected", "agent not connected")
        return {"ip": str(ipaddress.ip_interface(value["netbirdIp"]).ip), "key": value["publicKey"]}

    def peer_for_status(self, host: str) -> tuple[Mapping[str, object], Mapping[str, object]]:
        status = self.status(host)
        peers = self.api("GET", "peers")
        p = unique(
            [as_record(x) for x in as_list(peers if peers is not None else [])],
            "ip",
            status["ip"],
        )
        require(
            bool(p["connected"])
            and not bool(p["user_id"])
            and not bool(p["approval_required"])
            and not bool(p["login_expired"])
            and bool(p["hostname"])
            and p["name"] == "machine-" + host,
            "machine peer identity/admission mismatch",
        )
        return p, status

    def verify_deployment(self, host: str, d: Mapping[str, object]) -> None:
        kernel_only_nodes = self.config.get("kernel_only_nodes", [])
        expected = manifests(
            host,
            str(self.config["image"]),
            kernel_only=host in as_list(kernel_only_nodes if kernel_only_nodes is not None else []),
        )[1]
        spec = as_record(as_record(as_record(d["spec"])["template"])["spec"])
        want = as_record(as_record(as_record(expected["spec"])["template"])["spec"])
        containers = as_list(spec.get("containers"))
        want_containers = as_list(want.get("containers"))
        require(
            as_record(d["spec"]).get("replicas") == 1
            and spec.get("nodeSelector") == want.get("nodeSelector")
            and bool(spec.get("hostNetwork"))
            and spec.get("automountServiceAccountToken") is False
            and len(containers) == 1,
            "agent placement/config drift",
        )
        c, wc = as_record(containers[0]), as_record(want_containers[0])
        require(
            c.get("image") == wc.get("image")
            and c.get("env") == wc.get("env")
            and c.get("volumeMounts") == wc.get("volumeMounts")
            and c.get("securityContext") == wc.get("securityContext"),
            "agent image/env/security drift",
        )
        require(spec.get("volumes") == want.get("volumes"), "persistent identity volumes drift")

    def reconcile(self, host: str, seed: Mapping[str, object] | None = None) -> dict[str, object]:
        inventory_nodes = as_record(self.config["nodes"])
        require(host in inventory_nodes, "host not enabled in inventory")
        policies = self.guard()
        known = {v["peer_id"] for v in self.state["nodes"].values() if v.get("peer_id")}
        seed_nodes = as_record(seed.get("nodes", {})) if seed is not None else {}
        known |= {v["id"] for v in (as_record(x) for x in seed_nodes.values()) if v.get("id")}
        require(
            member_ids(self.group) <= known,
            "unbound machine-group member: explicit initial adoption required",
        )
        node = self.get("node", host, ns="default", optional=True)
        deferred = {"changed": False, "status": "deferred-node-not-ready", "node": host}
        if node is None:
            return deferred
        node_record = as_record(node)
        node_status = node_record.get("status", {})
        conditions = as_record(node_status if node_status is not None else {}).get("conditions", [])
        if not any(
            isinstance(c, dict) and c.get("type") == "Ready" and c.get("status") == "True"
            for c in as_list(conditions if conditions is not None else [])
        ):
            return deferred
        address = inventory_nodes[host]
        entry = self.state["nodes"].get(host)
        if entry:
            require(
                entry["phase"] == "ready",
                "incomplete enrollment: inspect private state, never reissue automatically",
            )
            require(
                entry["node_uid"] == as_record(node_record["metadata"])["uid"]
                and entry["address"] == address,
                "node reinstallation/address change requires explicit retirement",
            )
        d = self.get("deployment", "machine-" + host, optional=True)
        pvc = self.get("pvc", "machine-" + host, optional=True)
        if d is not None or pvc is not None:
            if not isinstance(d, dict) or not isinstance(pvc, dict):
                error = "partial/missing identity storage: refuse replacement"
                raise ValueError(error)
            self.require_argocd(d)
            self.require_argocd(pvc)
            self.verify_deployment(host, d)
            if entry or seed_nodes.get(host):
                p, status = self.peer_for_status(host)
                if not entry:
                    require(
                        as_record(seed_nodes[host]).get("id") == p["id"],
                        "trusted migration binding mismatch",
                    )
            else:
                enrolled = self.enroll_argocd_agent(host, node_record, d, pvc)
                if enrolled is None:
                    return {
                        "changed": False,
                        "status": "would-enroll-and-authorize",
                        "node": host,
                    }
                p, status = enrolled
        else:
            require(
                entry is None and not seed_nodes.get(host),
                "lost identity storage: no re-enrollment",
            )
            peers = self.api("GET", "peers")
            require(
                not any(
                    isinstance(q, dict)
                    and (q.get("hostname") == host or q.get("name") == "machine-" + host)
                    for q in as_list(peers if peers is not None else [])
                ),
                "orphan existing peer: no name adoption",
            )
            return {"changed": False, "status": "awaiting-argocd-workloads", "node": host}
        binding = {
            "phase": "ready",
            "node_uid": as_record(node_record["metadata"])["uid"],
            "address": address,
            "deployment_uid": as_record(as_record(d)["metadata"])["uid"],
            "pvc_uid": as_record(as_record(pvc)["metadata"])["uid"],
            "peer_id": p["id"],
            "ip": status["ip"],
            "public_key": status["key"],
        }
        require(entry is None or entry == binding, "persistent node/peer identity drift")
        require(
            entry is None or p["id"] in member_ids(self.group),
            "bound node removed from destination group; no automatic regrant",
        )
        local = json.loads(
            self.kub(
                [
                    "-n",
                    NS,
                    "exec",
                    "deployment/machine-" + host,
                    "--",
                    "ip",
                    "-j",
                    "address",
                    "show",
                    "dev",
                    "wg-socrat",
                ]
            )
        )
        require(
            any(a.get("local") == address for i in local for a in i.get("addr_info", [])),
            "inventory WG address is not on the actual node",
        )
        # Only Ready targets are required: an offline node is not mistaken for a broken mesh.
        nodes = json.loads(self.kub(["get", "nodes", "-o", "json"]))["items"]
        ready = {
            n["metadata"]["name"]
            for n in nodes
            if any(
                c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"]
            )
        }
        if p["id"] not in member_ids(self.group):
            for h in sorted(ready & inventory_nodes.keys()):
                self.kub(
                    [
                        "-n",
                        NS,
                        "exec",
                        "deployment/machine-" + host,
                        "--",
                        "ping",
                        "-n",
                        "-c",
                        "1",
                        "-W",
                        "3",
                        str(inventory_nodes[h]),
                    ]
                )
        resources_path = "networks/" + self.network + "/resources"
        resources = self.api("GET", resources_path)
        found = [
            as_record(r)
            for r in as_list(resources if resources is not None else [])
            if as_record(r).get("address") == str(address) + "/32"
        ]
        require(len(found) <= 1, "duplicate WG host resources")
        resource = found[0] if found else None
        if resource:
            require(
                resource.get("name") == "wg-" + host
                and bool(resource.get("enabled"))
                and resource.get("type") == "host"
                and not bool(resource.get("groups")),
                "existing resource scope drift",
            )
        matching: list[Mapping[str, object]] = []
        if resource:
            matching = [
                v
                for v in policies
                if any(
                    as_record(
                        r.get("destinationResource")
                        if r.get("destinationResource") is not None
                        else {}
                    ).get("id")
                    == resource["id"]
                    for r in [as_record(x) for x in as_list(v.get("rules", []))]
                )
                and str(v["name"]).startswith("admin-wg-")
            ]
            require(len(matching) <= 1, "duplicate managed resource policies")
            if matching:
                require(
                    policy_ok(matching[0], self.admin["id"], resource=resource["id"]),
                    "admin resource policy drift",
                )
        grant = self.state.get("grants", {}).get(host)
        if grant:
            require(
                resource is not None
                and resource.get("id") == grant["resource_id"]
                and bool(matching)
                and matching[0].get("id") == grant["policy_id"],
                "managed grant removed/replaced: explicit review required, no resurrection",
            )
        elif entry:
            seed_entry = seed_nodes.get(host, {}) if seed is not None else {}
            require(
                seed is not None
                and as_record(seed_entry).get("id") == p["id"]
                and bool(resource)
                and bool(matching),
                "legacy binding needs explicit grant-ID migration",
            )
        if self.apply:
            self.state["nodes"][host] = dict(binding, phase="admitting")
            self.save()
            if entry is None or grant is None:
                self.changed = True
            if p["id"] not in member_ids(self.group):
                fresh = as_record(self.api("GET", "groups/" + str(self.group["id"])))
                require(
                    member_ids(fresh) == member_ids(self.group)
                    and not bool(fresh.get("resources"))
                    and fresh["issued"] == "api"
                    and fresh["name"] == DEST,
                    "concurrent machine-group change",
                )
                self.write(
                    "PUT",
                    "groups/" + str(self.group["id"]),
                    {
                        "name": DEST,
                        "resources": [],
                        "peers": sorted(str(x) for x in member_ids(self.group) | {p["id"]}),
                    },
                )
            if resource is None:
                resource = as_record(
                    self.write(
                        "POST",
                        resources_path,
                        {
                            "name": "wg-" + host,
                            "description": "Inventory WG node; no broader prefix",
                            "address": str(address) + "/32",
                            "enabled": True,
                        },
                    )
                )
        if self.apply:
            if resource is None:
                error = "WG resource missing after plan/apply critical section"
                raise ValueError(error)
            if not matching:
                matching = [
                    as_record(
                        self.write(
                            "POST", "policies", policy_body(self.admin["id"], resource["id"])
                        )
                    )
                ]
            self.state.setdefault("grants", {})[host] = {
                "resource_id": resource["id"],
                "policy_id": matching[0].get("id"),
            }
            self.state["nodes"][host] = binding
            self.save()
        return {
            "changed": self.changed,
            "status": "ready" if self.apply else "validated-plan",
            "node": host,
        }


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--node")
    parser.add_argument("--adopt-state", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    folder = args.state_dir
    require(
        folder.is_dir() and not folder.is_symlink() and not folder.stat().st_mode & 0o077,
        "private state directory required",
    )
    with (folder / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        c = json.loads(args.config.read_text())
        runtime = Runtime(folder, c, apply=args.apply)
        seed = json.loads(args.adopt_state.read_text()) if args.adopt_state else None
        require(args.node is not None, "explicit selected inventory node required")
        print(json.dumps(runtime.reconcile(args.node, seed)))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(e).__name__,
                    "reason": str(e)
                    if isinstance(e, ValueError)
                    else "inspect private state; output intentionally redacted",
                }
            )
        )
        sys.exit(1)
