from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class VPSWorkloadOffloadTests(unittest.TestCase):
    """Read-only placement checks for the selected VPS offload sources."""

    def test_selected_profiles_preserve_explicit_node_placement(self) -> None:
        """Do not let pod admission reintroduce the old singleton pin."""
        profiles = yaml.safe_load((ROOT / "ansible/vars/container-resources.yml").read_text())[
            "container_resource_policy_profiles"
        ]
        by_owner = {(p["namespace"], p["ownerPattern"]): p for p in profiles}
        self.assertEqual(by_owner[("img-proxy", r"^img\-proxy-[a-z0-9]+$")]["nodeSelector"],
                         {"kubernetes.io/hostname": "socrat-2"})
        for owner in (r"^metrics\-server-[a-z0-9]+$", r"^local\-path\-provisioner-[a-z0-9]+$"):
            self.assertNotIn("kubernetes.io/hostname", by_owner[("kube-system", owner)].get("nodeSelector", {}))

    def test_rollout_is_sequential_and_scoped(self) -> None:
        """Only metrics-server remains imperative; storage-tiers owns provisioner placement."""
        tasks = yaml.safe_load(
            (ROOT / "ansible/roles/vps_workload_offload/tasks/main.yml").read_text()
        )
        loops = [task for task in tasks if "ansible.builtin.include_tasks" in task]
        self.assertEqual(len(loops), 1)
        self.assertEqual(
            loops[0]["loop"],
            [
                {"namespace": "kube-system", "name": "metrics-server"},
            ],
        )
        platform = list(yaml.safe_load_all((ROOT / "deploy/storage/tiers/platform.yaml").read_text()))
        provisioner = next(d for d in platform if d["kind"] == "Deployment")
        self.assertEqual(provisioner["metadata"]["name"], "local-path-provisioner")
        affinity = provisioner["spec"]["template"]["spec"]["affinity"]["nodeAffinity"]
        self.assertEqual(affinity["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]["matchExpressions"][0]["values"], ["socrat-0", "socrat-1"])
        deployment = (ROOT / "ansible/roles/vps_workload_offload/tasks/deployment.yml").read_text()
        self.assertIn("rollout", yaml.safe_load(deployment)[2]["ansible.builtin.command"]["argv"])
        template = yaml.safe_load(deployment)[1]["vars"]["offload_patch_spec"]["spec"]["template"]["spec"]
        self.assertIsNone(template["nodeSelector"]["kubernetes.io/hostname"])
        def term(nodes: list[str]):
            return {"matchExpressions": [{"key": "kubernetes.io/hostname", "operator": "In", "values": nodes}]}

        self.assertEqual(template["affinity"]["nodeAffinity"], {
            "requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [term(["socrat-0", "socrat-1"])]},
            "preferredDuringSchedulingIgnoredDuringExecution": [{"weight": 100, "preference": term(["socrat-0"])}],
        })
        self.assertNotIn("delete", deployment)
        self.assertFalse(
            any("helm" in str(task.get("ansible.builtin.command", {})) for task in tasks)
        )

    def test_playbook_refuses_cluster_wide_eviction(self) -> None:
        """Keep reconcile disabled and the play limited to the scoped role."""
        play = yaml.safe_load((ROOT / "ansible/playbooks/socrat-2-offload.yml").read_text())[0]
        checks = [
            task["ansible.builtin.assert"]
            for task in play["pre_tasks"]
            if "ansible.builtin.assert" in task
        ]
        self.assertEqual(
            checks[0]["that"], "not (container_resource_policy_reconcile | default(false) | bool)"
        )
        self.assertEqual(play["roles"], ["vps_workload_offload"])

    def test_image_proxy_helm_values_require_vps_placement(self) -> None:
        """Require the image-proxy chart to select the VPS node."""
        values = yaml.safe_load((ROOT / "charts/img-proxy/values.yaml").read_text())
        self.assertEqual(values["nodeSelector"], {"kubernetes.io/hostname": "socrat-2"})
        deployment = (ROOT / "charts/img-proxy/templates/deployment.yaml").read_text()
        self.assertIn("with .Values.nodeSelector", deployment)


if __name__ == "__main__":
    unittest.main()
