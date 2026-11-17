import ast
import json
import pathlib
import unittest
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = pathlib.Path(__file__).resolve().parents[1]


CAS_SOURCE = "hashlib.sha256(before).hexdigest() == EXPECTED"
CAS_EXPRESSION = ast.dump(ast.parse(CAS_SOURCE, mode="eval").body)


def has_cas_assertion(tree: ast.Module) -> bool:
    """Find an actual top-level main assertion, never a comment or quoted recipe."""
    return any(
        isinstance(statement, ast.Assert) and ast.dump(statement.test) == CAS_EXPRESSION
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
        for statement in node.body
    )


class BootstrapTests(unittest.TestCase):
    def test_manifest_matches_inventory_and_scoped_template(self):
        m = json.loads((ROOT / "deploy/network/socrat-5-bootstrap.json").read_text())
        v = {}
        for f in [
            "ansible/roles/wireguard_socrat/defaults/main.yml",
            "ansible/inventory/group_vars/Socrat.yml",
            "ansible/inventory/host_vars/socrat-4.yml",
        ]:
            v.update(yaml.safe_load((ROOT / f).read_text()))
        self.assertEqual(
            {k: v["wg_socrat_nodes"][m["name"]][k] for k in ["address", "public_key"]},
            {"address": m["address"], "public_key": m["public_key"]},
        )
        v.update(inventory_hostname="socrat-4", wg_socrat_private_key="TEST_ONLY_NOT_A_KEY")
        rendered = (
            Environment(undefined=StrictUndefined)
            .from_string(
                (ROOT / "ansible/roles/wireguard_socrat/templates/wg-socrat.conf.j2").read_text()
            )
            .render(v)
        )
        self.assertEqual(rendered.count(m["public_key"]), 1)
        self.assertIn("AllowedIPs = 10.250.0.41/32", rendered)
        self.assertNotIn("0.0.0.0/0", rendered)
        for name, p in v["wg_socrat_nodes"].items():
            if name != "socrat-4":
                self.assertIn(p["public_key"], rendered)

    def test_guard_is_pre_dnat_and_source_scoped(self):
        s = (ROOT / "scripts/testing-class-wg-guard.sh").read_text()
        self.assertIn("-t mangle -I PREROUTING 1 -i wg-socrat -s 10.250.0.41/32", s)
        self.assertIn("--sport 22 -m conntrack --ctstate ESTABLISHED", s)
        self.assertIn("-d 10.250.0.40/32", s)
        self.assertIn('-A "${CHAIN}" -j DROP', s)
        for bad in ["iptables-restore", " -F ", " -P ", "MASQUERADE", "--dport 6443"]:
            self.assertNotIn(bad, s)

    def test_peer_admission_is_cas_and_no_transport_restart(self):
        s = (ROOT / "scripts/wg-testing-class-admit.py").read_text()
        tree = ast.parse(s)
        assert has_cas_assertion(tree)
        expected_args = ast.parse(
            '["wg", "set", "wg-socrat", "peer", KEY, "allowed-ips", IP, '
            '"persistent-keepalive", "25"]',
            mode="eval",
        ).body
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "run"
            and node.args
            and ast.dump(node.args[0]) == ast.dump(expected_args)
            for node in ast.walk(tree)
        )
        preservation = ast.dump(ast.parse("current == original", mode="eval").body)
        assert any(
            ast.dump(part) == preservation
            for node in ast.walk(tree)
            if isinstance(node, ast.Assert)
            for part in ast.walk(node.test)
        )
        tokens = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert not {"syncconf", "restart", "down", "up"} & tokens

    def test_cas_assertion_rejects_real_mutations_and_comment_decoys(self):
        source = (ROOT / "scripts/wg-testing-class-admit.py").read_text()
        tree = ast.parse(source)
        assert has_cas_assertion(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert) and ast.dump(node.test) == CAS_EXPRESSION:
                node.test = ast.Constant(value=True)
        assert not has_cas_assertion(tree)
        assert not has_cas_assertion(ast.parse("# " + ast.unparse(ast.parse(CAS_SOURCE))))

    def test_guard_declared_before_transport_on_boot(self):
        s = (ROOT / "ansible/playbooks/testing-class-bootstrap-guard.yml").read_text()
        self.assertIn("Requires=testing-class-wg-guard.service", s)
        self.assertIn("Before=wg-quick@wg-socrat.service", s)
        self.assertNotIn("state: restarted", s)


if __name__ == "__main__":
    unittest.main()
