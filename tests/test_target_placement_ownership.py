import json
from types import SimpleNamespace
from unittest.mock import patch
import yaml
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("target", ROOT / "scripts/check_target_placement.py")
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


def owner(kind, uid):
    return {"kind": kind, "uid": uid, "controller": True}


def fixture():
    d = {
        "metadata": {
            "uid": "deployment",
            "generation": 2,
            "annotations": {"deployment.kubernetes.io/revision": "3"},
        },
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "fixture"}}},
        "status": {
            "replicas": 1,
            "updatedReplicas": 1,
            "readyReplicas": 1,
            "availableReplicas": 1,
            "observedGeneration": 2,
        },
    }
    r = {
        "metadata": {
            "uid": "rs-current",
            "ownerReferences": [owner("Deployment", "deployment")],
            "annotations": {"deployment.kubernetes.io/revision": "3"},
        }
    }
    p = {
        "metadata": {"ownerReferences": [owner("ReplicaSet", "rs-current")]},
        "spec": {"nodeName": "socrat-5", "containers": [{"name": "app"}]},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "app", "ready": True}],
        },
    }
    return d, [r], [p]


class Ownership(unittest.TestCase):
    def test_current_revision_and_ready_pod(self):
        d, r, p = fixture()
        self.assertTrue(target.converged(d, p, "socrat-5"))
        self.assertTrue(target.owned_by_current_revision(d, r, p))

    def test_old_revision_rejected_even_with_valid_deployment_owner(self):
        d, r, p = fixture()
        r[0]["metadata"]["annotations"]["deployment.kubernetes.io/revision"] = "2"
        self.assertFalse(target.owned_by_current_revision(d, r, p))

    def test_wrong_owner_uid_kind_or_noncontroller_rejected(self):
        for level in ["replicaset", "pod"]:
            for field, value in [("uid", "wrong"), ("kind", "wrong"), ("controller", False)]:
                with self.subTest(level=level, field=field):
                    d, r, p = fixture()
                    obj = r[0] if level == "replicaset" else p[0]
                    obj["metadata"]["ownerReferences"][0][field] = value
                    self.assertFalse(target.owned_by_current_revision(d, r, p))

    def test_missing_revision_and_empty_pods_do_not_pass_vacuously(self):
        d, r, p = fixture()
        self.assertFalse(target.owned_by_current_revision(d, r, []))
        d["metadata"]["annotations"].clear()
        self.assertFalse(target.owned_by_current_revision(d, r, p))

    def test_readiness_gate_or_nonrunning_phase_rejected(self):
        d, r, p = fixture()
        p[0]["status"]["conditions"][0]["status"] = "False"
        self.assertFalse(target.converged(d, p, "socrat-5"))
        d, r, p = fixture()
        p[0]["status"]["phase"] = "Pending"
        self.assertFalse(target.converged(d, p, "socrat-5"))

    def test_unavailable_or_extra_deployment_replicas_rejected(self):
        for field, value in [("availableReplicas", 0), ("replicas", 2), ("unavailableReplicas", 1)]:
            with self.subTest(field=field):
                d, r, p = fixture()
                d["status"][field] = value
                self.assertFalse(target.converged(d, p, "socrat-5"))


class Transport(unittest.TestCase):
    def test_cli_transports_only_get_requests_and_uses_same_contract(self):
        for local in [False, True]:
            with self.subTest(local=local):
                d, r, p = fixture()
                results = [
                    SimpleNamespace(returncode=0, stdout=json.dumps(obj))
                    for obj in [d, {"items": p}, {"items": r}]
                ]
                argv = [
                    "check_target_placement.py",
                    "--namespace",
                    "fixture",
                    "--deployment",
                    "fixture",
                    "--node",
                    "socrat-5",
                    "--timeout",
                    "1",
                ] + (["--local"] if local else [])
                with (
                    patch("sys.argv", argv),
                    patch.object(target.subprocess, "run", side_effect=results) as run,
                ):
                    target.main()
                self.assertEqual(run.call_count, 3)
                for call in run.call_args_list:
                    command = call.args[0]
                    if local:
                        self.assertEqual(command[0], "kubectl")
                        self.assertIn("get", command)
                    else:
                        self.assertEqual(command[0], "ssh")
                        self.assertIn(" get ", command[-1])

    def test_ansible_uses_same_checker_without_nested_ssh(self):
        tasks = yaml.safe_load(
            (ROOT / "ansible/roles/rancher_placement/tasks/verify.yml").read_text()
        )
        self.assertIn("ansible.builtin.assert", tasks[0])
        script = tasks[1]["ansible.builtin.script"]
        self.assertIn("scripts/check_target_placement.py", script["cmd"])
        self.assertIn("--local", script["cmd"])
        self.assertEqual(script["executable"], "/usr/bin/python3")
        self.assertFalse(tasks[1]["changed_when"])


if __name__ == "__main__":
    unittest.main()
