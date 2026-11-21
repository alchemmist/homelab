"""Offline source boundaries. No kube/credentials/workflow/model calls."""

import copy, pathlib, subprocess, tempfile, unittest, yaml

R = pathlib.Path(__file__).resolve().parents[1]
BASE = "ba7a1f34"


def render(
    root,
    chart,
    values,
    ns,
    release,
    *,
    release_image: dict[str, str] | None = None,
    monori_images: dict[str, dict[str, str]] | None = None,
):
    """Document this test or helper."""
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


def assert_monori_release_images(documents, images):
    """Document this test or helper."""
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
        pod = matches[0]["spec"]["template"]["spec"]
        for container in pod["containers"] + pod.get("initContainers", []):
            assert container["image"] == expected, "Current Monori release image differs"


class StatefulBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Document this test or helper."""
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
    def tearDownClass(cls):
        """Document this test or helper."""
        cls.tmp.cleanup()

    def test_only_intended_deployments_and_retention_annotation_change(self):
        """Document this test or helper."""
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
                    self.assertEqual(set(release_image), {"repository", "tag", "digest"})
                    self.assertTrue(all(isinstance(value, str) for value in release_image.values()))
                if chart == "charts/monori":
                    # The owner release is independent of the placement handoff.
                    # Inject only before-render inputs; retain all current-render
                    # image/strategy/PVC/identity and full payload comparisons.
                    monori_images = yaml.safe_load((R / values).read_text())["images"]
                    self.assertEqual(set(monori_images), {"front", "back", "sync"})
                    for fields in monori_images.values():
                        self.assertEqual(set(fields), {"repository", "tag", "digest", "fallback"})
                        self.assertTrue(all(isinstance(v, str) for v in fields.values()))
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
                self.assertEqual(set(a), set(b))
                for k in a:
                    if a[k] == b[k]:
                        continue
                    if k == ("PersistentVolumeClaim", "litellm-branding"):
                        x = copy.deepcopy(b[k])
                        x["metadata"].pop("annotations", None)
                        self.assertEqual(x, a[k])
                        continue
                    self.assertEqual(k[0], "Deployment")
                    self.assertIn(k[1], allowed)
                    x, y = copy.deepcopy(a[k]), copy.deepcopy(b[k])
                    self.assertEqual(y["spec"]["replicas"], 1)
                    self.assertEqual(y["spec"]["strategy"], {"type": "Recreate"})
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
                    self.assertEqual(x, y)

    def test_all_new_claims_are_prebound_local_retained_and_node5_only(self):
        """Document this test or helper."""
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
            for pv, pvc in zip(docs[::2], docs[1::2]):
                count += 1
                self.assertEqual(pv["spec"]["persistentVolumeReclaimPolicy"], "Retain")
                self.assertTrue(pv["spec"]["local"]["path"].startswith("/mnt/files/homelab/"))
                self.assertEqual(pvc["spec"]["volumeName"], pv["metadata"]["name"])
                self.assertEqual(pvc["spec"]["storageClassName"], "")
                self.assertEqual(
                    pv["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"][0][
                        "matchExpressions"
                    ][0]["values"],
                    ["socrat-5"],
                )
        self.assertEqual(count, 9)

    def test_no_paused_ingress_or_zero_replica_left_in_final_sources(self):
        """Document this test or helper."""
        spi = yaml.safe_load((R / "deploy/spi-triage/values.yaml").read_text())
        self.assertFalse(spi["maintenanceIngressPaused"])
        self.assertEqual(spi["workerReplicas"], 1)
        mono = yaml.safe_load((R / "deploy/monori/values.yaml").read_text())
        self.assertEqual(mono["backReplicaCount"], 1)
        self.assertEqual(mono["syncReplicaCount"], 1)
        self.assertTrue(mono["statefulRecreate"])
        for path in ["deploy/wiki-runtime/values.yaml", "deploy/format-quorum/values.yaml"]:
            self.assertEqual(yaml.safe_load((R / path).read_text())["replicaCount"], 1)
        legacy = (R / "ansible/playbooks/format-quorum.yml").read_text()
        self.assertNotIn("helm upgrade", legacy)
        self.assertNotIn("pacman", legacy)
        self.assertIn("argocd.argoproj.io/refresh=hard", legacy)

    def test_idle_controller_never_runs_or_cancels_a_business_job(self):
        """Document this test or helper."""
        s = (R / "scripts/vm105-spi-idle-handoff.py").read_text()
        for word in [
            "/claim",
            "/analyze",
            "/publish",
            "/operator/queue/cancel",
            "--force",
            "--grace-period=0",
        ]:
            self.assertNotIn(word, s)
        for word in [
            "finally:",
            "newWorkWonRaceRestoringImmediately",
            "liveOwners",
            "liveLinkLeases",
            "skip-reconcile-",
        ]:
            self.assertIn(word, s)


if __name__ == "__main__":
    unittest.main()


class CurrentMonoriRelease(unittest.TestCase):
    def test_current_image_mutation_is_not_hidden_by_historical_input(self):
        """Document this test or helper."""
        images = yaml.safe_load((R / "deploy/monori/values.yaml").read_text())["images"]
        documents = render(R, "charts/monori", "deploy/monori/values.yaml", "monori", "monori")
        assert_monori_release_images(documents, images)
        changed = copy.deepcopy(documents)
        changed[("Deployment", "monori-back")]["spec"]["template"]["spec"]["containers"][0][
            "image"
        ] = "unreviewed:latest"
        with self.assertRaisesRegex(AssertionError, "Current Monori release image differs"):
            assert_monori_release_images(changed, images)
