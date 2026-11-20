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
        """Include exactly the two kube-system workloads, without Helm or deletion."""
        tasks = yaml.safe_load(
            (ROOT / "ansible/roles/vps_workload_offload/tasks/main.yml").read_text()
        )
        loops = [task for task in tasks if "ansible.builtin.include_tasks" in task]
        self.assertEqual(len(loops), 1)
        self.assertEqual(
            loops[0]["loop"],
            [
                {"namespace": "kube-system", "name": "metrics-server"},
                {"namespace": "kube-system", "name": "local-path-provisioner"},
            ],
        )
        deployment = (ROOT / "ansible/roles/vps_workload_offload/tasks/deployment.yml").read_text()
        self.assertIn("rollout", yaml.safe_load(deployment)[1]["ansible.builtin.command"]["argv"])
        template = yaml.safe_load(deployment)[0]["vars"]["offload_patch_spec"]["spec"]["template"]["spec"]
        self.assertIsNone(template["nodeSelector"]["kubernetes.io/hostname"])
        terms = template["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
        self.assertEqual(terms["nodeSelectorTerms"][0]["matchExpressions"][0]["values"], ["socrat-0", "socrat-1"])
        self.assertNotIn("delete", deployment)
        self.assertFalse(
            any("helm" in str(task.get("ansible.builtin.command", {})) for task in tasks)
        )

    def test_playbook_refuses_cluster_wide_eviction(self) -> None:
        """Keep reconcile disabled and the play limited to the two roles."""
        play = yaml.safe_load((ROOT / "ansible/playbooks/socrat-2-offload.yml").read_text())[0]
        checks = [
            task["ansible.builtin.assert"]
            for task in play["pre_tasks"]
            if "ansible.builtin.assert" in task
        ]
        self.assertEqual(
            checks[0]["that"], "not (container_resource_policy_reconcile | default(false) | bool)"
        )
        self.assertEqual(play["roles"], ["container_resource_policy", "vps_workload_offload"])

    def test_image_proxy_helm_values_require_vps_placement(self) -> None:
        """Require the image-proxy chart to select the VPS node."""
        values = yaml.safe_load((ROOT / "charts/img-proxy/values.yaml").read_text())
        self.assertEqual(values["nodeSelector"], {"kubernetes.io/hostname": "socrat-2"})
        deployment = (ROOT / "charts/img-proxy/templates/deployment.yaml").read_text()
        self.assertIn("with .Values.nodeSelector", deployment)


if __name__ == "__main__":
    unittest.main()
