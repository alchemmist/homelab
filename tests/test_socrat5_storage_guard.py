"""Fail closed when the owned socrat-5 local storage admission guard drifts."""

import copy
import importlib.util
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / "scripts/socrat5-storage-guard.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class StorageGuardTests(unittest.TestCase):
    """Check the owned admission documents and worker bootstrap stay fail-closed."""

    def setUp(self) -> None:
        self.docs = list(
            yaml.safe_load_all((ROOT / "deploy/admission/socrat5-local-storage.yaml").read_text())
        )

    def test_fail_closed_owned_boundary(self) -> None:
        """Require Fail, Deny, and the owned policy name."""
        assert self.docs[0]["spec"]["failurePolicy"] == "Fail"
        assert self.docs[1]["spec"]["validationActions"] == ["Deny"]
        assert self.docs[1]["spec"]["policyName"] == g.NAME

    def test_only_known_api_defaults_ignored(self) -> None:
        """Allow Kubernetes defaults that the guard canonicalizes away."""
        p = copy.deepcopy(self.docs[0])
        p["spec"]["matchConstraints"].update(
            matchPolicy="Equivalent", namespaceSelector={}, objectSelector={}
        )
        p["spec"]["matchConstraints"]["resourceRules"][0]["scope"] = "*"
        g.validate_existing(self.docs[0], p)

    def test_foreign_object_refused(self) -> None:
        """Refuse a document whose owner label was removed."""
        p = copy.deepcopy(self.docs[0])
        p["metadata"]["labels"].clear()
        with self.assertRaises(ValueError):
            g.validate_existing(self.docs[0], p)

    def test_narrowing_selector_drift_is_not_ignored(self) -> None:
        """Refuse a namespace selector that drops existing objects."""
        p = copy.deepcopy(self.docs[0])
        p["spec"]["matchConstraints"]["namespaceSelector"] = {"matchLabels": {"skip": "most"}}
        with self.assertRaises(ValueError):
            g.validate_existing(self.docs[0], p)

    def test_weakened_binding_refused(self) -> None:
        """Refuse a binding that warns instead of denying."""
        p = copy.deepcopy(self.docs[1])
        p["spec"]["validationActions"] = ["Warn"]
        with self.assertRaises(ValueError):
            g.validate_existing(self.docs[1], p)

    def test_existing_workers_keep_default_taint_template(self) -> None:
        """Keep the worker taint default in the k3s worker template."""
        text = (ROOT / "ansible/roles/k3s_worker/templates/config.yaml.j2").read_text()
        assert "k3s_worker_taints | default([k3s_worker_bootstrap_taint])" in text

    def test_overlay_guard_is_part_of_worker_bootstrap(self) -> None:
        """Run the overlay marks role before the worker and require its service."""
        play = yaml.safe_load((ROOT / "ansible/playbooks/socrat-5-worker.yml").read_text())[0]
        assert play["roles"] == ["k3s_overlay_marks", "k3s_worker"]
        assert "Requires=homelab-k3s-overlay-marks.service" in str(play["post_tasks"])
