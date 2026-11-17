"""Offline ownership classifications and refusal-before-effects regression tests."""

import ast
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict

import pytest
import yaml


class _Entrypoint(TypedDict):
    """One temporary ownership classification, including its explicit review reason."""

    path: str
    status: str
    owners: list[str]
    reason: str


class _EntrypointConfig(TypedDict):
    """Fixture schema and all classified operational entries."""

    schemaVersion: int
    entries: list[_Entrypoint]


class _RefusalPlay(TypedDict):
    """The only allowed retired play shape, before deliberate effect mutations."""

    name: str
    hosts: str
    gather_facts: bool
    become: bool
    any_errors_fatal: bool
    tasks: list[dict[str, object]]


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "entrypoints", ROOT / "scripts/check_operational_entrypoints.py"
)
assert spec is not None
assert spec.loader is not None
entrypoints = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoints)


class OperationalEntrypoints(unittest.TestCase):
    """Detect stale classifications, unowned installers and retired entrypoint effects."""

    def fixture(self, d: str) -> tuple[Path, _EntrypointConfig]:
        """Create a review-required competing installer in an isolated directory."""
        root = Path(d)
        (root / "ansible").mkdir()
        (root / "deploy/contracts").mkdir(parents=True)
        (root / "ansible/demo.yml").write_text("command: helm upgrade demo ./chart\n")
        c: _EntrypointConfig = {
            "schemaVersion": 1,
            "entries": [
                {
                    "path": "ansible/demo.yml",
                    "status": "review-required",
                    "owners": [],
                    "reason": "Known competing entrypoint, not permission to execute.",
                }
            ],
        }
        self.save(root, c)
        return root, c

    def save(self, root: Path, c: _EntrypointConfig) -> None:
        """Persist only the temporary classification used by a mutation test."""
        (root / "deploy/contracts/operational-entrypoints.json").write_text(json.dumps(c))

    def test_current_inventory_is_read_only(self) -> None:
        """Verify current inventory is read only."""
        assert entrypoints.check(ROOT) == (23, 10)
        with tempfile.TemporaryDirectory() as d:
            root, _c = self.fixture(d)
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            assert entrypoints.check(root) == (1, 1)
            assert before == {p: p.read_bytes() for p in before}

    def test_new_unclassified_helm_entrypoint_fails(self) -> None:
        """Verify new unclassified helm entrypoint fails."""
        with tempfile.TemporaryDirectory() as d:
            root, _c = self.fixture(d)
            (root / "ansible/other.yml").write_text("command: helm install other ./chart\n")
            with pytest.raises(ValueError, match="Unclassified"):
                entrypoints.check(root)

    def test_duplicate_or_stale_classification_fails(self) -> None:
        """Verify duplicate or stale classification fails."""
        for mode in ["duplicate", "stale", "invalid"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root, c = self.fixture(d)
                if mode == "duplicate":
                    c["entries"] *= 2
                    expected = "Duplicate operational entrypoint"
                elif mode == "stale":
                    (root / "ansible/demo.yml").write_text("tasks: []\n")
                    expected = "Stale Helm classification; re-review removal: ansible/demo.yml"
                else:
                    c["entries"][0]["status"] = "safe-to-run"
                    expected = "Invalid operational classification: ansible/demo.yml"
                self.save(root, c)
                with pytest.raises(ValueError, match=re.escape(expected)):
                    entrypoints.check(root)

    def test_retired_import_or_remote_action_fails(self) -> None:
        """Verify retired import or remote action fails."""
        for mode in ["import", "command"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root, c = self.fixture(d)
                c["entries"][0]["status"] = "retired"
                self.save(root, c)
                play: _RefusalPlay = {
                    "name": "refuse",
                    "hosts": "socrat-0",
                    "gather_facts": False,
                    "become": False,
                    "any_errors_fatal": True,
                    "tasks": [
                        {
                            "name": "refuse",
                            "ansible.builtin.fail": {"msg": "retired"},
                            "tags": ["always"],
                        }
                    ],
                }
                p = root / "ansible/demo.yml"
                p.write_text(yaml.safe_dump([play]))
                assert entrypoints.check(root) == (1, 0)
                if mode == "import":
                    p.write_text(yaml.safe_dump([play, {"import_playbook": "later.yml"}]))
                    expected = "Retired follow-up play: ansible/demo.yml"
                else:
                    play["tasks"].append({"ansible.builtin.command": "true"})
                    p.write_text(yaml.safe_dump([play]))
                    expected = "Retired entrypoint side effects: ansible/demo.yml"
                with pytest.raises(ValueError, match=re.escape(expected)):
                    entrypoints.check(root)

    def test_missing_owner_is_not_silently_accepted(self) -> None:
        """Verify missing owner is not silently accepted."""
        with tempfile.TemporaryDirectory() as d:
            root, c = self.fixture(d)
            c["entries"][0]["owners"] = ["missing"]
            self.save(root, c)
            with pytest.raises(ValueError, match="Missing operational source owner"):
                entrypoints.check(root)

    def test_scan_symlink_escape_rejected_before_read(self) -> None:
        """Verify scan symlink escape rejected before read."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            root, _c = self.fixture(d)
            (root / "ansible/outside.yml").symlink_to(Path(other) / "nonexistent-private.yml")
            with pytest.raises(ValueError, match="symlink escapes"):
                entrypoints.check(root)


if __name__ == "__main__":
    unittest.main()


_REFUSAL_MODULE_SIZE = 4
_REFUSAL_MAIN_SIZE = 3
_REFUSAL_EXIT_CODE = 2


def _assert_retired_grafana_source(source: str) -> None:
    """Gate the tiny refusal program before importing it into an offline test."""
    tree = ast.parse(source)
    assert len(tree.body) == _REFUSAL_MODULE_SIZE
    doc, imports, main, guard = tree.body
    assert isinstance(doc, ast.Expr)
    assert isinstance(doc.value, ast.Constant)
    assert isinstance(doc.value.value, str)
    assert isinstance(imports, ast.Import)
    assert [(alias.name, alias.asname) for alias in imports.names] == [("sys", None)]
    assert isinstance(main, ast.FunctionDef)
    assert main.name == "main"
    expected_signature = ast.parse("def main() -> int: pass").body[0]
    assert isinstance(expected_signature, ast.FunctionDef)
    assert main.returns is not None
    assert expected_signature.returns is not None
    assert ast.dump(main.args) == ast.dump(expected_signature.args)
    assert ast.dump(main.returns) == ast.dump(expected_signature.returns)
    assert main.decorator_list == []
    assert len(main.body) == _REFUSAL_MAIN_SIZE
    main_doc, message, result = main.body
    assert isinstance(main_doc, ast.Expr)
    assert isinstance(main_doc.value, ast.Constant)
    assert isinstance(main_doc.value.value, str)
    assert isinstance(message, ast.Expr)
    assert isinstance(message.value, ast.Call)
    call = message.value
    assert ast.dump(call.func) == ast.dump(ast.parse("sys.stderr.write", mode="eval").body)
    assert len(call.args) == 1
    assert call.keywords == []
    assert isinstance(call.args[0], ast.Constant)
    assert isinstance(call.args[0].value, str)
    text = call.args[0].value
    assert text.startswith("Retired:")
    assert "docs/identity/app-access-groups.md" in text
    assert "ansible/roles/authentik/files/reconcile_app_access.py" in text
    assert "ansible/roles/identity_app_access/" in text
    assert isinstance(result, ast.Return)
    assert isinstance(result.value, ast.Constant)
    assert type(result.value.value) is int
    assert result.value.value == _REFUSAL_EXIT_CODE
    expected_guard = ast.parse('if __name__ == "__main__":\n    raise SystemExit(main())').body[0]
    assert ast.dump(guard) == ast.dump(expected_guard)


@pytest.mark.parametrize(
    "args", [[], ["--help"], ["plan"], ["apply", "--root", "/not-a-credential-root"]]
)
def test_retired_grafana_admission_never_forwards_or_reads_credentials(
    args: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import only the structurally bounded refusal; no identity helper is loaded."""
    path = ROOT / "scripts/grafana-app-admission.py"
    _assert_retired_grafana_source(path.read_text())
    spec = importlib.util.spec_from_file_location("retired_grafana_admission", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", [str(path), *args])
    assert module.main() == _REFUSAL_EXIT_CODE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Retired:")
    assert "nothing was forwarded" in captured.err


@pytest.mark.parametrize("mutation", ["import", "open", "forward", "success"])
def test_retired_grafana_admission_effect_mutations_are_rejected(mutation: str) -> None:
    """The guard rejects capability imports, file access, forwarding and success."""
    source = (ROOT / "scripts/grafana-app-admission.py").read_text()
    _assert_retired_grafana_source(source)
    if mutation == "import":
        changed = source + "\nimport os\n"
    elif mutation == "open":
        changed = source.replace("sys.stderr.write(", "open(", 1)
    elif mutation == "forward":
        changed = source.replace("sys.stderr.write(", "reconcile_app_access.apply(", 1)
    else:
        changed = source.replace("return 2", "return 0", 1)
    assert changed != source
    with pytest.raises(AssertionError):
        _assert_retired_grafana_source(changed)
