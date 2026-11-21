"""Offline infrastructure contract checks using copied fixtures, never live hosts."""

import ast
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "infra_contract", ROOT / "scripts/check_infrastructure_contracts.py"
)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


class InfrastructureContracts(unittest.TestCase):
    """Drift rejection for mesh, issuer, inventory, and fixed-relay contracts."""

    def test_registered_consumers_and_mesh(self) -> None:
        """Accept the canonical repository contract set unchanged."""
        self.assertEqual(contract.check(ROOT), 10)

    def test_openhands_issuer_consumer_is_exact_and_refuses_drift(self) -> None:
        """Review the sole additive consumer and reject IP/scope drift in copied files."""
        configuration = json.loads((ROOT / "deploy/contracts/infrastructure.json").read_text())
        matches = [
            row
            for row in configuration["issuerTransport"]["consumers"]
            if row["file"] == "deploy/openhands/values.yaml"
        ]
        self.assertEqual(
            matches, [{"file": "deploy/openhands/values.yaml", "path": ["oidc", "hostAliases"]}]
        )
        for violation in ("ip", "scope"):
            with self.subTest(violation=violation), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory)
                target = root / "deploy/openhands/values.yaml"
                text = target.read_text()
                if violation == "ip":
                    text = text.replace("10.43.218.222", "10.43.218.223")
                else:
                    text = text.replace(
                        "[auth.socrat.alchemmist.xyz]",
                        "[auth.socrat.alchemmist.xyz, unrelated.example]",
                    )
                self.assertNotEqual(text, target.read_text())
                target.write_text(text)
                with self.assertRaises(ValueError):
                    contract.check(root)

    def fixture(self, directory):
        root = Path(directory)
        c = json.loads((ROOT / "deploy/contracts/infrastructure.json").read_text())
        names = ["deploy/contracts/infrastructure.json", c["meshRegistry"], c["ansibleInventory"]]
        names += [x["file"] for x in c["issuerTransport"]["consumers"]]
        names += [
            c["relayContract"][k]
            for k in [
                "relayScript",
                "endpointScript",
                "frontHostVars",
                "targetHostVars",
                "serviceFile",
                "installPlaybook",
            ]
        ]
        for name in names:
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, p)
        return root

    def test_drift_rejected_and_generation_only_changes_ip(self) -> None:
        """Reject issuer IP drift and restore the original bytes on write."""
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root / "deploy/platform/rancher/values.yaml"
            original = p.read_text()
            p.write_text(original.replace("10.43.218.222", "10.43.218.223"))
            with self.assertRaisesRegex(ValueError, "Issuer IP drift"):
                contract.check(root)
            contract.check(root, write=True)
            self.assertEqual(p.read_text(), original)

    def test_late_scope_error_leaves_earlier_drifted_files_untouched(self) -> None:
        """Leave earlier files untouched when a later scope error aborts a write."""
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            c = json.loads((root / "deploy/contracts/infrastructure.json").read_text())
            first = root / c["issuerTransport"]["consumers"][0]["file"]
            first.write_text(first.read_text().replace("10.43.218.222", "10.43.218.223"))
            last = root / c["issuerTransport"]["consumers"][-1]["file"]
            last.write_text(
                last.read_text().replace(
                    "[auth.socrat.alchemmist.xyz]", "[auth.socrat.alchemmist.xyz, other.example]"
                )
            )
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "scope widened"):
                contract.check(root, write=True)
            self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_multiple_registered_scalars_in_one_file_are_preserved(self) -> None:
        """Preserve every registered scalar when one file contains an alias block."""
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            config = root / "deploy/contracts/infrastructure.json"
            c = json.loads(config.read_text())
            first = c["issuerTransport"]["consumers"][0]
            p = root / first["file"]
            source = p.read_text()
            ends = [
                token
                for token in yaml.scan(source)
                if isinstance(token, yaml.tokens.DocumentEndToken)
            ]
            self.assertLessEqual(len(ends), 1)
            insertion = ends[0].start_mark.index if ends else len(source)
            expected = (
                source[:insertion]
                + "\ncontractTestAliases:\n  - ip: 10.43.218.222\n    hostnames: [auth.socrat.alchemmist.xyz]\n"
                + source[insertion:]
            )
            self.assertEqual(len(list(yaml.compose_all(expected))), 1)
            p.write_text(expected.replace("10.43.218.222", "10.43.218.223"))
            c["issuerTransport"]["consumers"].append(
                {"file": first["file"], "path": ["contractTestAliases"]}
            )
            config.write_text(json.dumps(c))
            self.assertEqual(contract.check(root, write=True), 11)
            self.assertEqual(p.read_text(), expected)

    def test_scope_widening_not_regenerated(self) -> None:
        """Refuse to regenerate a hostname list that gained an extra name."""
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root / "deploy/platform/rancher/values.yaml"
            p.write_text(
                p.read_text().replace(
                    "[auth.socrat.alchemmist.xyz]", "[auth.socrat.alchemmist.xyz, other.example]"
                )
            )
            with self.assertRaisesRegex(ValueError, "scope widened"):
                contract.check(root, write=True)

    def test_inventory_drift_rejected(self) -> None:
        """Reject an inventory address that no longer matches the mesh registry."""
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root / "ansible/inventory/hosts.yml"
            p.write_text(
                p.read_text().replace("ansible_host: 10.250.0.41", "ansible_host: 10.250.0.99")
            )
            with self.assertRaisesRegex(ValueError, "Inventory endpoint drift: socrat-5"):
                contract.check(root)

    def test_relay_scope_drift_is_not_automatically_rewritten(self) -> None:
        """Reject an all-interfaces relay mutation and leave the fixture bytes unchanged."""
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root / "scripts/wg-peer15-relay.py"
            self.assertEqual(contract.check(root), 10)
            original = p.read_text()
            tree = ast.parse(original)
            front = [
                node
                for node in tree.body
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "FRONT" for target in node.targets
                )
            ]
            self.assertEqual(len(front), 1)
            self.assertIsInstance(front[0].value, ast.Tuple)
            front[0].value.elts[0] = ast.Constant(value="0.0.0.0")
            mutated = ast.unparse(tree) + "\n"
            self.assertNotEqual(ast.dump(ast.parse(original)), ast.dump(ast.parse(mutated)))
            p.write_text(mutated)
            before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            with self.assertRaisesRegex(ValueError, "Fixed relay topology drift"):
                contract.check(root, write=True)
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_relay_sandbox_widening_or_stale_endpoint_rejected_without_writes(self) -> None:
        """Reject widened or stale sandbox endpoints without rewriting the unit."""
        for replacement in ["10.250.0.0/16", "10.250.0.99/32"]:
            with tempfile.TemporaryDirectory() as d:
                root = self.fixture(d)
                p = root / "ansible/files/wg-peer15-relay.service"
                p.write_text(p.read_text().replace("10.250.0.41/32", replacement))
                before = p.read_bytes()
                with self.assertRaisesRegex(ValueError, "sandbox endpoint scope drift"):
                    contract.check(root, write=True)
                self.assertEqual(p.read_bytes(), before)

    def test_relay_sandbox_privilege_drift_rejected(self) -> None:
        """Reject a sandbox unit that gains CAP_NET_ADMIN."""
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root / "ansible/files/wg-peer15-relay.service"
            p.write_text(
                p.read_text().replace(
                    "CapabilityBoundingSet=", "CapabilityBoundingSet=CAP_NET_ADMIN"
                )
            )
            with self.assertRaisesRegex(ValueError, "sandbox privilege drift"):
                contract.check(root)

    def test_bootstrap_requires_opt_in_and_refuses_existing_workloads(self) -> None:
        """Keep empty bootstrap opt-in false and install-only for the Argo playbook."""
        p = yaml.safe_load((ROOT / "ansible/playbooks/argocd.yml").read_text())[0]
        self.assertFalse(p["vars"]["argocd_allow_empty_bootstrap"])
        self.assertTrue(
            p["vars"]["argocd_values_local"].endswith("/deploy/platform/argo-cd/values.yaml")
        )
        tasks = p["tasks"]
        self.assertIn("ansible.builtin.assert", tasks[0])
        self.assertIn("ansible.builtin.assert", tasks[2])
        helm = next(
            t["ansible.builtin.command"]["argv"]
            for t in tasks
            if t.get("name") == "Install Argo CD control plane only"
        )
        self.assertIn("install", helm)
        self.assertNotIn("upgrade", helm)
        self.assertNotIn("--install", helm)

    def test_bootstrap_compatibility_path_is_same_canonical_source(self) -> None:
        """Require the compatibility values path to be the canonical Argo source."""
        alias = ROOT / "deploy/argocd/values.yaml"
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), (ROOT / "deploy/platform/argo-cd/values.yaml").resolve())
        self.assertEqual(alias.read_bytes(), alias.resolve().read_bytes())


if __name__ == "__main__":
    unittest.main()
