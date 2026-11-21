"""Owner-approved static app placement: replace node2, retain two failure domains."""

from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

REPLICA_COUNT_WITH_ANTI_AFFINITY = 2


class StaticVMPlacementTests(unittest.TestCase):
    """Check retained failure domains, rolling updates, images, and opt-out."""

    def render(self, name, *extra):
        output = subprocess.check_output(
            [
                "helm",
                "template",
                name,
                str(ROOT / "charts" / name),
                "-f",
                str(ROOT / "deploy" / name / "values.yaml"),
                *extra,
            ],
            text=True,
        )
        return next(d for d in yaml.safe_load_all(output) if d and d.get("kind") == "Deployment")

    def test_production_eligibility_and_two_failure_domains(self) -> None:
        """Require two replicas on the retained node and socrat-5, with anti-affinity."""
        for name, retained in [("blog", "socrat-0"), ("socrat-home", "socrat-1")]:
            with self.subTest(app=name):
                spec = self.render(name)["spec"]
                assert spec["replicas"] == REPLICA_COUNT_WITH_ANTI_AFFINITY
                pod = spec["template"]["spec"]
                affinity = pod["affinity"]
                assert affinity["nodeAffinity"] == {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {
                                        "key": "kubernetes.io/hostname",
                                        "operator": "In",
                                        "values": [retained, "socrat-5"],
                                    }
                                ]
                            }
                        ]
                    }
                }
                anti = affinity["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
                assert len(anti) == 1
                assert anti[0]["topologyKey"] == "kubernetes.io/hostname"
                assert anti[0]["labelSelector"]["matchLabels"] == spec["selector"]["matchLabels"]
                assert "nodeName" not in pod
                assert "nodeSelector" not in pod

    def test_rolling_update_cannot_deadlock_on_two_required_domains(self) -> None:
        """Keep surge at zero so two required hostnames cannot deadlock a rollout."""
        for name in ["blog", "socrat-home"]:
            with self.subTest(app=name):
                strategy = self.render(name)["spec"]["strategy"]
                assert strategy["type"] == "RollingUpdate"
                assert strategy["rollingUpdate"] == {"maxSurge": 0, "maxUnavailable": 1}

    def test_images_unchanged_and_no_persistent_data_added(self) -> None:
        """Keep the digested image and reject new persistent or host volumes."""
        for name in ["blog", "socrat-home"]:
            with self.subTest(app=name):
                values = yaml.safe_load((ROOT / "deploy" / name / "values.yaml").read_text())
                pod = self.render(name)["spec"]["template"]["spec"]
                assert (
                    pod["containers"][0]["image"]
                    == values["image"]["repository"] + "@" + values["image"]["digest"]
                )
                for volume in pod.get("volumes", []):
                    assert "persistentVolumeClaim" not in volume
                    assert "hostPath" not in volume

    def test_optional_scheduling_can_be_disabled(self) -> None:
        """Allow the chart to render without affinity when scheduling is disabled."""
        for name in ["blog", "socrat-home"]:
            with self.subTest(app=name):
                pod = self.render(
                    name, "--set", "nodeAffinity=null", "--set", "podAntiAffinity.enabled=false"
                )["spec"]["template"]["spec"]
                assert "affinity" not in pod


if __name__ == "__main__":
    unittest.main()
