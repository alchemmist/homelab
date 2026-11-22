"""Local Argo values and documentation pointers reject missing or escaping sources."""

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import NotRequired, TypedDict

import pytest
import yaml


class _HelmSource(TypedDict):
    """Local values files, including the deliberately rejected optional-file flag."""

    valueFiles: list[str]
    ignoreMissingValueFiles: NotRequired[bool]


class _Source(TypedDict):
    """Local or external Argo source used by the fixture and its mutations."""

    repoURL: str
    targetRevision: str
    path: NotRequired[str]
    chart: NotRequired[str]
    ref: NotRequired[str]
    helm: NotRequired[_HelmSource]


class _ApplicationSpec(TypedDict):
    """Both source forms remain representable so ambiguity can be rejected."""

    source: NotRequired[_Source]
    sources: NotRequired[list[_Source]]


class _Application(TypedDict):
    """Minimal mutable Application document; no live Kubernetes resource."""

    kind: str
    metadata: dict[str, str]
    spec: _ApplicationSpec


class _CurrentValue(TypedDict):
    """A source value bound to the documentation that must describe it."""

    application: str
    source: str
    path: list[str]
    documents: list[str]


class _PointerConfig(TypedDict):
    """Temporary source inventory and current-value documentation bindings."""

    schemaVersion: int
    repoURL: str
    applicationDirectory: str
    rootApplication: str
    documents: list[str]
    currentValues: list[_CurrentValue]


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "source_pointers", ROOT / "ci/check_source_pointers.py"
)
assert spec is not None
assert spec.loader is not None
pointers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pointers)
REPO = "https://github.com/alchemmist/homelab.git"


class SourcePointers(unittest.TestCase):
    """Check local source resolution, repository confinement and current document bindings."""

    def write(self, root: Path, name: str, value: object) -> None:
        """Write only fixture-local YAML without changing the represented values."""
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(value))

    def fixture(self, directory: str) -> tuple[Path, _Application, _PointerConfig]:
        """Create local Argo sources, a values binding and its current documentation."""
        root = Path(directory)
        self.write(
            root, "charts/api/Chart.yaml", {"apiVersion": "v2", "name": "api", "version": "1.0.0"}
        )
        self.write(
            root, "charts/api/values.yaml", {"persistence": {"existingClaim": "claim-current"}}
        )
        self.write(root, "deploy/api.yaml", {"extra": "value"})
        app: _Application = {
            "kind": "Application",
            "metadata": {"name": "api", "namespace": "argocd"},
            "spec": {
                "source": {
                    "repoURL": REPO,
                    "targetRevision": "main",
                    "path": "charts/api",
                    "helm": {"valueFiles": ["../../deploy/api.yaml"]},
                }
            },
        }
        self.write(root, "deploy/argocd/apps/api.yaml", app)
        self.write(
            root,
            "deploy/argocd/root.yaml",
            {
                "spec": {
                    "source": {
                        "repoURL": REPO,
                        "targetRevision": "main",
                        "path": "deploy/argocd/apps",
                    }
                }
            },
        )
        (root / "docs").mkdir()
        (root / "docs/current.md").write_text(
            "Claim `claim-current`; [chart](../charts/api/Chart.yaml).\n"
        )
        config: _PointerConfig = {
            "schemaVersion": 1,
            "repoURL": REPO,
            "applicationDirectory": "deploy/argocd/apps",
            "rootApplication": "deploy/argocd/root.yaml",
            "documents": ["docs/current.md"],
            "currentValues": [
                {
                    "application": "api",
                    "source": "charts/api/values.yaml",
                    "path": ["persistence", "existingClaim"],
                    "documents": ["docs/current.md"],
                }
            ],
        }
        p = root / "deploy/contracts/source-pointers.json"
        p.parent.mkdir()
        p.write_text(json.dumps(config))
        return root, app, config

    def test_real_current_sources_and_docs(self) -> None:
        """Verify real current sources and docs."""
        count, values = pointers.check(ROOT)
        assert count > 0
        assert values > count

    def test_valid_relative_values_and_docs_are_read_only(self) -> None:
        """Verify valid relative values and docs are read only."""
        with tempfile.TemporaryDirectory() as d:
            root, _app, _c = self.fixture(d)
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            assert pointers.check(root) == (1, 2)
            assert before == {p: p.read_bytes() for p in before}

    def test_missing_values_rejected_even_when_ignored_by_argo(self) -> None:
        """Verify missing values rejected even when ignored by argo."""
        with tempfile.TemporaryDirectory() as d:
            root, app, _c = self.fixture(d)
            app["spec"]["source"]["helm"]["ignoreMissingValueFiles"] = True
            self.write(root, "deploy/argocd/apps/api.yaml", app)
            (root / "deploy/api.yaml").unlink()
            with pytest.raises(ValueError, match="Missing local values"):
                pointers.check(root)

    def test_missing_source_or_chart_rejected(self) -> None:
        """Verify missing source or chart rejected."""
        for name in ["source", "chart"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                root, app, _c = self.fixture(d)
                if name == "chart":
                    (root / "charts/api/Chart.yaml").unlink()
                else:
                    app["spec"]["source"]["path"] = "charts/absent"
                    self.write(root, "deploy/argocd/apps/api.yaml", app)
                with pytest.raises(ValueError, match="Missing"):
                    pointers.check(root)

    def test_cross_source_values_resolve_from_repo_root_not_ref_path(self) -> None:
        """Verify cross source values resolve from repo root not ref path."""
        with tempfile.TemporaryDirectory() as d:
            root, app, c = self.fixture(d)
            app["spec"] = {
                "sources": [
                    {
                        "repoURL": "https://charts.example.test",
                        "chart": "api",
                        "targetRevision": "1.0.0",
                        "helm": {"valueFiles": ["$values/deploy/api.yaml"]},
                    },
                    {"repoURL": REPO, "targetRevision": "main", "ref": "values", "path": "docs"},
                ]
            }
            self.write(root, "deploy/argocd/apps/api.yaml", app)
            c["currentValues"] = []
            (root / "deploy/contracts/source-pointers.json").write_text(json.dumps(c))
            assert pointers.check(root) == (1, 2)

    def test_undefined_ref_and_repo_escape_rejected(self) -> None:
        """Verify undefined ref and repo escape rejected."""
        for value, error in [
            ("$unknown/file.yaml", "Undefined"),
            ("../../../../outside.yaml", "escapes"),
        ]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as d:
                root, app, _c = self.fixture(d)
                app["spec"]["source"]["helm"]["valueFiles"] = [value]
                self.write(root, "deploy/argocd/apps/api.yaml", app)
                with pytest.raises(ValueError, match=error):
                    pointers.check(root)

    def test_values_symlink_escape_rejected(self) -> None:
        """Verify values symlink escape rejected."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            root, _app, _c = self.fixture(d)
            for name in ["deploy/api.yaml", "charts/api/Chart.yaml"]:
                with self.subTest(name=name):
                    p = root / name
                    original = p.read_bytes()
                    p.unlink()
                    p.symlink_to(Path(outside) / "outside.yaml")
                    with pytest.raises(ValueError, match="escapes"):
                        pointers.check(root)
                    p.unlink()
                    p.write_bytes(original)

    def test_duplicate_app_and_ambiguous_source_form_rejected(self) -> None:
        """Verify duplicate app and ambiguous source form rejected."""
        for mode in ["duplicate", "ambiguous"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root, app, _c = self.fixture(d)
                if mode == "duplicate":
                    self.write(root, "deploy/argocd/apps/copy.yaml", app)
                    expected = "Duplicate Application identity: copy.yaml"
                else:
                    app["spec"]["sources"] = [app["spec"]["source"]]
                    self.write(root, "deploy/argocd/apps/api.yaml", app)
                    expected = "Require exactly one source/sources form: api.yaml"
                with pytest.raises(ValueError, match=re.escape(expected)):
                    pointers.check(root)

    def test_root_source_move_and_stale_doc_binding_rejected(self) -> None:
        """Verify root source move and stale doc binding rejected."""
        for mode in ["root", "binding", "claim", "link"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root, _app, c = self.fixture(d)
                if mode == "root":
                    self.write(
                        root,
                        "deploy/argocd/root.yaml",
                        {
                            "spec": {
                                "source": {
                                    "repoURL": REPO,
                                    "targetRevision": "main",
                                    "path": "other",
                                }
                            }
                        },
                    )
                    expected = "Root Application no longer owns the checked source directory"
                elif mode == "binding":
                    c["currentValues"][0]["application"] = "other"
                    (root / "deploy/contracts/source-pointers.json").write_text(json.dumps(c))
                    expected = "Documented values are not consumed by their registered Application"
                elif mode == "claim":
                    (root / "docs/current.md").write_text("`stale-claim`")
                    expected = "Current documentation value drift: docs/current.md"
                else:
                    (root / "docs/current.md").write_text("`claim-current` [missing](missing.md)")
                    expected = "Broken local document link: docs/current.md"
                with pytest.raises(ValueError, match=re.escape(expected)):
                    pointers.check(root)

    def test_duplicate_refs_and_nonmain_source_not_silently_accepted(self) -> None:
        """Verify duplicate refs and nonmain source not silently accepted."""
        for mode in ["refs", "revision", "absolute"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root, app, _c = self.fixture(d)
                if mode == "refs":
                    source = app["spec"].pop("source")
                    app["spec"]["sources"] = [
                        source,
                        {"repoURL": REPO, "targetRevision": "main", "ref": "values"},
                        {"repoURL": REPO, "targetRevision": "main", "ref": "values"},
                    ]
                    expected = "Duplicate/invalid source ref: api.yaml"
                elif mode == "revision":
                    app["spec"]["source"]["targetRevision"] = "old-revision"
                    expected = (
                        "Cannot verify non-main local source against current checkout: api.yaml"
                    )
                else:
                    app["spec"]["source"]["helm"]["valueFiles"] = [str(root / "deploy/api.yaml")]
                    expected = "Helm values must be repository-relative: api.yaml"
                self.write(root, "deploy/argocd/apps/api.yaml", app)
                with pytest.raises(ValueError, match=re.escape(expected)):
                    pointers.check(root)


if __name__ == "__main__":
    unittest.main()
