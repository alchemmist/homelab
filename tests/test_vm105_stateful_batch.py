"""Offline source boundaries. No kube/credentials/workflow/model calls."""

import copy, pathlib, subprocess, tempfile, typing, unittest, yaml
from typing import Mapping

R = pathlib.Path(__file__).resolve().parents[1]
LOCAL_STORAGE_CLAIM_PAIR_COUNT = 9
BASE = "ba7a1f34"


def _mapping(value: object) -> dict[str, object]:
    """Narrow decoded document fields to mappings for typed test callers."""
    assert isinstance(value, dict)
    return value


def _sequence(value: object) -> list[object]:
    """Narrow decoded document fields to sequences for typed test callers."""
    assert isinstance(value, list)
    return list(value)


def _text(value: object) -> str:
    """Narrow decoded document fields to text for typed test callers."""
    assert isinstance(value, str)
    return value


def render(
    root: pathlib.Path,
    chart: str,
    values: str | None,
    ns: str,
    release: str,
    *,
    release_image: dict[str, str] | None = None,
    monori_images: dict[str, dict[str, str]] | None = None,
) -> dict[tuple[str, str], dict[str, object]]:
    cmd = ["helm", "template", release, str(root / chart), "-n", ns]
    if values:
        cmd += ["-f", str(root / values)]
    if release_image is not None:
        # Release version is an input independent of historical placement. Only
        # the before-render receives it; a wrong current template still differs.
        for key, value in release_image.items():
            cmd += ["--set-string", f"image.{key}={value}"]
    if monori_images is not None:
        for component, fields in monori_images.items():
            for key, value in fields.items():
                cmd += ["--set-string", f"images.{component}.{key}={value}"]
    return {
        (d["kind"], d["metadata"]["name"]): d
        for d in yaml.safe_load_all(subprocess.check_output(cmd, text=True))
        if d
    }


def assert_monori_release_images(
    documents: Mapping[tuple[str, str], object], images: dict[str, dict[str, str]]
) -> None:
    """Check actual current images independently from before-render CLI overrides."""
    for component in ("front", "back", "sync"):
        matches = [
            d
            for (kind, name), d in documents.items()
            if kind in {"Deployment", "DaemonSet"}
            and name == ("monori" if component == "front" else "monori-" + component)
        ]
        assert len(matches) == 1
        image = images[component]
        expected = image["repository"] + "@" + image["digest"]
        doc = _mapping(matches[0])
        pod = _mapping(_mapping(_mapping(doc["spec"])["template"])["spec"])
        for container in _sequence(pod["containers"]) + _sequence(pod.get("initContainers", [])):
            assert _mapping(container)["image"] == expected, "Current Monori release image differs"


class StatefulBoundaries(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory[str]
    old: pathlib.Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.old = pathlib.Path(cls.tmp.name)
        archive = subprocess.check_output(
            [
                "git",
                "-C",
                str(R),
                "archive",
                BASE,
                "charts",
                "deploy/wiki-runtime",
                "deploy/monori",
                "deploy/spi-triage",
                "deploy/format-quorum",
            ]
        )
        subprocess.run(["tar", "-xf", "-", "-C", str(cls.old)], input=archive, check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _historical_inputs(
        self, chart: str, values: str | None
    ) -> tuple[dict[str, str] | None, dict[str, dict[str, str]] | None]:
        """Derive the before-render image inputs a given chart must pin."""
        release_image: dict[str, str] | None = None
        monori_images: dict[str, dict[str, str]] | None = None
        if chart == "charts/spi-triage":
            # Do not freeze the SPI application version at the migration
            # date or revert a subsequent canonical release from main.
            if values is None:
                raise AssertionError(f"{chart} requires a values file")
            image: dict[str, str] = yaml.safe_load((R / values).read_text())["image"]
            self.assertEqual(set(image), {"repository", "tag", "digest"})
            self.assertTrue(all(isinstance(value, str) for value in image.values()))
            release_image = image
        if chart == "charts/monori":
            # The owner release is independent of the placement handoff.
            # Inject only before-render inputs; retain all current-render
            # image/strategy/PVC/identity and full payload comparisons.
            if values is None:
                raise AssertionError(f"{chart} requires a values file")
            images: dict[str, dict[str, str]] = yaml.safe_load((R / values).read_text())["images"]
            self.assertEqual(set(images), {"front", "back", "sync"})
            for fields in images.values():
                self.assertEqual(set(fields), {"repository", "tag", "digest", "fallback"})
                self.assertTrue(all(isinstance(v, str) for v in fields.values()))
            monori_images = images
        return release_image, monori_images

    def _strip_volatile_pod_fields(self, rendered: dict[str, object]) -> None:
        """Drop fields either side may legitimately differ on before comparing."""
        spec = rendered["spec"]
        assert isinstance(spec, dict)
        spec.pop("strategy", None)
        pod = spec["template"]["spec"]
        assert isinstance(pod, dict)
        pod.pop("nodeSelector", None)
        pod.pop("hostAliases", None)
        kept = [
            c for c in pod.get("initContainers", []) if not c["name"].startswith("require-existing")
        ]
        if kept:
            pod["initContainers"] = kept
        else:
            pod.pop("initContainers", None)
        for v in pod.get("volumes", []):
            if v["name"] in ["data", "assets", "clang-versions", "tests", "config-history"]:
                v.clear()

    def _assert_changed_document(
        self,
        key: tuple[str, str],
        old: dict[str, object],
        current: dict[str, object],
        allowed: set[str],
    ) -> None:
        """Assert an intentionally changed document changed only in allowed ways."""
        if key == ("PersistentVolumeClaim", "litellm-branding"):
            x = copy.deepcopy(current)
            metadata = x["metadata"]
            assert isinstance(metadata, dict)
            metadata.pop("annotations", None)
            self.assertEqual(x, old)
            return
        self.assertEqual(key[0], "Deployment")
        self.assertIn(key[1], allowed)
        x, y = copy.deepcopy(old), copy.deepcopy(current)
        spec = y["spec"]
        assert isinstance(spec, dict)
        self.assertEqual(spec["replicas"], 1)
        self.assertEqual(spec["strategy"], {"type": "Recreate"})
        for o in [x, y]:
            self._strip_volatile_pod_fields(o)
        self.assertEqual(x, y)

    def test_only_intended_deployments_and_retention_annotation_change(self):

        cases = [
            (
                "deploy/wiki-runtime/chart",
                "deploy/wiki-runtime/values.yaml",
                "wiki",
                "wiki-runtime",
                {"wiki-runtime-wiki"},
            ),
            (
                "charts/monori",
                "deploy/monori/values.yaml",
                "monori",
                "monori",
                {"monori-back", "monori-sync"},
            ),
            (
                "charts/spi-triage",
                "deploy/spi-triage/values.yaml",
                "automation",
                "spi-triage",
                {"spi-triage"},
            ),
            (
                "charts/format-quorum",
                "deploy/format-quorum/values.yaml",
                "format-quorum",
                "format-quorum",
                {"format-quorum"},
            ),
            ("charts/litellm-infra", None, "llm", "litellm-infra", {"litellm-branding"}),
        ]
        for chart, values, ns, release, allowed in cases:
            with self.subTest(chart=chart):
                release_image = None
                monori_images = None
                if chart == "charts/spi-triage":
                    # Do not freeze the SPI application version at the migration
                    # date or revert a subsequent canonical release from main.
                    release_image = yaml.safe_load((R / values).read_text())["image"]
                    assert set(release_image) == {"repository", "tag", "digest"}
                    assert all(isinstance(value, str) for value in release_image.values())
                if chart == "charts/monori":
                    # The owner release is independent of the placement handoff.
                    # Inject only before-render inputs; retain all current-render
                    # image/strategy/PVC/identity and full payload comparisons.
                    monori_images = yaml.safe_load((R / values).read_text())["images"]
                    assert set(monori_images) == {"front", "back", "sync"}
                    for fields in monori_images.values():
                        assert set(fields) == {"repository", "tag", "digest", "fallback"}
                        assert all(isinstance(v, str) for v in fields.values())
                a, b = (
                    render(
                        self.old,
                        chart,
                        values,
                        ns,
                        release,
                        release_image=release_image,
                        monori_images=monori_images,
                    ),
                    render(R, chart, values, ns, release),
                )
                if monori_images is not None:
                    assert_monori_release_images(b, monori_images)
                assert set(a) == set(b)
                for k in a:
                    if a[k] == b[k]:
                        continue
                    if k == ("PersistentVolumeClaim", "litellm-branding"):
                        x = copy.deepcopy(b[k])
                        x["metadata"].pop("annotations", None)
                        assert x == a[k]
                        continue
                    assert k[0] == "Deployment"
                    assert k[1] in allowed
                    x, y = copy.deepcopy(a[k]), copy.deepcopy(b[k])
                    assert y["spec"]["replicas"] == 1
                    assert y["spec"]["strategy"] == {"type": "Recreate"}
                    for o in [x, y]:
                        o["spec"].pop("strategy", None)
                        p = o["spec"]["template"]["spec"]
                        p.pop("nodeSelector", None)
                        p.pop("hostAliases", None)
                        p["initContainers"] = [
                            c
                            for c in p.get("initContainers", [])
                            if not c["name"].startswith("require-existing")
                        ]
                        if not p["initContainers"]:
                            p.pop("initContainers")
                        for v in p.get("volumes", []):
                            if v["name"] in [
                                "data",
                                "assets",
                                "clang-versions",
                                "tests",
                                "config-history",
                            ]:
                                v.clear()
                    assert x == y

    def test_all_new_claims_are_prebound_local_retained_and_node5_only(self) -> None:
        count = 0
        for file in [
            "wishlist",
            "wiki-runtime",
            "monori",
            "spi-triage",
            "format-quorum",
            "litellm-branding",
        ]:
            docs = list(
                yaml.safe_load_all((R / "deploy/storage" / (file + "-socrat5.yaml")).read_text())
            )
            for pv, pvc in zip(docs[::2], docs[1::2], strict=False):
                count += 1
                assert pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
                assert pv["spec"]["local"]["path"].startswith("/mnt/files/homelab/")
                assert pvc["spec"]["volumeName"] == pv["metadata"]["name"]
                assert pvc["spec"]["storageClassName"] == ""
                assert pv["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"][0][
                    "matchExpressions"
                ][0]["values"] == ["socrat-5"]
        assert count == LOCAL_STORAGE_CLAIM_PAIR_COUNT

    def test_no_paused_ingress_or_zero_replica_left_in_final_sources(self) -> None:
        spi = yaml.safe_load((R / "deploy/spi-triage/values.yaml").read_text())
        assert not spi["maintenanceIngressPaused"]
        assert spi["workerReplicas"] == 1
        mono = yaml.safe_load((R / "deploy/monori/values.yaml").read_text())
        assert mono["backReplicaCount"] == 1
        assert mono["syncReplicaCount"] == 1
        assert mono["statefulRecreate"]
        for path in ["deploy/wiki-runtime/values.yaml", "deploy/format-quorum/values.yaml"]:
            assert yaml.safe_load((R / path).read_text())["replicaCount"] == 1
        legacy = (R / "ansible/playbooks/format-quorum.yml").read_text()
        assert "helm upgrade" not in legacy
        assert "pacman" not in legacy
        assert "argocd.argoproj.io/refresh=hard" in legacy

    def test_idle_controller_never_runs_or_cancels_a_business_job(self) -> None:
        s = (R / "scripts/vm105-spi-idle-handoff.py").read_text()
        for word in [
            "/claim",
            "/analyze",
            "/publish",
            "/operator/queue/cancel",
            "--force",
            "--grace-period=0",
        ]:
            assert word not in s
        for word in [
            "finally:",
            "newWorkWonRaceRestoringImmediately",
            "liveOwners",
            "liveLinkLeases",
            "skip-reconcile-",
        ]:
            assert word in s


if __name__ == "__main__":
    unittest.main()


class CurrentMonoriRelease(unittest.TestCase):
    def test_current_image_mutation_is_not_hidden_by_historical_input(self) -> None:
        images = yaml.safe_load((R / "deploy/monori/values.yaml").read_text())["images"]
        documents = render(R, "charts/monori", "deploy/monori/values.yaml", "monori", "monori")
        assert_monori_release_images(documents, images)
        changed = copy.deepcopy(documents)
        back = _mapping(changed[("Deployment", "monori-back")])
        pod = _mapping(_mapping(_mapping(back["spec"])["template"])["spec"])
        container = _mapping(_sequence(pod["containers"])[0])
        container["image"] = "unreviewed:latest"
        with self.assertRaisesRegex(AssertionError, "Current Monori release image differs"):
            assert_monori_release_images(changed, images)
