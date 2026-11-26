"""Offline source boundaries. No kube/credentials/workflow/model calls."""

import copy
import json
import pathlib
import subprocess
import tempfile
import unittest
from collections.abc import Mapping

import pytest
import yaml

R = pathlib.Path(__file__).resolve().parents[1]
LOCAL_STORAGE_CLAIM_PAIR_COUNT = 9
BASE = "ba7a1f34d36b12ede791269b084e5957657758ae"
HANDOFF = "c4a7c68938e36872841a1cce0f5441a5c6b78d7d"
# Independent post-handoff owners: Wiki and Monori pg-common cutovers,
# SPI egress/portable broker, and the retired LiteLLM legacy DB writer.
CUTOVERS = {
    "deploy/wiki-runtime/chart": "3c0c68dbd206138c4f4d96f5b3cafc34a8ad7141",
    "charts/monori": "093df2214564fd7db76e28da6975d267a0652431",
    "charts/spi-triage": "ca3a866c",
    "charts/litellm-infra": "61441c53",
}

# These identities now spell out the release namespace that Helm previously
# supplied implicitly. Update only the historical expectation, never the
# candidate; a missing or different current namespace must fail comparison.
EXPLICIT_NAMESPACES = {
    "charts/monori": (
        ("Deployment", "monori"),
        ("Deployment", "monori-back"),
        ("Deployment", "monori-sync"),
        ("Ingress", "monori"),
        ("Service", "back"),
        ("Service", "monori"),
        ("Service", "monori-sync"),
    ),
    "charts/spi-triage": (
        ("Deployment", "spi-queue-ui"),
        ("Deployment", "spi-triage"),
        ("Ingress", "spi-queue-ui"),
        ("NetworkPolicy", "spi-queue-ui"),
        ("NetworkPolicy", "spi-triage"),
        ("Service", "spi-queue-ui"),
        ("Service", "spi-triage"),
        ("ServiceAccount", "spi-evidence-reader"),
    ),
    "charts/format-quorum": (
        ("Deployment", "format-quorum"),
        ("Ingress", "format-quorum"),
        ("Service", "format-quorum"),
    ),
    "charts/litellm-infra": (
        ("Deployment", "litellm-branding"),
        ("Ingress", "litellm-branding"),
        ("Service", "litellm-branding"),
    ),
}


def compare_namespace_inputs(
    documents: dict[tuple[str, str], dict[str, object]], chart: str, ns: str
) -> None:
    """Apply the exact owned namespace declaration delta to the historical side only."""
    for key in EXPLICIT_NAMESPACES.get(chart, ()):
        meta = _mapping(documents[key]["metadata"])
        if "namespace" in meta:
            assert meta["namespace"] == ns
        else:
            meta["namespace"] = ns


def checkout(root: pathlib.Path, revision: str, *paths: str) -> pathlib.Path:
    """Extract only the Git inputs for an offline baseline render."""
    target = root / revision
    target.mkdir(exist_ok=True)
    archive = subprocess.check_output(["git", "-C", str(R), "archive", revision, *paths])
    subprocess.run(["tar", "-xf", "-", "-C", str(target)], input=archive, check=True)
    return target


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
    sqlite_with_retired_handoff: bool = False,
) -> dict[tuple[str, str], dict[str, object]]:
    cmd = ["helm", "template", release, str(root / chart), "-n", ns]
    if values:
        cmd += ["-f", str(root / values)]
    if sqlite_with_retired_handoff:
        cmd += ["--set", "postgresEnabled=false,pgHandoff=true"]
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


def expect_spi_cutover(
    expected: dict[tuple[str, str], dict[str, object]], *, postgres: bool
) -> None:
    """Extend the pinned SPI render by the committed storage cutover, not the live chart."""
    # The pinned render already includes the pg-common:5432 egress peer.
    deployment = _mapping(expected["Deployment", "spi-triage"]["spec"])
    pod = _mapping(_mapping(deployment["template"])["spec"])
    (guard,) = [
        g
        for g in map(_mapping, _sequence(pod["initContainers"]))
        if g["name"] == "require-existing-spi"
    ]
    # #590 adds a reviewed, storage-independent bot patch in both DB modes.
    (worker,) = [w for w in map(_mapping, _sequence(pod["containers"])) if w["name"] == "worker"]
    patch = json.loads((R / "tests/fixtures/spi-retarget-bot-init.json").read_text())
    pod["initContainers"] = [{**patch, "image": worker["image"]}, *_sequence(pod["initContainers"])]
    pod["volumes"] = [*_sequence(pod["volumes"]), {"name": "bot-base", "emptyDir": {}}]
    worker["volumeMounts"] = [*_sequence(worker["volumeMounts"]), {
        "name": "bot-base", "mountPath": "/app/telegram_delivery.py",
        "subPath": "telegram_delivery.py", "readOnly": True,
    }]
    if not postgres:
        return

    # ca3a866c wires PG credentials and CA; f927f5a4 checks both required relations.
    # Compare the rendered command as text; never execute the guard.
    pg_secret = {"secretRef": {"name": "spi-triage-postgres"}}
    ca_mount = {"name": "pg-ca", "mountPath": "/pg-ca", "readOnly": True}
    guard["envFrom"] = [pg_secret]
    guard["volumeMounts"] = [ca_mount]
    guard["args"] = [
        "\nimport os,psycopg; c=psycopg.connect(os.environ['SPI_POSTGRES_URL'],connect_timeout=5); "
        "assert c.execute(\"SELECT current_database(),to_regclass('public.jobs') IS NOT NULL,"
        "to_regclass('workflow_wait_owner') IS NOT NULL\").fetchone()==('spi_triage',True,True); "
        "c.close()"
    ]
    pod["volumes"] = [
        {"name": "pg-ca", "configMap": {"name": "pg-common-ca"}},
        *_sequence(pod["volumes"]),
    ]
    worker["envFrom"] = [*_sequence(worker["envFrom"]), pg_secret]
    mounts = _sequence(worker["volumeMounts"])
    # e4b09e31 keeps graph files accessible, not the SQLite DB at the PVC root.
    mounts[mounts.index({"name": "data", "mountPath": "/data"})] = {
        "name": "data",
        "mountPath": "/data/graphs",
        "subPath": "graphs",
    }
    worker["volumeMounts"] = [ca_mount, *mounts]
    # The static Service selector in the pinned render is already the final one.


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
    """Tests for StatefulBoundaries."""

    tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()

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
                msg = f"{chart} requires a values file"
                raise AssertionError(msg)
            image: dict[str, str] = yaml.safe_load((R / values).read_text())["image"]
            assert set(image) == {"repository", "tag", "digest"}
            assert all(isinstance(value, str) for value in image.values())
            release_image = image
        if chart == "charts/monori":
            # The owner release is independent of the placement handoff.
            # Inject only before-render inputs; retain all current-render
            # image/strategy/PVC/identity and full payload comparisons.
            if values is None:
                msg = f"{chart} requires a values file"
                raise AssertionError(msg)
            images: dict[str, dict[str, str]] = yaml.safe_load((R / values).read_text())["images"]
            assert set(images) == {"front", "back", "sync"}
            for fields in images.values():
                assert set(fields) == {"repository", "tag", "digest", "fallback"}
                assert all(isinstance(v, str) for v in fields.values())
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
            if v["name"] in [
                "data",
                "assets",
                "clang-versions",
                "tests",
                "config-history",
            ]:
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
            assert metadata.pop("annotations") == {
                "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"
            }
            assert x == old
            return
        assert key[0] == "Deployment"
        assert key[1] in allowed
        x, y = copy.deepcopy(old), copy.deepcopy(current)
        spec = y["spec"]
        assert isinstance(spec, dict)
        assert spec["replicas"] == 1
        assert spec["strategy"] == {"type": "Recreate"}
        for o in [x, y]:
            self._strip_volatile_pod_fields(o)
        assert x == y

    def test_only_intended_deployments_and_retention_annotation_change(self) -> None:

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
            (
                "charts/litellm-infra",
                None,
                "llm",
                "litellm-infra",
                {"litellm-branding"},
            ),
        ]
        for chart, values, ns, release, allowed in cases:
            with self.subTest(chart=chart):
                release_image, monori_images = self._historical_inputs(chart, values)
                paths = [chart] + ([values] if values is not None else [])

                def historical(revision: str):
                    root = checkout(pathlib.Path(self.tmp.name), revision, *paths)
                    if chart == "deploy/wiki-runtime/chart" and revision == CUTOVERS[chart]:
                        # Isolate the approved mirror update including Helm's ConfigMap checksum.
                        # Use the independent canonical source, never the actual rendered payload.
                        source = R / "deploy/platform/rancher/public-entry/files/observer_membership.py"
                        (root / chart / "files/observer_membership.py").write_bytes(source.read_bytes())
                    return render(
                        root,
                        chart,
                        values,
                        ns,
                        release,
                        release_image=release_image,
                        monori_images=monori_images,
                    )

                before = historical(BASE)
                current = render(R, chart, values, ns, release)
                if monori_images is not None:
                    assert_monori_release_images(current, monori_images)
                after = current
                if chart in CUTOVERS:
                    # The placement migration and subsequent approved changes are
                    # separate contracts. Compare *all* current documents first,
                    # without injecting historical values into the current chart.
                    expected = historical(CUTOVERS[chart])
                    if chart == "charts/monori":
                        cache = current.pop(("Job", "monori-sync-image-cache"))
                        annotations = _mapping(_mapping(cache["metadata"])["annotations"])
                        assert annotations["argocd.argoproj.io/hook"] == "PreSync"
                        assert annotations["argocd.argoproj.io/sync-wave"] == "-1"
                        cache_pod = _mapping(_mapping(_mapping(cache["spec"])["template"])["spec"])
                        sync = current[("Deployment", "monori-sync")]
                        sync_pod = _mapping(_mapping(_mapping(sync["spec"])["template"])["spec"])
                        assert cache_pod["nodeSelector"] == sync_pod["nodeSelector"]
                        assert "volumes" not in cache_pod
                        container = _mapping(_sequence(cache_pod["containers"])[0])
                        assert (
                            container["image"]
                            == _mapping(_sequence(sync_pod["containers"])[0])["image"]
                        )
                        assert container["command"] == ["python", "-I", "-S", "-c", "pass"]
                        # Schema delivery also adds a pre-rollout Job and
                        # advances only the backend init check, not placement.
                        job = current.pop(("Job", "monori-schema"))
                        annotations = _mapping(_mapping(job["metadata"])["annotations"])
                        assert annotations["argocd.argoproj.io/hook"] == "PreSync"
                        backend = expected[("Deployment", "monori-back")]
                        template = _mapping(_mapping(backend["spec"])["template"])
                        pod = _mapping(template["spec"])
                        init = _mapping(_sequence(pod["initContainers"])[0])
                        args = _sequence(init["args"])
                        args[0] = (
                            _text(args[0])
                            .replace(
                                '    assert c.execute("SELECT version_num',
                                "    marker=pathlib.Path('/app/server/postgres/revision')\n"
                                "    target=marker.read_text().strip() if marker.exists() else '0022'\n"
                                '    assert c.execute("SELECT version_num',
                            )
                            .replace("[('0021',)]", "[(target,)]")
                        )
                        init["args"] = args
                    if chart == "charts/spi-triage":
                        expect_spi_cutover(expected, postgres=True)
                    if chart == "charts/litellm-infra":
                        # fe3903c2 retired the dormant DB controller and Service;
                        # 731505f8 later retired only their dedicated PVC here.
                        for key in (
                            ("Deployment", "litellm-postgres"),
                            ("Service", "litellm-postgres"),
                            ("PersistentVolumeClaim", "litellm-postgres"),
                        ):
                            expected.pop(key, None)
                    compare_namespace_inputs(expected, chart, ns)
                    assert current == expected
                    after = historical(HANDOFF)
                else:
                    compare_namespace_inputs(before, chart, ns)
                added_identity = None
                if chart == "charts/format-quorum":
                    # A dedicated tokenless account is an intentional security
                    # hardening delta, not part of the original stateful move.
                    added_identity = ("ServiceAccount", "format-quorum")
                    service_account = _mapping(after[added_identity])
                    assert not service_account.get("automountServiceAccountToken", True)
                assert before.keys() == after.keys() - (
                    {added_identity} if added_identity else set()
                )
                for key, old in before.items():
                    if chart == "charts/format-quorum" and key == ("Ingress", "format-quorum"):
                        expected_ingress = copy.deepcopy(old)
                        labels = _mapping(expected_ingress["metadata"]).setdefault("labels", {})
                        _mapping(labels)["homelab.alchemmist.xyz/public-web"] = "true"
                        assert after[key] == expected_ingress
                        continue
                    if old != after[key]:
                        if chart == "charts/format-quorum" and key[0] == "Deployment":
                            old = copy.deepcopy(old)
                            old_pod = _mapping(_mapping(_mapping(old["spec"])["template"])["spec"])
                            current_pod = _mapping(
                                _mapping(_mapping(after[key]["spec"])["template"])["spec"]
                            )
                            assert current_pod.get("serviceAccountName") == "format-quorum"
                            assert not current_pod.get("automountServiceAccountToken", True)
                            old_pod["serviceAccountName"] = "format-quorum"
                            old_pod["automountServiceAccountToken"] = False
                        self._assert_changed_document(key, old, after[key], allowed)

    def test_spi_sqlite_guard_and_retired_handoff_route(self) -> None:
        chart, values = "charts/spi-triage", "deploy/spi-triage/values.yaml"
        revision = CUTOVERS[chart]
        pinned = checkout(pathlib.Path(self.tmp.name), revision, chart, values)
        image, _ = self._historical_inputs(chart, values)
        expected = render(pinned, chart, values, "automation", "spi-triage", release_image=image)
        expect_spi_cutover(expected, postgres=False)
        compare_namespace_inputs(expected, chart, "automation")
        # f927f5a4 retires the handoff Service target, even with the old flag set.
        current = render(
            R,
            chart,
            values,
            "automation",
            "spi-triage",
            sqlite_with_retired_handoff=True,
        )
        assert current == expected

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
        for path in [
            "deploy/wiki-runtime/values.yaml",
            "deploy/format-quorum/values.yaml",
        ]:
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
    """Tests for CurrentMonoriRelease."""

    def test_current_image_mutation_is_not_hidden_by_historical_input(self) -> None:
        images = yaml.safe_load((R / "deploy/monori/values.yaml").read_text())["images"]
        documents = render(R, "charts/monori", "deploy/monori/values.yaml", "monori", "monori")
        assert_monori_release_images(documents, images)
        changed = copy.deepcopy(documents)
        back = _mapping(changed[("Deployment", "monori-back")])
        pod = _mapping(_mapping(_mapping(back["spec"])["template"])["spec"])
        container = _mapping(_sequence(pod["containers"])[0])
        container["image"] = "unreviewed:latest"
        with pytest.raises(AssertionError, match="Current Monori release image differs"):
            assert_monori_release_images(changed, images)
