"""Tests for the container resource policy rollout."""

import copy
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict, cast
from unittest.mock import Mock, patch

PATH = (
    Path(__file__).resolve().parents[1]
    / "ansible/roles/container_resource_policy/files/reconcile_pods.py"
)
SPEC = importlib.util.spec_from_file_location("reconcile_pods", PATH)
ROLLOUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROLLOUT)


class OwnerRef(TypedDict, total=False):
    """Owner reference entry of a pod manifest."""

    uid: str
    kind: str
    controller: bool
    name: str


class Metadata(TypedDict):
    """Standard pod metadata block."""

    name: str
    namespace: str
    uid: str
    ownerReferences: list[OwnerRef]


class ProfileResources(TypedDict, total=False):
    """Per-container requests and limits with optional CPU removal."""

    requests: dict[str, str]
    limits: dict[str, str]
    removeCpuLimit: bool


class Container(TypedDict):
    """One named container with its resource block."""

    name: str
    resources: ProfileResources


class PodSpec(TypedDict, total=False):
    """Pod scheduling spec keys exercised by the reconciler."""

    nodeName: str
    nodeSelector: dict[str, str]
    containers: list[Container]
    initContainers: list[dict[str, object]]


class PodStatus(TypedDict, total=False):
    """Runtime phase and conditions of a pod."""

    phase: str
    conditions: list[dict[str, str]]


class Pod(TypedDict):
    """A rendered pod manifest."""

    metadata: Metadata
    spec: PodSpec
    status: PodStatus


class PolicyProfile(TypedDict, total=False):
    """One committed resource policy profile."""

    namespace: str
    ownerKind: str
    ownerPattern: str
    containers: dict[str, ProfileResources]
    nodeSelector: dict[str, str]


def pod(
    uid: str = "old",
    kind: str = "ReplicaSet",
    node: str = "socrat-1",
    *,
    compliant: bool = False,
) -> Pod:
    """Build one pod manifest with the requested compliance and placement."""
    limits = (
        {"cpu": "500m", "memory": "512Mi", "ephemeral-storage": "1Gi"}
        if compliant
        else {"cpu": "500m"}
    )
    return {
        "metadata": {
            "name": uid,
            "namespace": "test",
            "uid": uid,
            "ownerReferences": [{"uid": "owner", "kind": kind, "controller": True}],
        },
        "spec": {
            "nodeName": node,
            "containers": [
                {
                    "name": "main",
                    "resources": {
                        "limits": limits,
                        "requests": {
                            "cpu": "100m",
                            "memory": "128Mi",
                            "ephemeral-storage": "16Mi",
                        }
                        if compliant
                        else {},
                    },
                }
            ],
        },
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }


def profile() -> PolicyProfile:
    """Return the committed compliant profile used by the contracts."""
    return {
        "namespace": "test",
        "ownerKind": "ReplicaSet",
        "ownerPattern": "^app-.*$",
        "containers": {
            "main": {
                "requests": {
                    "cpu": "250m",
                    "memory": "256Mi",
                    "ephemeral-storage": "512Mi",
                },
                "limits": {
                    "cpu": "500m",
                    "memory": "512Mi",
                    "ephemeral-storage": "1Gi",
                },
            }
        },
    }


def profiled_pod() -> Pod:
    """Build a pod that already satisfies the committed profile."""
    value = pod(compliant=True)
    value["metadata"]["ownerReferences"][0]["name"] = "app-abcd"
    value["spec"]["containers"][0]["resources"] = copy.deepcopy(profile()["containers"]["main"])
    return value


class RolloutTests(unittest.TestCase):
    """Check container resource rollout reconciliation decisions."""

    def test_profile_node_selector_requires_reconciliation_when_missing_or_different(
        self,
    ) -> None:
        """Profile node selector requires reconciliation when missing or different."""
        expected = dict(profile(), nodeSelector={"kubernetes.io/hostname": "socrat-1"})
        for selector in ({}, {"kubernetes.io/hostname": "socrat-2"}):
            value = profiled_pod()
            value["spec"]["nodeSelector"] = selector
            self.assertIn(
                "nodeSelector/kubernetes.io/hostname",
                ROLLOUT.profile_mismatches(value, expected),
            )
            self.assertTrue(ROLLOUT.needs_reconcile(value, [expected]))

    def test_profile_node_selector_preserves_unrelated_labels(self) -> None:
        """Profile node selector preserves unrelated labels."""
        expected = dict(profile(), nodeSelector={"kubernetes.io/hostname": "socrat-1"})
        value = profiled_pod()
        value["spec"]["nodeSelector"] = {
            "kubernetes.io/hostname": "socrat-1",
            "kubernetes.io/os": "linux",
        }
        before = copy.deepcopy(value)
        self.assertFalse(ROLLOUT.needs_reconcile(value, [expected]))
        self.assertEqual(value, before)

    def test_profile_node_selector_detects_bound_wrong_node(self) -> None:
        """Profile node selector detects bound wrong node."""
        expected = dict(profile(), nodeSelector={"kubernetes.io/hostname": "socrat-1"})
        value = profiled_pod()
        selector = expected["nodeSelector"]
        assert isinstance(selector, dict)
        value["spec"]["nodeSelector"] = selector
        value["spec"]["nodeName"] = "socrat-2"
        self.assertIn("nodeName", ROLLOUT.profile_mismatches(value, expected))
        del value["spec"]["nodeName"]
        self.assertFalse(ROLLOUT.needs_reconcile(value, [expected]))

    def test_profile_without_placement_does_not_reconcile_node(self) -> None:
        """Profile without placement does not reconcile node."""
        value = profiled_pod()
        value["spec"]["nodeName"] = "socrat-2"
        value["spec"]["nodeSelector"] = {"custom": "unchanged"}
        for expected in (profile(), dict(profile(), nodeSelector={})):
            self.assertFalse(ROLLOUT.needs_reconcile(value, [expected]))

    def test_node_selector_schema_accepts_literal_labels(self) -> None:
        """Node selector schema accepts literal labels."""
        for selector in (
            {},
            {"kubernetes.io/hostname": "socrat-1"},
            {"pool": "", "example.com/rack": "Rack_1.2"},
        ):
            expected = dict(profile(), nodeSelector=selector)
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as source:
                json.dump([expected], source)
                source.flush()
                self.assertEqual(ROLLOUT.load_profiles(source.name), [expected])

    def test_node_selector_schema_rejects_invalid_maps_and_labels(self) -> None:
        """Node selector schema rejects invalid maps and labels."""
        for selector in cast(
            "tuple[object, ...]",
            (
                None,
                [],
                "socrat-1",
                {"node": 1},
                {"": "value"},
                {"/node": "value"},
                {"UPPER.com/node": "value"},
                {"a/b/c": "value"},
                {"node": "*"},
                {"node": "a" * 64},
                {"a" * 64: "value"},
                {"node": "socrat 1"},
            ),
        ):
            with self.subTest(selector=selector):
                with self.assertRaisesRegex(ValueError, "nodeSelector"):
                    ROLLOUT.validate_node_selector(selector)

    def test_excluded_nodes_remain_visible_but_not_actionable(self) -> None:
        """Excluded nodes remain visible but not actionable."""
        values = [pod(), pod("excluded", node="socrat-3")]
        output = io.StringIO()
        with redirect_stdout(output):
            actionable = ROLLOUT.audit(values, {"socrat-3"})
        self.assertEqual([value["metadata"]["uid"] for value in actionable], ["old"])
        summary = json.loads(output.getvalue().splitlines()[-1])["summary"]
        self.assertEqual(summary["deficient"], 2)
        self.assertEqual(summary["actionable_deficient"], 1)
        self.assertEqual(summary["excluded_deficient"], 1)

    def test_no_exclusions_remains_strict(self) -> None:
        """No exclusions remains strict."""
        values = [pod(), pod("other", node="socrat-3")]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ROLLOUT.audit(values), values)

    def test_profile_matches_namespace_owner_kind_and_regex(self) -> None:
        """Profile matches namespace owner kind and regex."""
        value, expected = profiled_pod(), profile()
        self.assertEqual(ROLLOUT.matching_profile(value, [expected]), expected)
        for field, different in [
            ("namespace", "other"),
            ("ownerKind", "DaemonSet"),
            ("ownerPattern", "other-.*"),
        ]:
            changed = dict(expected, **{field: different})
            self.assertIsNone(ROLLOUT.matching_profile(value, [changed]))

    def test_ambiguous_profiles_fail_even_for_already_compliant_pod(self) -> None:
        """Ambiguous profiles fail even for already compliant pod."""
        with self.assertRaisesRegex(RuntimeError, "Ambiguous"):
            ROLLOUT.audit([profiled_pod()], profiles=[profile(), profile()])

    def test_equivalent_units_do_not_require_reconciliation(self) -> None:
        """Equivalent units do not require reconciliation."""
        value = profiled_pod()
        resources = value["spec"]["containers"][0]["resources"]
        resources["limits"]["cpu"] = "0.5"
        resources["limits"]["ephemeral-storage"] = "1024Mi"
        self.assertFalse(ROLLOUT.needs_reconcile(value, [profile()]))
        self.assertEqual(ROLLOUT.quantity("1"), ROLLOUT.quantity("1000m"))
        self.assertEqual(ROLLOUT.quantity("1Gi"), ROLLOUT.quantity("1024Mi"))
        self.assertEqual(ROLLOUT.quantity("1e3"), ROLLOUT.quantity("1k"))

    def test_changed_requests_and_limits_require_reconciliation(self) -> None:
        """Changed requests and limits require reconciliation."""
        for mode in ("requests", "limits"):
            value = profiled_pod()
            cast("dict[str, dict[str, str]]", value["spec"]["containers"][0]["resources"])[mode][
                "cpu"
            ] = "1"
            self.assertTrue(ROLLOUT.needs_reconcile(value, [profile()]))
            self.assertIn(
                "containers/main/" + mode + "/cpu",
                ROLLOUT.profile_mismatches(value, profile()),
            )

    def test_gpu_and_custom_resources_are_ignored(self) -> None:
        """Gpu and custom resources are ignored."""
        value = profiled_pod()
        value["spec"]["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] = "1"
        value["spec"]["containers"][0]["resources"]["requests"]["example.com/device"] = "1"
        before = copy.deepcopy(value)
        self.assertFalse(ROLLOUT.needs_reconcile(value, [profile()]))
        self.assertEqual(value, before)

    def test_unknown_workload_is_reported_in_profile_coverage(self) -> None:
        """Unknown workload is reported in profile coverage."""
        value = pod(compliant=True)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(ROLLOUT.audit([value], profiles=[profile()]), [])
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["profile"], "unmatched")
        self.assertEqual(lines[-1]["summary"]["unprofiled_active"], 1)

    def test_ready_replacement_with_stale_profile_times_out(self) -> None:
        """Ready replacement with stale profile times out."""
        old = profiled_pod()
        old["spec"]["containers"][0]["resources"]["limits"]["cpu"] = "1"
        new = copy.deepcopy(old)
        new["metadata"]["uid"] = "new"
        client = Mock()
        client.pods.side_effect = [[old], [new]]
        client.evict.return_value = SimpleNamespace(returncode=0)
        with (
            patch.object(ROLLOUT.time, "monotonic", side_effect=[0, 0, 0, 11]),
            patch.object(ROLLOUT.time, "sleep"),self.assertRaisesRegex(TimeoutError, "Replacement")
        ):
            ROLLOUT.reconcile_one(client, old, 10, 0.01, [profile()])

    def test_unlimited_profile_accepts_absent_cpu_limit(self) -> None:
        """Unlimited profile accepts absent cpu limit."""
        expected, value = profile(), profiled_pod()
        expected["containers"]["main"]["removeCpuLimit"] = True
        del expected["containers"]["main"]["limits"]["cpu"]
        del value["spec"]["containers"][0]["resources"]["limits"]["cpu"]
        self.assertFalse(ROLLOUT.needs_reconcile(value, [expected]))

    def test_unlimited_profile_detects_existing_cpu_limit_including_zero(self) -> None:
        """Unlimited profile detects existing cpu limit including zero."""
        expected = profile()
        expected["containers"]["main"]["removeCpuLimit"] = True
        del expected["containers"]["main"]["limits"]["cpu"]
        for limit in ("2", "0"):
            value = profiled_pod()
            value["spec"]["containers"][0]["resources"]["limits"]["cpu"] = limit
            self.assertIn(
                "containers/main/limits/cpu-present",
                ROLLOUT.profile_mismatches(value, expected),
            )

    def test_unknown_workload_needs_requests_but_not_cpu_limit(self) -> None:
        """Unknown workload needs requests but not cpu limit."""
        value = pod(compliant=True)
        del value["spec"]["containers"][0]["resources"]["limits"]["cpu"]
        self.assertFalse(ROLLOUT.needs_reconcile(value))
        del value["spec"]["containers"][0]["resources"]["requests"]["memory"]
        self.assertTrue(ROLLOUT.needs_reconcile(value))

    def test_profile_schema_validates_selective_limits(self) -> None:
        """Profile schema validates selective limits."""
        expected = profile()
        expected["containers"]["main"]["removeCpuLimit"] = True
        del expected["containers"]["main"]["limits"]["cpu"]
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as source:
            json.dump([expected], source)
            source.flush()
            self.assertEqual(ROLLOUT.load_profiles(source.name), [expected])

    def test_profile_schema_rejects_ambiguous_limit_intent_and_unanchored_regex(
        self,
    ) -> None:
        """Profile schema rejects ambiguous limit intent and unanchored regex."""
        cases = []
        conflict = profile()
        conflict["containers"]["main"]["removeCpuLimit"] = True
        cases.append(conflict)
        absent = profile()
        del absent["containers"]["main"]["limits"]["cpu"]
        cases.append(absent)
        unanchored = profile()
        unanchored["ownerPattern"] = "app-.*"
        cases.append(unanchored)
        excessive = profile()
        excessive["containers"]["main"]["requests"]["memory"] = "2Gi"
        cases.append(excessive)
        for expected in cases:
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as source:
                json.dump([expected], source)
                source.flush()
                with self.assertRaises(ValueError):
                    ROLLOUT.load_profiles(source.name)

    def test_profile_template_casts_mixed_resource_values_individually(self) -> None:
        """Profile template casts mixed resource values individually."""
        try:
            import jinja2
            import yaml
        except ImportError:
            self.skipTest("Jinja2 and PyYAML are required for template rendering")
        role = PATH.parent.parent
        expected = profile()
        expected["containers"]["main"]["removeCpuLimit"] = True
        del expected["containers"]["main"]["limits"]["cpu"]
        variables = yaml.safe_load((role / "defaults/main.yml").read_text())
        expected["nodeSelector"] = {"kubernetes.io/hostname": "socrat-1"}
        variables["container_resource_policy_profiles"] = [expected, profile()]
        environment = jinja2.Environment(loader=jinja2.FileSystemLoader(str(role / "templates")))
        environment.filters["to_json"] = json.dumps
        rendered = environment.get_template("resource-policy.yaml.j2").render(**variables)
        policy = yaml.safe_load(rendered)
        expression = policy["spec"]["variables"][0]["expression"]
        self.assertIn('"removeCpuLimit": dyn(true)', expression)
        self.assertIn('"requests": dyn({', expression)
        self.assertIn('"limits": dyn({', expression)
        self.assertIn('"nodeSelector": dyn({"kubernetes.io/hostname": "socrat-1"})', expression)
        self.assertIn('"nodeSelector": dyn({})', expression)
        removal = policy["spec"]["mutations"][0]["jsonPatch"]["expression"]
        self.assertIn("variables.profileNodeSelector.size() == 0 ? []", removal)
        self.assertIn("!has(object.spec.nodeSelector)", removal)
        self.assertIn("jsonpatch.escapeKey(key)", removal)
        self.assertEqual(
            removal.count('quantity(c.resources.limits["cpu"]).compareTo(quantity("0")) == 0'),
            2,
        )
        self.assertEqual(
            [mutation["patchType"] for mutation in policy["spec"]["mutations"]],
            ["JSONPatch", "ApplyConfiguration"],
        )

    def test_role_rolls_back_validation_failures_before_evictions(self) -> None:
        """Role rolls back validation failures before evictions."""
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is required for role validation")
        tasks = yaml.safe_load((PATH.parent.parent / "tasks/main.yml").read_text())
        activation = next(task for task in tasks if "block" in task)
        self.assertEqual(len(activation["rescue"]), 3)
        self.assertEqual(
            activation["rescue"][-1]["ansible.builtin.fail"]["msg"].split(";")[0],
            "Admission validation failed",
        )
        self.assertTrue(all("reconcile_pods.py" not in str(task) for task in activation["block"]))
        self.assertTrue(all("retries" not in task for task in activation["block"]))
        names = [task["name"] for task in tasks]
        self.assertLess(
            names.index("Read current admission configuration for rollback"),
            names.index(activation["name"]),
        )
        self.assertLess(
            names.index(activation["name"]),
            names.index("Reconcile existing pods when explicitly enabled"),
        )

    def test_positive_quantities(self) -> None:
        """Positive quantities."""
        for value in ("1", "500m", "1Gi", "1e3", "1E-3", "0.001", "10Ki"):
            self.assertTrue(ROLLOUT.positive(value), value)
        for invalid in (None, "0", "0Mi", "-1", "NaN", "bad", "0.0"):
            self.assertFalse(ROLLOUT.positive(invalid), invalid)

    def test_limits_check_includes_init_containers(self) -> None:
        """Limits check includes init containers."""
        value = pod(compliant=True)
        value["spec"]["initContainers"] = [{"name": "init"}]
        self.assertEqual(len(ROLLOUT.deficits(value)), 5)

    def test_does_not_change_existing_resources(self) -> None:
        """Does not change existing resources."""
        value = pod()
        original = copy.deepcopy(value)
        ROLLOUT.deficits(value)
        payload = ROLLOUT.eviction_payload(value)
        self.assertEqual(value, original)
        self.assertEqual(payload["deleteOptions"]["preconditions"], {"uid": "old"})
        self.assertNotIn("spec", payload)

    def test_unsupported_owners(self) -> None:
        """Unsupported owners."""
        self.assertFalse(ROLLOUT.supported(pod(kind="Job")))
        value = pod()
        value["metadata"]["ownerReferences"] = []
        self.assertFalse(ROLLOUT.supported(value))
        value["status"]["phase"] = "Succeeded"
        self.assertFalse(ROLLOUT.active(value))

    def test_daemonset_requires_same_node(self) -> None:
        """Daemonset requires same node."""
        self.assertFalse(
            ROLLOUT.same_workload(
                pod(kind="DaemonSet"), pod("new", kind="DaemonSet", node="socrat-2")
            )
        )
        self.assertTrue(ROLLOUT.same_workload(pod(kind="DaemonSet"), pod("new", kind="DaemonSet")))

    def test_statefulset_requires_same_name(self) -> None:
        """Statefulset requires same name."""
        self.assertFalse(
            ROLLOUT.same_workload(pod(kind="StatefulSet"), pod("new", kind="StatefulSet"))
        )

    def test_waits_for_new_ready_pod_and_old_deletion(self) -> None:
        """Waits for new ready pod and old deletion."""
        old = pod()
        new = pod("new", compliant=True)
        existing = pod("existing", compliant=True)
        unready = copy.deepcopy(new)
        unready["status"]["conditions"] = []
        client = Mock()
        client.pods.side_effect = [
            [old, existing],
            [old, existing, new],
            [existing, unready],
            [existing, new],
        ]
        client.evict.return_value = SimpleNamespace(returncode=0)
        with patch.object(ROLLOUT.time, "sleep") as sleep:
            ROLLOUT.reconcile_one(client, old, 10, 0.01)
        self.assertEqual(sleep.call_count, 2)
        client.evict.assert_called_once_with(old)

    def test_retries_disruption_budget(self) -> None:
        """Retries disruption budget."""
        old, new = pod(), pod("new", compliant=True)
        client = Mock()
        client.pods.side_effect = [[old], [new]]
        client.evict.side_effect = [
            SimpleNamespace(returncode=1, stderr="TooManyRequests", stdout=""),
            SimpleNamespace(returncode=0),
        ]
        with patch.object(ROLLOUT.time, "sleep"):
            ROLLOUT.reconcile_one(client, old, 10, 0.01)
        self.assertEqual(client.evict.call_count, 2)

    def test_stops_on_eviction_error(self) -> None:
        """Stops on eviction error."""
        old = pod()
        client = Mock()
        client.pods.return_value = [old]
        client.evict.return_value = SimpleNamespace(returncode=1, stderr="Forbidden", stdout="")
        with self.assertRaisesRegex(RuntimeError, "Forbidden"):
            ROLLOUT.reconcile_one(client, old, 10, 0.01)

    def test_existing_ready_replica_does_not_count_as_replacement(self) -> None:
        """Existing ready replica does not count as replacement."""
        old, existing = pod(), pod("existing", compliant=True)
        client = Mock()
        client.pods.side_effect = [[old, existing], [existing]]
        client.evict.return_value = SimpleNamespace(returncode=0)
        with (
            patch.object(ROLLOUT.time, "monotonic", side_effect=[0, 0, 0, 11]),
            patch.object(ROLLOUT.time, "sleep"),self.assertRaisesRegex(TimeoutError, "Replacement")
        ):
            ROLLOUT.reconcile_one(client, old, 10, 0.01)

    def test_ready_replacement_without_limits_times_out(self) -> None:
        """Ready replacement without limits times out."""
        old, new = pod(), pod("new")
        client = Mock()
        client.pods.side_effect = [[old], [new]]
        client.evict.return_value = SimpleNamespace(returncode=0)
        with (
            patch.object(ROLLOUT.time, "monotonic", side_effect=[0, 0, 0, 11]),
            patch.object(ROLLOUT.time, "sleep"),self.assertRaisesRegex(TimeoutError, "Replacement")
        ):
            ROLLOUT.reconcile_one(client, old, 10, 0.01)

    def test_eviction_uses_stdin_and_uid(self) -> None:
        """Eviction uses stdin and uid."""
        client = ROLLOUT.Client("kubectl", "/config")
        with patch.object(ROLLOUT.subprocess, "run") as run:
            client.evict(pod())
        args, kwargs = run.call_args
        self.assertIn("/api/v1/namespaces/test/pods/old/eviction", args[0])
        self.assertEqual(
            json.loads(kwargs["input"])["deleteOptions"]["preconditions"]["uid"], "old"
        )


if __name__ == "__main__":
    unittest.main()
