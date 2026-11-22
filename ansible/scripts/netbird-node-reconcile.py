#!/usr/bin/env python3
"""Inventory-driven existing-cluster NetBird onboarding. Plan by default; workloads exclusively owned by Argo CD.

Run on the trusted K3s controller. Never log API bodies, credentials or subprocess
output. Persistent cluster/node/PVC/deployment/peer bindings prohibit replacement
or re-enrollment by friendly name. Uncertain writes stop for operator inspection.
"""

import argparse
import fcntl
import http.client
import ipaddress
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import NamedTuple, cast

NS = "netbird-host-peers"
ADMIN = "netbird-internal-admins"
DEST = "netbird-node-agents"
NETWORK = "wireguard-internal"
SERVICE = "homelab-netbird-node-automation"
BASE = "https://netbird.socrat.alchemmist.xyz/api/"


def require(ok: object, message: str) -> None:
    """Stop unless the audited invariant holds."""
    if not ok:
        raise ValueError(message)


def atomic(path, value):
    """Durably write a JSON value to disk via a temporary file and rename."""
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def validate_config(c):
    """Enforce the reviewed image pin and other config invariants."""
    require(
        re.fullmatch(r"netbirdio/netbird:0\.82\.0@sha256:[a-f0-9]{64}", c["image"]),
        "pinned client required",
    )
    require(isinstance(c["nodes"], dict) and c["nodes"], "inventory nodes required")
    ips = []
    for name, value in c["nodes"].items():
        require(re.fullmatch(r"socrat-[0-9]+", name), "invalid inventory node name")
        ip = ipaddress.ip_address(value)
        require(
            ip.version == 4
            and ip in ipaddress.ip_network("10.250.0.0/24")
            and int(str(ip).split(".")[-1]) not in (0, 255),
            "explicit WG host address required",
        )
        ips.append(str(ip))
    require(len(ips) == len(set(ips)), "duplicate WG addresses")
    require(
        isinstance(c.get("reserved_addresses"), list),
        "reserved client address inventory required",
    )
    reserved = {str(ipaddress.ip_address(v)) for v in c["reserved_addresses"]}
    require(not set(ips) & reserved, "node address collides with a human/device WG client")
    require(
        set(c.get("kernel_only_nodes", [])) <= set(c["nodes"]),
        "kernel-only nodes must be admitted inventory nodes",
    )
    return c


def manifests(host, image, enrollment=False, kernel_only=False):
    """Render the node Deployment and Service manifests for a reviewed host."""
    require(re.fullmatch(r"socrat-[0-9]+", host), "invalid node")
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
    container = {
        "name": "peer",
        "image": image,
        "env": [{"name": k, "value": v} for k, v in env.items()],
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
        "volumeMounts": [
            {"name": "state", "mountPath": "/etc/netbird"},
            {"name": "tun", "mountPath": "/dev/net/tun"},
        ],
    }
    if kernel_only:
        # A fresh Docker entrypoint starts an interactive SSO `up` and races
        # the one-off controller enrollment. Run only the service daemon.
        container["command"] = ["netbird"]
        container["args"] = ["service", "run"]
        container["volumeMounts"] = [v for v in container["volumeMounts"] if v["name"] != "tun"]
    if enrollment:
        container["env"].append(
            {
                "name": "NB_SETUP_KEY",
                "valueFrom": {"secretKeyRef": {"name": name + "-enrollment", "key": "setup-key"}},
            }
        )
    documents = [
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
                    "spec": {
                        "hostNetwork": True,
                        "dnsPolicy": "ClusterFirstWithHostNet",
                        "automountServiceAccountToken": False,
                        "nodeSelector": {"kubernetes.io/hostname": host},
                        "tolerations": [
                            {
                                "key": "homelab.io/bootstrap",
                                "operator": "Equal",
                                "value": "true",
                                "effect": "NoSchedule",
                            }
                        ],
                        "containers": [container],
                        "volumes": [
                            {
                                "name": "state",
                                "persistentVolumeClaim": {"claimName": name},
                            },
                            {
                                "name": "tun",
                                "hostPath": {
                                    "path": "/dev/net/tun",
                                    "type": "CharDevice",
                                },
                            },
                        ],
                    },
                },
            },
        },
    ]

    if kernel_only:
        spec = documents[1]["spec"]["template"]["spec"]
        spec["volumes"] = [v for v in spec["volumes"] if v["name"] != "tun"]
        spec["tolerations"].append(
            {
                "key": "homelab.io/no-nfs",
                "operator": "Equal",
                "value": "true",
                "effect": "NoSchedule",
            }
        )
    return documents


def policy_body(source, resource):
    """Build the admin-to-node policy body for one inventory /32 resource."""
    return {
        "name": "admin-wg-" + resource,
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


def member_ids(group: object) -> set[object]:
    """Return the ids of every peer currently recorded in the group."""
    return {
        cast("dict[str, object]", p)["id"] if isinstance(p, dict) else p
        for p in cast("list[object]", cast("dict[str, object]", group).get("peers") or [])
    }


def unique(items, key, value):
    """Return the exactly one item matching key=value, refusing ambiguity."""
    found = [v for v in items if v.get(key) == value]
    require(len(found) == 1, "missing or ambiguous " + key)
    return found[0]


def policy_ok(p, admin, resource=None, group=None):
    """Check that a policy matches the reviewed single-rule admin grant shape."""
    rules = p.get("rules") or []
    if not p.get("enabled") or len(rules) != 1:
        return False
    r = rules[0]
    src = {v["id"] if isinstance(v, dict) else v for v in (r.get("sources") or [])}
    dst = {v["id"] if isinstance(v, dict) else v for v in (r.get("destinations") or [])}
    return (
        r.get("enabled")
        and r.get("action") == "accept"
        and r.get("protocol") == "all"
        and r.get("bidirectional") is False
        and not r.get("ports")
        and src == {admin}
        and (r.get("destinationResource") or {}).get("id") == resource
        and (resource is None or r["destinationResource"].get("type") == "host")
        and dst == ({group} if group else set())
    )


class _PlanInputs(NamedTuple):
    """Guarded policies and inventory-node context for reconcile."""

    policies: object
    node: object
    address: object
    entry: object
    seed: object
    host: object


class _ResourceReview(NamedTuple):
    """Reviewed network resource and its managed admin-policy grants."""

    resources_path: str
    resource: object
    matching: object


def node_ready(node: object) -> bool:
    """Report whether the Kubernetes node currently reports a Ready condition."""
    status = cast("dict[str, object]", cast("dict[str, object]", node).get("status", {}))
    conditions = cast("list[object]", status.get("conditions", []))
    return any(
        cast("dict[str, object]", c)["type"] == "Ready"
        and cast("dict[str, object]", c)["status"] == "True"
        for c in conditions
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow HTTP redirects."""

    def redirect_request(self, *_a, **_kw):
        """Refuse redirects so credentials are never forwarded."""
        return


class Runtime:
    """Runtime wrapper for reconciling NetBird node state."""

    def __init__(self, folder, config, apply=False) -> None:
        """Initialize the reconciliation runtime."""
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

    def api(self, method, path, body=None):
        """Call the NetBird management API with the pinned token."""
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

    def kub(self, args, obj=None, optional=False, stdin=None):
        """Run a kubectl command with a strict allowlist per operation."""
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
            require(
                args[:2] == ["delete", "--raw"]
                and args[2].startswith("/api/v1/namespaces/" + NS + "/pods/")
                and obj
                and obj.get("kind") == "DeleteOptions"
                and obj.get("preconditions", {}).get("uid")
                and obj["preconditions"].get("resourceVersion"),
                "only UID-bound operational pod restart is permitted",
            )
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

    def get(self, kind, name, ns=NS, optional=False):
        """Fetch one object if present, or None when missing."""
        out = self.kub(["-n", ns, "get", kind, name, "-o", "json"], optional=optional)
        return json.loads(out) if out.strip() else None

    def save(self):
        """Persist the reconciler state atomically."""
        atomic(self.state_path, self.state)

    def write(self, method, path, body):
        """Apply an already-verified mutation if planning permits it."""
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
    def require_argocd(obj) -> None:
        """Assert the manifest is owned by the Argo CD application."""
        meta = obj["metadata"]
        require(
            meta.get("annotations", {})
            .get("argocd.argoproj.io/tracking-id", "")
            .startswith("netbird:")
            or meta.get("labels", {}).get("app.kubernetes.io/instance") == "netbird",
            "workload/PVC must already be owned by the root-managed netbird Argo CD Application",
        )

    def restart_without_key(self, host, deployment):
        # Operational acceptance restart only: never edit/create a workload spec.
        """Restart the deployment pod so the node key is never persisted."""
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
        require(
            rs["metadata"]["uid"] == owners[0]["uid"]
            and any(
                v["kind"] == "Deployment"
                and v["uid"] == deployment["metadata"]["uid"]
                and v.get("controller")
                for v in rs["metadata"].get("ownerReferences", [])
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
            [
                "-n",
                NS,
                "wait",
                "--for=delete",
                "pod/" + pod["metadata"]["name"],
                "--timeout=90s",
            ]
        )
        self.kub(
            [
                "-n",
                NS,
                "rollout",
                "status",
                "deployment/machine-" + host,
                "--timeout=120s",
            ]
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

    def enroll_argocd_agent(self, host, node, deployment, pvc):
        """Enroll the node and record ownership before any restart."""
        self.require_argocd(deployment)
        self.require_argocd(pvc)
        peers = self.api("GET", "peers")
        require(
            not any(p.get("hostname") == host or p.get("name") == "machine-" + host for p in peers),
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
            "node_uid": node["metadata"]["uid"],
            "address": self.config["nodes"][host],
            "deployment_uid": deployment["metadata"]["uid"],
            "pvc_uid": pvc["metadata"]["uid"],
        }
        self.save()
        key = self.write(
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
                stdin=key["key"].encode(),
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
            self.state["cleanup"] = {
                "setup_key_id": key["id"],
                "node": host,
                "revoked": False,
            }
            self.save()
            retired = self.api(
                "PUT", "setup-keys/" + key["id"], {"revoked": True, "auto_groups": []}
            )
            require(retired["revoked"], "setup-key retirement failed")
            self.state["cleanup"]["revoked"] = True
            self.save()
        self.restart_without_key(host, deployment)
        again, second = self.peer_for_status(host)
        require(
            peer["id"] == again["id"] and status == second,
            "identity changed on key-free restart",
        )
        require(
            self.get("deployment", "machine-" + host)["metadata"]["uid"]
            == deployment["metadata"]["uid"]
            and self.get("pvc", "machine-" + host)["metadata"]["uid"] == pvc["metadata"]["uid"],
            "Argo CD workload or storage replaced during enrollment",
        )
        return peer, status

    def guard(self):
        """Validate the Argo CD application and inventory configuration."""
        app = self.get("application", "netbird", ns="argocd")
        source = app["spec"].get("source", {})
        require(
            app["spec"]["project"] == "default"
            and source.get("path") == "charts/netbird"
            and source.get("targetRevision") == "main"
            and source.get("repoURL") == "https://github.com/alchemmist/homelab.git"
            and (
                app["metadata"]
                .get("annotations", {})
                .get("argocd.argoproj.io/tracking-id", "")
                .startswith("root:")
                or app["metadata"].get("labels", {}).get("app.kubernetes.io/instance") == "root"
            ),
            "root-managed GitOps Application required; do not create one manually",
        )
        groups = self.api("GET", "groups")
        self.admin = unique(groups, "name", ADMIN)
        self.group = unique(groups, "name", DEST)
        require(
            self.admin["issued"] == "jwt" and not self.admin.get("resources"),
            "real JWT admin source required",
        )
        require(
            self.group["issued"] == "api" and not self.group.get("resources"),
            "dedicated machine destinations required",
        )
        net = unique(self.api("GET", "networks"), "name", NETWORK)
        self.network = net["id"]
        routers = self.api("GET", "networks/" + self.network + "/routers")
        require(
            len(routers) == 1
            and not routers[0].get("peer")
            and routers[0]["peer_groups"] == [self.group["id"]]
            and routers[0]["enabled"]
            and routers[0]["masquerade"]
            and routers[0]["metric"] == 80,
            "native group-router drift",
        )
        cluster = self.get("namespace", "kube-system", ns="default")["metadata"]["uid"]
        namespace = self.get("namespace", NS, ns="default")["metadata"]["uid"]
        binding = {
            "cluster_uid": cluster,
            "namespace_uid": namespace,
            "network_id": self.network,
            "router_id": routers[0]["id"],
            "admin_id": self.admin["id"],
            "group_id": self.group["id"],
        }
        require(
            self.state.get("scope", binding) == binding,
            "cluster/account/scope binding changed",
        )
        self.state["scope"] = binding
        policies = self.api("GET", "policies")
        all_id = unique(groups, "name", "All")["id"]
        for policy in policies:
            for rule in policy.get("rules", []):
                if policy.get("enabled") and rule.get("enabled") and rule.get("action") == "accept":
                    endpoints = (rule.get("sources") or []) + (rule.get("destinations") or [])
                    require(
                        all_id not in {g["id"] if isinstance(g, dict) else g for g in endpoints},
                        "All-device grant violates enrollment default deny",
                    )
        require(
            any(policy_ok(p, self.admin["id"], group=self.group["id"]) for p in policies),
            "admin own-node INPUT policy missing or broadened",
        )
        return policies

    def status(self, host):
        """Read the current enrollment status of the host's node."""
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
        return {
            "ip": str(ipaddress.ip_interface(value["netbirdIp"]).ip),
            "key": value["publicKey"],
        }

    def peer_for_status(self, host):
        """Return the peer record matching the host's enrolled IP."""
        status = self.status(host)
        p = unique(self.api("GET", "peers"), "ip", status["ip"])
        require(
            p["connected"]
            and not p["user_id"]
            and not p["approval_required"]
            and not p["login_expired"]
            and bool(p["hostname"])
            and p["name"] == "machine-" + host,
            "machine peer identity/admission mismatch",
        )
        return p, status

    def verify_deployment(self, host, d):
        """Verify the deployment manifest matches the expected rendering."""
        expected = manifests(
            host,
            self.config["image"],
            kernel_only=host in self.config.get("kernel_only_nodes", []),
        )[1]
        spec = d["spec"]["template"]["spec"]
        want = expected["spec"]["template"]["spec"]
        require(
            d["spec"]["replicas"] == 1
            and spec["nodeSelector"] == want["nodeSelector"]
            and spec["hostNetwork"]
            and spec["automountServiceAccountToken"] is False
            and len(spec["containers"]) == 1,
            "agent placement/config drift",
        )
        c, wc = spec["containers"][0], want["containers"][0]
        require(
            c["image"] == wc["image"]
            and c["env"] == wc["env"]
            and c["volumeMounts"] == wc["volumeMounts"]
            and c["securityContext"] == wc["securityContext"],
            "agent image/env/security drift",
        )
        require(spec["volumes"] == want["volumes"], "persistent identity volumes drift")

    def _plan_inputs(self, host: object, seed: object) -> _PlanInputs:
        """Review adoption bindings and collect the inventory-node context."""
        cfg = cast("dict[str, object]", self.config)
        inventory = cast("dict[str, object]", cfg["nodes"])
        require(host in inventory, "host not enabled in inventory")
        policies = self.guard()
        state_nodes = cast("dict[str, object]", cast("dict[str, object]", self.state)["nodes"])
        known = {
            cast("dict[str, object]", v)["peer_id"]
            for v in state_nodes.values()
            if cast("dict[str, object]", v).get("peer_id")
        }
        seed_raw = cast("dict[str, object]", seed) if seed else {}
        known |= {
            cast("dict[str, object]", v)["id"]
            for v in cast("dict[str, object]", seed_raw.get("nodes", {})).values()
            if cast("dict[str, object]", v).get("id")
        }
        require(
            member_ids(self.group) <= known,
            "unbound machine-group member: explicit initial adoption required",
        )
        node = self.get("node", host, ns="default", optional=True)
        if node is None or not node_ready(node):
            return _PlanInputs(
                policies=None, node=None, address=None, entry=None, seed=seed, host=host
            )
        return _PlanInputs(
            policies=policies,
            node=node,
            address=inventory[host],
            entry=state_nodes.get(host),
            seed=seed,
            host=host,
        )

    def _verify_ready_entry(self, inputs: _PlanInputs) -> None:
        """Require a previously enrolled node to keep its recorded identity."""
        entry = inputs.entry
        if not entry:
            return
        raw_entry = cast("dict[str, object]", entry)
        require(
            raw_entry["phase"] == "ready",
            "incomplete enrollment: inspect private state, never reissue automatically",
        )
        metadata = cast("dict[str, object]", cast("dict[str, object]", inputs.node)["metadata"])
        require(
            raw_entry["node_uid"] == metadata["uid"] and raw_entry["address"] == inputs.address,
            "node reinstallation/address change requires explicit retirement",
        )

    def _existing_peer(
        self, inputs: _PlanInputs, d: object, pvc: object
    ) -> tuple[object, object] | None:
        """Verify existing identity storage and locate or enroll its agent peer."""
        host = inputs.host
        self.require_argocd(d)
        self.require_argocd(pvc)
        self.verify_deployment(host, d)
        seed_raw = cast("dict[str, object]", inputs.seed) if inputs.seed else {}
        if inputs.entry or cast("dict[str, object]", seed_raw.get("nodes", {})).get(host):
            p, status = self.peer_for_status(host)
            if not inputs.entry:
                require(
                    cast("dict[str, object]", seed_raw["nodes"][host]).get("id")
                    == cast("dict[str, object]", p)["id"],
                    "trusted migration binding mismatch",
                )
            return p, status
        enrolled = self.enroll_argocd_agent(host, inputs.node, d, pvc)
        return tuple(enrolled) if enrolled is not None else None

    def _require_lost_storage_absent(self, inputs: _PlanInputs) -> None:
        """Refuse re-enrollment when identity storage was lost."""
        seed_raw = cast("dict[str, object]", inputs.seed) if inputs.seed else {}
        require(
            inputs.entry is None
            and not cast("dict[str, object]", seed_raw.get("nodes", {})).get(inputs.host),
            "lost identity storage: no re-enrollment",
        )
        peers = cast("list[object]", self.api("GET", "peers"))
        host = cast("str", inputs.host)
        require(
            not any(
                cast("dict[str, object]", p).get("hostname") == host
                or cast("dict[str, object]", p).get("name") == "machine-" + host
                for p in peers
            ),
            "orphan existing peer: no name adoption",
        )

    def _binding(
        self, inputs: _PlanInputs, d: object, pvc: object, p: object, status: object
    ) -> dict[str, object]:
        """Assemble the persistent node/peer identity binding."""
        return {
            "phase": "ready",
            "node_uid": cast("dict[str, dict[str, object]]", inputs.node)["metadata"]["uid"],
            "address": inputs.address,
            "deployment_uid": cast("dict[str, dict[str, object]]", d)["metadata"]["uid"],
            "pvc_uid": cast("dict[str, dict[str, object]]", pvc)["metadata"]["uid"],
            "peer_id": cast("dict[str, object]", p)["id"],
            "ip": cast("dict[str, object]", status)["ip"],
            "public_key": cast("dict[str, object]", status)["key"],
        }

    def _require_bound_identity(self, inputs: _PlanInputs, binding: object, p: object) -> None:
        """Require recorded bindings and destination-group membership to hold."""
        require(
            inputs.entry is None or inputs.entry == binding,
            "persistent node/peer identity drift",
        )
        require(
            inputs.entry is None or cast("dict[str, object]", p)["id"] in member_ids(self.group),
            "bound node removed from destination group; no automatic regrant",
        )

    def _require_local_address(self, host: object, address: object) -> None:
        """Require the inventory WG address to exist on the actual node."""
        local = cast(
            "list[object]",
            json.loads(
                self.kub(
                    [
                        "-n",
                        NS,
                        "exec",
                        "deployment/machine-" + cast("str", host),
                        "--",
                        "ip",
                        "-j",
                        "address",
                        "show",
                        "dev",
                        "wg-socrat",
                    ]
                )
            ),
        )
        require(
            any(
                cast("dict[str, object]", a).get("local") == address
                for i in local
                for a in cast("list[object]", cast("dict[str, object]", i).get("addr_info", []))
            ),
            "inventory WG address is not on the actual node",
        )

    def _verify_mesh_ping(self, host: object, p: object) -> None:
        """Ping every Ready inventory node when this peer is not yet admitted."""
        nodes = cast(
            "list[object]",
            cast(
                "dict[str, object]",
                json.loads(self.kub(["get", "nodes", "-o", "json"])),
            )["items"],
        )
        # Only Ready targets are required: an offline node is not mistaken for a broken mesh.
        ready = {
            cast("dict[str, dict[str, object]]", cast("dict[str, object]", n)["metadata"])["name"]
            for n in nodes
            if any(
                cast("dict[str, object]", c)["type"] == "Ready"
                and cast("dict[str, object]", c)["status"] == "True"
                for c in cast(
                    "list[object]",
                    cast("dict[str, dict[str, list[object]]]", n)["status"]["conditions"],
                )
            )
        }
        if cast("dict[str, object]", p)["id"] not in member_ids(self.group):
            inventory = cast("dict[str, object]", cast("dict[str, object]", self.config)["nodes"])
            for h in sorted(ready & inventory.keys()):
                self.kub(
                    [
                        "-n",
                        NS,
                        "exec",
                        "deployment/machine-" + cast("str", host),
                        "--",
                        "ping",
                        "-n",
                        "-c",
                        "1",
                        "-W",
                        "3",
                        inventory[h],
                    ]
                )

    def _reviewed_resource(self, host: object, address: object) -> tuple[str, object | None]:
        """Locate the existing reviewed /32 resource for this inventory address."""
        resources_path = "networks/" + self.network + "/resources"
        resources = cast("list[object]", self.api("GET", resources_path))
        found = [
            r
            for r in resources
            if cast("dict[str, object]", r)["address"] == cast("str", address) + "/32"
        ]
        require(len(found) <= 1, "duplicate WG host resources")
        resource = found[0] if found else None
        if resource:
            raw_resource = cast("dict[str, object]", resource)
            require(
                raw_resource["name"] == "wg-" + cast("str", host)
                and raw_resource["enabled"]
                and raw_resource["type"] == "host"
                and not raw_resource.get("groups"),
                "existing resource scope drift",
            )
        return resources_path, resource

    def _matching_policies(self, policies: object, resource: object) -> list[object]:
        """Collect and verify the managed admin-policy grant for the resource."""
        matching: list[object] = []
        if not resource:
            return matching
        raw_resource = cast("dict[str, object]", resource)
        matching = [
            v
            for v in cast("list[object]", policies)
            if any(
                cast(
                    "dict[str, object]",
                    cast("dict[str, object]", r).get("destinationResource") or {},
                ).get("id")
                == raw_resource["id"]
                for r in cast("list[object]", cast("dict[str, object]", v)["rules"])
            )
            and cast("dict[str, object]", v)["name"].startswith("admin-wg-")
        ]
        require(len(matching) <= 1, "duplicate managed resource policies")
        if matching:
            require(
                policy_ok(matching[0], self.admin["id"], resource=raw_resource["id"]),
                "admin resource policy drift",
            )
        return matching

    def _resource_review(self, inputs: _PlanInputs) -> _ResourceReview:
        """Assemble the reviewed network resource and its managed admin policy."""
        resources_path, resource = self._reviewed_resource(inputs.host, inputs.address)
        matching = self._matching_policies(inputs.policies, resource)
        return _ResourceReview(resources_path=resources_path, resource=resource, matching=matching)

    def _require_grant_aligned(
        self, grant: object, inputs: _PlanInputs, p: object, review: _ResourceReview
    ) -> None:
        """Require managed grants to be present without silent replacement or loss."""
        if grant:
            raw_grant = cast("dict[str, object]", grant)
            require(
                review.resource is not None
                and cast("dict[str, object]", review.resource)["id"] == raw_grant["resource_id"]
                and review.matching
                and cast("dict[str, object]", cast("list[object]", review.matching)[0])["id"]
                == raw_grant["policy_id"],
                "managed grant removed/replaced: explicit review required, no resurrection",
            )
        elif inputs.entry:
            require(
                inputs.seed is not None
                and cast(
                    "dict[str, object]",
                    cast("dict[str, dict[str, object]]", inputs.seed)["nodes"].get(inputs.host, {}),
                ).get("id")
                == cast("dict[str, object]", p)["id"]
                and review.resource
                and review.matching,
                "legacy binding needs explicit grant-ID migration",
            )

    def _apply_admission(
        self,
        inputs: _PlanInputs,
        binding: object,
        grant: object,
        p: object,
        review: _ResourceReview,
    ) -> _ResourceReview:
        """Apply phase one: record admission and join the destination group."""
        state_nodes = cast("dict[str, object]", cast("dict[str, object]", self.state)["nodes"])
        state_nodes[inputs.host] = dict(cast("dict[str, object]", binding), phase="admitting")
        self.save()
        if inputs.entry is None or grant is None:
            self.changed = True
        if cast("dict[str, object]", p)["id"] not in member_ids(self.group):
            fresh = self.api("GET", "groups/" + self.group["id"])
            require(
                member_ids(fresh) == member_ids(self.group)
                and not fresh.get("resources")
                and fresh.get("issued") == "api"
                and fresh.get("name") == DEST,
                "concurrent machine-group change",
            )
            self.write(
                "PUT",
                "groups/" + self.group["id"],
                {
                    "name": DEST,
                    "resources": [],
                    "peers": sorted(member_ids(self.group) | {cast("dict[str, object]", p)["id"]}),
                },
            )
        if review.resource is None:
            created = self.write(
                "POST",
                review.resources_path,
                {
                    "name": "wg-" + cast("str", inputs.host),
                    "description": "Inventory WG node; no broader prefix",
                    "address": cast("str", inputs.address) + "/32",
                    "enabled": True,
                },
            )
            return review._replace(resource=created)
        return review

    def _apply_grant(self, inputs: _PlanInputs, binding: object, review: _ResourceReview) -> None:
        """Apply phase two: ensure the admin policy grant and persist final bindings."""
        matching = review.matching
        if not matching:
            matching = [
                self.write(
                    "POST",
                    "policies",
                    policy_body(
                        self.admin["id"],
                        cast("dict[str, object]", review.resource)["id"],
                    ),
                )
            ]
        cast(
            "dict[str, object]",
            cast("dict[str, object]", self.state).setdefault("grants", {}),
        )[cast("str", inputs.host)] = {
            "resource_id": cast("dict[str, object]", review.resource)["id"],
            "policy_id": cast("dict[str, object]", cast("list[object]", matching)[0])["id"],
        }
        state_nodes = cast("dict[str, object]", cast("dict[str, object]", self.state)["nodes"])
        state_nodes[inputs.host] = binding
        self.save()

    def reconcile(self, host, seed=None):
        """Reconcile one host end-to-end through verification and reporting."""
        inputs = self._plan_inputs(host, seed)
        if inputs.node is None:
            return {"changed": False, "status": "deferred-node-not-ready", "node": host}
        self._verify_ready_entry(inputs)
        d = self.get("deployment", "machine-" + host, optional=True)
        pvc = self.get("pvc", "machine-" + host, optional=True)
        if d or pvc:
            require(
                d is not None and pvc is not None,
                "partial/missing identity storage: refuse replacement",
            )
            existing = self._existing_peer(inputs, d, pvc)
            if existing is None:
                return {
                    "changed": False,
                    "status": "would-enroll-and-authorize",
                    "node": host,
                }
            p, status = existing
        else:
            self._require_lost_storage_absent(inputs)
            return {
                "changed": False,
                "status": "awaiting-argocd-workloads",
                "node": host,
            }
        binding = self._binding(inputs, d, pvc, p, status)
        self._require_bound_identity(inputs, binding, p)
        self._require_local_address(inputs.host, inputs.address)
        self._verify_mesh_ping(inputs.host, p)
        review = self._resource_review(inputs)
        grant = self.state.get("grants", {}).get(host)
        self._require_grant_aligned(grant, inputs, p, review)
        if self.apply:
            review = self._apply_admission(inputs, binding, grant, p, review)
            self._apply_grant(inputs, binding, review)
        return {
            "changed": self.changed,
            "status": "ready" if self.apply else "validated-plan",
            "node": host,
        }


def main():
    """Verify the pinning config and reconcile the reviewed node state."""
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
        runtime = Runtime(folder, c, args.apply)
        seed = json.loads(args.adopt_state.read_text()) if args.adopt_state else None
        require(args.node is not None, "explicit selected inventory node required")
        print(json.dumps(runtime.reconcile(args.node, seed)))


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        OSError,
        subprocess.SubprocessError,
        http.client.HTTPException,
    ) as e:
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
