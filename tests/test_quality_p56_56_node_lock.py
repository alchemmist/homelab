"""Offline npm lock auditing stays inside the repository and the fixed advisory feed."""

from __future__ import annotations

import ast
import base64
import gzip
import hashlib
import http.client
import json
import ssl
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from ci.quality import check_dependencies as lint

_REPO = Path(__file__).resolve().parents[1]
_LOCAL_AUDIT = ["pip-audit", "--local", "--strict", "--format", "json"]
_INTEGRITY = "sha512-" + base64.b64encode(bytes((0x11,)) * 64).decode("ascii")
_OWNED_LOCK = "deploy/mcp/clients/package-lock.json"
_OWNED_DISTRIBUTIONS = 127
_UNCHANGED_FUNCTION_DIGESTS = {
    "validate_requirement_lock": "b3a33235549137f1",
    "_distribution_fields": "92a59186d7631950",
    "_vulnerability_id": "28d4d310c9cd0844",
    "dependency_report": "28a9518091f014b5",
    "_audit_python_source": "82a0df4c0b4905b9",
    "sarif": "9a051a40eaa2fc84",
    "nonsecret_tokenizer_option": "8bed6a3793d2ba0c",
    "yaml_targets": "06416c3ddf6bc233",
    "shell_targets": "d0a64ddec3855750",
    "shell_dialect": "5b314dd33ce322ab",
    "walk_runs": "84e47c6628291ba5",
    "workflow_runs": "b662bffc061e68ea",
    "workflow_files": "bd14b7f949c7a464",
    "parse_mypy": "a4b195fa170ed049",
    "mypy_argv": "52f4ec72b8406dcf",
    "mypy_status": "3b74ad0402e03549",
    "mypy_invoke": "893e273ac5b5b538",
    "python_syntax_findings": "0767c5b6e78c82a1",
    "mypy_on": "884133f27e5b0c18",
    "mypy_findings": "b35d24c5bcc1146f",
    "format_findings": "07852e9906d911b4",
    "shellcheck_files": "5212046c9fd29985",
    "workflow_script_findings": "a9c8e6afff47f8fd",
    # 7a45c9cd split check into a dispatcher and nine typed implementations.
    # Pin the extracted implementations and the shared fail-closed report runner.
    # #459 deliberately changed the workflow dispatch and both workflow scanners.
    # Sources of the revised pins (leading docstrings excluded as below):
    # d525d349 for the scanner commands, a7cfd08e for check/workflow_directives,
    # 82e99f75 for physical-line attribution. All other original pins remain.
    "check_workflow": "f31d15922b633629",
    "workflow_directives": "42d74e4c8b199427",
    "python_directive_lines": "69a68cc0a476fc79",
    "check_python": "e8a7c92439e49d29",
    "check_yaml": "f7758c28b3de10c4",
    "check_shell": "3cb39cc5d1303f55",
    "check_actions": "640d695b3edece7c",
    "check_actionlint": "caa982e539c3e36c",
    "check_ansible": "e7f4c4134b3e3508",
    "check_docker": "62b3f92b54fea0d7",
    "check_javascript": "669d09e95bf085cf",
    "check_secrets": "d58cf370ba0c9e77",
    "run": "451657b3c955b7a4",
}
_PREVIOUS_CHECK_DEPENDENCIES = "256df8f69c0d5d07"


class _Response:
    """Canned HTTP response. It never reads a socket."""

    def __init__(self, status: int, body: bytes, *, oversized: bool) -> None:
        """Store one status and body for the auditor under test."""
        self.status = status
        self._body = body
        self._oversized = oversized

    def read(self, limit: int) -> bytes:
        """Return the canned body, or exactly the requested bound when oversized."""
        if self._oversized:
            return b"x" * limit
        return self._body


class _Connection:
    """Stand-in for one direct TLS connection."""

    def __init__(
        self,
        host: str,
        timeout: float | None = None,
        context: ssl.SSLContext | None = None,
    ) -> None:
        """Record constructor arguments and leave the network unused."""
        self.host = host
        self.timeout = timeout
        self.context = context
        self.method = ""
        self.url = ""
        self.body = b""
        self.headers: dict[str, str] = {}
        self.closed = False
        self.response = _Response(200, b"{}", oversized=False)
        self.error: BaseException | None = None

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Record the request or raise the injected transport error."""
        if self.error is not None:
            raise self.error
        self.method = method
        self.url = url
        self.body = body or b""
        self.headers = dict(headers or {})

    def getresponse(self) -> _Response:
        """Return the injected response without a round trip."""
        return self.response

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


def _owner(name: str) -> Path:
    if name in {"check_actions", "check_actionlint", "workflow_directives", "python_directive_lines"}:
        module = "check_workflow"
    elif name.startswith("mypy_") or name in {"parse_mypy", "format_findings", "python_syntax_findings"}:
        module = "check_python"
    elif name in {"shell_targets", "shellcheck_files"}:
        module = "check_shell"
    elif name in {"nonsecret_tokenizer_option", "docker_targets"}:
        module = "check_docker"
    elif name == "yaml_targets":
        module = "check_yaml"
    elif name == "run":
        module = "runner"
    elif name.startswith("check_"):
        module = name
    elif name in {"validate_requirement_lock", "_distribution_fields", "_vulnerability_id", "dependency_report", "_audit_python_source", "node_lock_packages", "node_advisory_report", "post_node_advisory_batch"}:
        module = "check_dependencies"
    else:
        module = "lint_support"
    return Path("ci/quality") / f"{module}.py"


def _digest(name: str) -> str:
    source = (_REPO / _owner(name)).read_text()
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            if name == "_distribution_fields":
                expected = ast.parse('"skip_reason" in value', mode="eval").body
                guards = [
                    item
                    for item in ast.walk(node)
                    if isinstance(item, ast.If) and ast.dump(item.test) == ast.dump(expected)
                ]
                assert len(guards) == 1, "Unexpected skipped-distribution guard"
                guards[0].test = ast.parse('value.get("skip_reason")', mode="eval").body
            if name == "_audit_python_source":
                expected = ast.parse("_python_audit_payload(process.stdout)", mode="eval").body
                decoders = [
                    item
                    for item in ast.walk(node)
                    if isinstance(item, ast.Call) and ast.dump(item) == ast.dump(expected)
                ]
                assert len(decoders) == 1, "Unexpected Python audit decoder"
                decoders[0].func = ast.Attribute(
                    value=ast.Name(id="json", ctx=ast.Load()), attr="loads", ctx=ast.Load()
                )
            # D103 added leading docstrings to functions whose executable AST
            # was already pinned. Keep the original seven documented pins intact.
            historically_documented = {
                "validate_requirement_lock",
                "_distribution_fields",
                "_vulnerability_id",
                "dependency_report",
                "_audit_python_source",
                "mypy_status",
                "python_syntax_findings",
            }
            if name not in historically_documented and ast.get_docstring(node) is not None:
                node.body.pop(0)
            if name == "run":
                # 0cfe2545 narrowed only the caught error types; verify the exact
                # tuple before comparing the rest against the original fingerprint.
                handlers = [item for item in ast.walk(node) if isinstance(item, ast.ExceptHandler)]
                assert len(handlers) == 1
                assert handlers[0].type is not None
                assert ast.dump(handlers[0].type) == ast.dump(
                    ast.parse("(OSError, RuntimeError, TypeError, ValueError)", mode="eval").body
                )
                handlers[0].type = ast.Name(id="Exception", ctx=ast.Load())
            if name == "check_docker":
                expected = ast.parse("docker_targets(names)", mode="eval").body
                selectors = [
                    item
                    for item in ast.walk(node)
                    if isinstance(item, ast.Assign)
                    and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name)
                    and item.targets[0].id == "files"
                    and ast.dump(item.value) == ast.dump(expected)
                ]
                assert len(selectors) == 1, "Unexpected Docker selector shape"
            dumped = ast.dump(node, include_attributes=False)
            return hashlib.sha256(dumped.encode()).hexdigest()[:16]
    message = name
    raise AssertionError(message)


def _python_audit_literals() -> list[list[object]]:
    source = (_REPO / "ci/quality/check_dependencies.py").read_text()
    module = ast.parse(source)
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "check_dependencies"
    )
    literals: list[list[object]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "_audit_python_source" or not node.args:
            continue
        argument = node.args[0]
        if not isinstance(argument, ast.List):
            continue
        values: list[object] = []
        for item in argument.elts:
            if isinstance(item, ast.Constant):
                values.append(item.value)
            elif isinstance(item, ast.Name):
                values.append(item.id)
        literals.append(values)
    return literals


def _clean_report(count: int) -> dict[str, object]:
    return {"results": [{} for _ in range(count)]}


def _command(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    assert kwargs == {"allowed": (0, 1), "timeout": 300}
    payload = {"dependencies": [{"name": "fixture", "version": "1", "vulns": []}]}
    return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _document(dependencies: dict[str, str]) -> dict[str, object]:
    packages: dict[str, object] = {
        "": {
            "name": "fixture",
            "version": "1.0.0",
            "dependencies": dict(dependencies),
        }
    }
    for name, version in dependencies.items():
        filename = name.rsplit("/", 1)[-1]
        packages[f"node_modules/{name}"] = {
            "version": version,
            "resolved": f"https://registry.npmjs.org/{name}/-/{filename}-{version}.tgz",
            "integrity": _INTEGRITY,
        }
    return {
        "name": "fixture",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": packages,
    }


def _entry(document: dict[str, object], name: str) -> dict[str, object]:
    packages = document["packages"]
    if not isinstance(packages, dict):
        message = "packages"
        raise TypeError(message)
    entry = packages[f"node_modules/{name}"]
    if not isinstance(entry, dict):
        message = "entry"
        raise TypeError(message)
    return entry


def test_non_npm_linter_functions_keep_their_executable_ast() -> None:
    """Dependency-audit edits do not rewrite the other linter implementations."""
    for name, digest in _UNCHANGED_FUNCTION_DIGESTS.items():
        assert _digest(name) == digest, name
    assert _digest("check_dependencies") != _PREVIOUS_CHECK_DEPENDENCIES
    for name in ("node_lock_packages", "node_advisory_report", "post_node_advisory_batch"):
        assert _digest(name)


def test_python_audit_command_bytes_remain_in_check_dependencies() -> None:
    """pip-audit invocation bytes and the requirement name stay positional."""
    assert _python_audit_literals() == [
        ["pip-audit", "--local", "--strict", "--format", "json"],
        [
            "pip-audit",
            "--strict",
            "--disable-pip",
            "--no-deps",
            "--require-hashes",
            "--requirement",
            "name",
            "--format",
            "json",
        ],
    ]


def test_owned_npm_lock_is_fully_described_without_a_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owned lock's complete distribution set is local data, not a sample."""

    def unavailable(*_args: object, **_kwargs: object) -> object:
        message = "network"
        raise AssertionError(message)

    monkeypatch.setattr(http.client, "HTTPSConnection", unavailable)
    packages = lint.node_lock_packages(_REPO / _OWNED_LOCK)
    assert packages is not None
    assert len(packages) == _OWNED_DISTRIBUTIONS
    assert packages == sorted(set(packages))
    assert ("@umami/mcp", "0.2.0") in packages
    assert ("argocd-mcp", "0.9.0") in packages
    assert ("zod", "3.25.76") not in packages
    assert ("zod", "4.6.7") in packages
    assert ("content-type", "1.0.5") in packages
    assert ("content-type", "2.1.0") in packages


def test_supported_lock_submits_every_distribution_and_keeps_python_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean advisory body still counts every locked distribution."""
    calls: list[list[str]] = []
    posted: list[tuple[str, str]] = []

    def command(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return _command(argv, **kwargs)

    def post(packages: list[tuple[str, str]]) -> dict[str, object]:
        posted.extend(packages)
        return _clean_report(len(packages))

    monkeypatch.setattr(lint, "command", command)
    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    findings, count = lint.check_dependencies([_OWNED_LOCK])
    assert findings == []
    assert calls == [_LOCAL_AUDIT]
    assert len(posted) == _OWNED_DISTRIBUTIONS
    assert ("@umami/mcp", "0.2.0") in posted
    assert ("argocd-mcp", "0.9.0") in posted
    expected = 1 + _OWNED_DISTRIBUTIONS
    assert count == expected


def test_advisory_findings_keep_version_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same advisory on two locked versions remains two source findings."""
    relative = "tools/fixture/package-lock.json"
    document = _document({"fixture-package": "1.0.0"})
    packages = document["packages"]
    assert isinstance(packages, dict)
    packages["node_modules/nested/node_modules/fixture-package"] = {
        "version": "2.0.0",
        "resolved": "https://registry.npmjs.org/fixture-package/-/fixture-package-2.0.0.tgz",
        "integrity": _INTEGRITY,
    }
    root = packages[""]
    assert isinstance(root, dict)
    root["dependencies"] = {"fixture-package": "1.0.0"}
    _write(tmp_path, relative, json.dumps(document))
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", _command)

    def post(packages_sent: list[tuple[str, str]]) -> dict[str, object]:
        assert packages_sent == [
            ("fixture-package", "1.0.0"),
            ("fixture-package", "2.0.0"),
        ]
        return {
            "results": [
                {"vulns": [{"id": "GHSA-fixture"}, {"id": "GHSA-fixture"}]},
                {"vulns": [{"id": "GHSA-fixture"}]},
            ]
        }

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    findings, count = lint.check_dependencies([relative])
    assert [item["ruleId"] for item in findings] == ["GHSA-fixture", "GHSA-fixture"]
    assert {item["message"] for item in findings} == {
        "fixture-package 1.0.0: GHSA-fixture",
        "fixture-package 2.0.0: GHSA-fixture",
    }
    expected = 3
    assert count == expected


@pytest.mark.parametrize(
    ("metadata", "text", "rule"),
    [
        ("tools/fixture/package-lock.json", "{}\n", "DEPENDENCY_LOCK_UNAUDITED"),
        ("tools/fixture/package-lock.json", "not-json\n", "DEPENDENCY_LOCK_UNAUDITED"),
        ("tools/fixture/yarn.lock", "lockfile\n", "DEPENDENCY_LOCK_UNAUDITED"),
        ("tools/fixture/poetry.lock", "[metadata]\n", "DEPENDENCY_LOCK_UNAUDITED"),
        ("tools/fixture/pnpm-lock.yaml", "lockfileVersion: 6\n", "DEPENDENCY_LOCK_UNAUDITED"),
        ("services/fixture/requirements.in", "fixture\n", "DEPENDENCY_LOCK_MISSING"),
        ("tools/fixture/package.json", "{}\n", "DEPENDENCY_LOCK_MISSING"),
    ],
)
def test_unsupported_metadata_stays_blocking_without_an_advisory_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata: str,
    text: str,
    rule: str,
) -> None:
    """Unimplemented ecosystems and non-v3 npm files do not look audited."""
    _write(tmp_path, metadata, text)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", _command)

    def post(_packages: object) -> object:
        message = "advisory request"
        raise AssertionError(message)

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    findings, count = lint.check_dependencies([metadata])
    assert [item["ruleId"] for item in findings] == [rule]
    assert findings[0]["location"]["path"] == metadata
    expected = 1
    assert count == expected


def test_lockfile_version_two_stays_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Version 2 documents are not silently treated as the implemented auditor."""
    relative = "tools/fixture/package-lock.json"
    document = _document({"fixture-package": "1.0.0"})
    document["lockfileVersion"] = 2
    _write(tmp_path, relative, json.dumps(document))
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", _command)

    def post(_packages: object) -> object:
        message = "advisory request"
        raise AssertionError(message)

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    findings, count = lint.check_dependencies([relative])
    assert [item["ruleId"] for item in findings] == ["DEPENDENCY_LOCK_UNAUDITED"]
    expected = 1
    assert count == expected


def test_requirement_audit_does_not_call_the_npm_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Python hash checking and its auditor arguments stay on the Python path."""
    relative = "services/fixture/requirements.txt"
    _write(
        tmp_path,
        relative,
        "fixture-package==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\n",
    )
    calls: list[list[str]] = []

    def command(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return _command(argv, **kwargs)

    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", command)

    def post(_packages: object) -> object:
        message = "advisory request"
        raise AssertionError(message)

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    findings, count = lint.check_dependencies([relative])
    assert findings == []
    assert calls[0] == _LOCAL_AUDIT
    assert calls[1][0:6] == [
        "pip-audit",
        "--strict",
        "--disable-pip",
        "--no-deps",
        "--require-hashes",
        "--requirement",
    ]
    assert calls[1][6] == relative
    expected = 2
    assert count == expected


@pytest.mark.parametrize(
    "mutate",
    [
        "resolved",
        "integrity",
        "install",
        "range",
        "missing",
        "peer",
        "path",
    ],
)
def test_unsafe_version_three_lock_refuses_before_the_advisory_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: str
) -> None:
    """Unsafe npm sources never reach the advisory transport."""
    relative = "tools/fixture/npm-shrinkwrap.json"
    document = _document({"fixture-package": "1.0.0"})
    entry = _entry(document, "fixture-package")
    if mutate == "resolved":
        entry["resolved"] = "http://registry.npmjs.org/fixture-package/-/fixture-package-1.0.0.tgz"
    elif mutate == "integrity":
        entry["integrity"] = "sha1-not-a-sha512-digest"
    elif mutate == "install":
        entry["hasInstallScript"] = True
    elif mutate == "range":
        packages = document["packages"]
        assert isinstance(packages, dict)
        root = packages[""]
        assert isinstance(root, dict)
        root["dependencies"] = {"fixture-package": "^1.0.0"}
    elif mutate == "missing":
        entry["dependencies"] = {"missing-package": "^1.0.0"}
    elif mutate == "path":
        packages = document["packages"]
        assert isinstance(packages, dict)
        packages["node_modules/parent/arbitrary/node_modules/fixture-package"] = dict(entry)
    else:
        entry["peerDependencies"] = {"required-peer": "^1.2.3"}
    _write(tmp_path, relative, json.dumps(document))
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", _command)

    def post(_packages: object) -> object:
        message = "advisory request"
        raise AssertionError(message)

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    with pytest.raises(ValueError, match="unsupported or unsafe package sources"):
        lint.node_lock_packages(tmp_path / relative)
    if mutate == "install":
        findings, count = lint.check_dependencies([relative])
        assert count == 1  # Only the local Python environment reached the auditor.
        assert [item["ruleId"] for item in findings] == ["DEPENDENCY_INSTALL_SCRIPT"]
        assert findings[0]["severity"] == "error"
    else:
        with pytest.raises(ValueError, match="unsupported or unsafe package sources"):
            lint.check_dependencies([relative])


def test_compressed_lock_is_bound_to_manifest_and_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compression is a transport detail, not an exception to npm admission."""
    owner = "tools/fixture"
    directory = tmp_path / owner
    directory.mkdir(parents=True)
    lock = directory / "package-lock.json.gz"
    document = _document({"fixture-package": "1.0.0"})
    raw = json.dumps(document).encode()
    lock.write_bytes(gzip.compress(raw))
    packages = document["packages"]
    assert isinstance(packages, dict)
    manifest = directory / "package.json"
    manifest.write_text(json.dumps(packages[""]))
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", _command)
    posted: list[tuple[str, str]] = []

    def post(rows: list[tuple[str, str]]) -> dict[str, object]:
        posted.extend(rows)
        return _clean_report(len(rows))

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    inputs = [f"{owner}/{manifest.name}", f"{owner}/{lock.name}"]
    findings, count = lint.check_dependencies(inputs)
    expected = ["DEPENDENCY_LOCK_MISSING"]
    assert [item["ruleId"] for item in findings] == expected
    assert count == 1 + len(posted)
    rows = sorted(
        {(k.rsplit("node_modules/", 1)[-1], v["version"]) for k, v in packages.items() if k}
    )
    assert posted == rows
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="unsupported or unsafe"):
        lint.check_dependencies(inputs)
    assert posted == rows


@pytest.mark.parametrize(
    "data",
    [gzip.compress(b"x" * 2048), b"not gzip", gzip.compress(b"{}")[:-1]],
)
def test_compressed_lock_refuses_bounded_expansion_and_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: bytes
) -> None:
    """Refuse unreadable or oversized compressed data before parsing any lock."""
    monkeypatch.setattr(lint, "_MAX_REQUIREMENT_LOCK_BYTES", 1024)
    lock = tmp_path / "package-lock.json.gz"
    lock.write_bytes(data)
    with pytest.raises(ValueError, match="unsupported or unsafe"):
        lint.node_lock_packages(lock)


def test_optional_peer_absence_is_still_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicitly optional missing peer does not hide the locked graph."""
    relative = "tools/fixture/package-lock.json"
    document = _document({"@scope/pkg": "1.2.3"})
    entry = _entry(document, "@scope/pkg")
    entry["peerDependencies"] = {"optional-peer": "^1.0.0", "fixture-peer": "^2.0.0"}
    entry["peerDependenciesMeta"] = {"optional-peer": {"optional": True}}
    packages = document["packages"]
    assert isinstance(packages, dict)
    packages["node_modules/fixture-peer"] = {
        "version": "2.0.0",
        "resolved": "https://registry.npmjs.org/fixture-peer/-/fixture-peer-2.0.0.tgz",
        "integrity": _INTEGRITY,
    }
    _write(tmp_path, relative, json.dumps(document))
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", _command)
    posted: list[tuple[str, str]] = []

    def post(packages_sent: list[tuple[str, str]]) -> dict[str, object]:
        posted.extend(packages_sent)
        return _clean_report(len(packages_sent))

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    findings, count = lint.check_dependencies([relative])
    assert findings == []
    assert posted == [("@scope/pkg", "1.2.3"), ("fixture-peer", "2.0.0")]
    expected = 3
    assert count == expected


def test_npm_symlink_and_absolute_path_refuse_before_the_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Links and absolute inventory names are not advisory inputs."""
    target = tmp_path / "actual.json"
    target.write_text(json.dumps(_document({"fixture-package": "1.0.0"})))
    (tmp_path / "package-lock.json").symlink_to(target)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", _command)

    def post(_packages: object) -> object:
        message = "advisory request"
        raise AssertionError(message)

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    with pytest.raises(ValueError, match="tracked regular repository file"):
        lint.check_dependencies(["package-lock.json"])
    with pytest.raises(ValueError, match="tracked regular repository file"):
        lint.check_dependencies(["/package-lock.json"])


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"results": []},
        {"results": [{}, {}]},
        {"results": [None]},
        {"results": [{}], "error": "fixture outage"},
        {"results": [{"error": "fixture outage"}]},
        {"results": [{"next_page_token": "fixture-more"}]},
        {"results": [{"vulns": [], "next_page_token": "fixture-more"}]},
        {"results": [{"next_page_token": None}]},
        {"results": [{"next_page_token": False}]},
        {"results": [{"skipped": True}]},
        {"results": [{"vulns": [], "unknown": True}]},
        {"results": [{"vulns": None}]},
        {"results": [{"vulns": [{}]}]},
        {"results": [{"vulns": [{"id": ""}]}]},
        {"results": [{"vulns": [{"id": "GHSA\nfixture"}]}]},
    ],
)
def test_incomplete_npm_advisory_protocol_never_means_clean(payload: object) -> None:
    """A short, empty or malformed advisory body cannot clear a distribution."""
    packages = [("fixture-package", "1.0.0")]
    with pytest.raises((TypeError, ValueError), match="malformed, empty, or skipped"):
        lint.node_advisory_report(payload, packages, "tools/fixture/package-lock.json")


def test_advisory_batch_uses_direct_tls_without_credential_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The batch request has a fixed host, verified TLS and no auth headers."""
    body = b'{"results":[{"vulns":[{"id":"GHSA-fixture"}]}]}'
    connection = _Connection("unused")
    connection.response = _Response(200, body, oversized=False)

    def factory(*args: object, **kwargs: object) -> _Connection:
        host = args[0] if args else kwargs.get("host")
        timeout = kwargs.get("timeout")
        context = kwargs.get("context")
        assert isinstance(host, str)
        assert isinstance(timeout, int)
        assert isinstance(context, ssl.SSLContext)
        connection.host = host
        connection.timeout = timeout
        connection.context = context
        return connection

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    payload = lint.post_node_advisory_batch([("fixture-package", "1.0.0")])
    assert connection.closed is True
    assert connection.host == "api.osv.dev"
    assert connection.method == "POST"
    assert connection.url == "/v1/querybatch"
    assert connection.context is not None
    assert connection.context.check_hostname is True
    assert connection.context.verify_mode == ssl.CERT_REQUIRED
    assert set(connection.headers) == {"Accept", "Content-Type", "User-Agent"}
    assert "Authorization" not in connection.headers
    decoded = json.loads(connection.body)
    assert decoded == {
        "queries": [
            {"package": {"ecosystem": "npm", "name": "fixture-package"}, "version": "1.0.0"}
        ]
    }
    assert payload == {"results": [{"vulns": [{"id": "GHSA-fixture"}]}]}


@pytest.mark.parametrize(
    "mode", ["status", "json", "transport", "oversized", "duplicate", "nonfinite", "encoding"]
)
def test_advisory_transport_failures_hide_response_bodies(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """Transport failures stay protocol errors and do not echo the response."""
    status = 200
    body = b""
    error: BaseException | None = None
    oversized = False
    if mode == "status":
        status = 503
        body = b'{"advisory-body":"hidden"}'
    elif mode == "json":
        body = b"NOT-JSON-advisory-body"
    elif mode == "transport":
        error = OSError("network-down")
    elif mode == "duplicate":
        body = b'{"results":[{"vulns":[{"id":"fixture"}],"vulns":[]}]}'
    elif mode == "nonfinite":
        body = b'{"results":[{"vulns":NaN}]}'
    elif mode == "encoding":
        body = b"\xff"
    else:
        oversized = True
    connection = _Connection("unused")
    connection.response = _Response(status, body, oversized=oversized)
    connection.error = error

    def factory(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    with pytest.raises(ValueError, match="malformed, empty, or skipped") as caught:
        lint.post_node_advisory_batch([("fixture-package", "1.0.0")])
    message = str(caught.value)
    assert "advisory-body" not in message
    assert "network-down" not in message
    assert caught.value.__cause__ is None
    assert connection.closed is True


def test_advisory_function_does_not_name_credential_files() -> None:
    """The batch function's source does not point at npm or netrc credentials."""
    source = (_REPO / "ci/quality/check_dependencies.py").read_text()
    module = ast.parse(source)
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "post_node_advisory_batch"
    )
    assignments: dict[str, str] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            assignments[target.id] = node.value.value
    statements = function.body
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
    ):
        statements = statements[1:]
    constants = {
        node.value
        for statement in statements
        for node in ast.walk(statement)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    names = {
        node.id
        for statement in statements
        for node in ast.walk(statement)
        if isinstance(node, ast.Name)
    }
    assert assignments["_OSV_HOST"] == "api.osv.dev"
    assert assignments["_OSV_AUDIT_PATH"] == "/v1/querybatch"
    assert "_OSV_HOST" in names
    assert "environ" not in names
    assert "urlopen" not in names
    for forbidden in ("npmrc", "netrc", ".npmrc", "NODE_AUTH_TOKEN", "registry.npmjs.org"):
        assert all(forbidden not in value for value in constants)


@pytest.mark.parametrize(
    "mutation", ["name", "version", "dependency", "workspaces", "override", "duplicate", "symlink"]
)
def test_manifest_drift_refuses_before_advisory_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """A paired lock cannot hide a changed, ambiguous or redirected manifest."""
    relative = "tools/fixture/package-lock.json"
    manifest: dict[str, object] = {
        "name": "fixture",
        "version": "1.0.0",
        "dependencies": {"fixture-package": "1.0.0"},
    }
    if mutation == "name":
        manifest["name"] = "another-package"
    elif mutation == "version":
        manifest["version"] = "2.0.0"
    elif mutation == "dependency":
        manifest["dependencies"] = {"new-package": "1.0.0"}
    elif mutation == "workspaces":
        manifest["workspaces"] = ["packages/*"]
    elif mutation == "override":
        manifest["overrides"] = {"fixture-package": "2.0.0"}
    _write(tmp_path, relative, json.dumps(_document({"fixture-package": "1.0.0"})))
    manifest_path = tmp_path / "tools/fixture/package.json"
    text = json.dumps(manifest)
    if mutation == "duplicate":
        text = text[:-1] + ',"dependencies":{}}'
    _write(tmp_path, "tools/fixture/package.json", text)
    if mutation == "symlink":
        original = manifest_path.with_name("manifest-source.json")
        manifest_path.rename(original)
        manifest_path.symlink_to(original)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "command", _command)

    def post(_packages: object) -> object:
        message = "advisory transport must not run"
        raise AssertionError(message)

    monkeypatch.setattr(lint, "post_node_advisory_batch", post)
    refusal = (
        "Dependency metadata must be a tracked regular repository file"
        if mutation == "symlink"
        else "npm lock contains unsupported or unsafe package sources"
    )
    with pytest.raises(ValueError, match=refusal):
        lint.check_dependencies([relative, "tools/fixture/package.json"])


def test_docker_selector_proof_refuses_argument_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated selector input cannot masquerade as the reviewed expansion."""
    source = (_REPO / _owner("check_docker")).read_text()
    original = "files = docker_targets(names)"
    assert source.count(original) == 1
    destination = tmp_path / _owner("check_docker")
    destination.parent.mkdir(parents=True)
    destination.write_text(source.replace(original, "files = docker_targets(names[:1])"))
    monkeypatch.setattr(sys.modules[__name__], "_REPO", tmp_path)
    with pytest.raises(AssertionError, match="Unexpected Docker selector shape"):
        _digest("check_docker")


@pytest.mark.parametrize(
    ("name", "original", "replacement"),
    [
        ("check_docker", '"--config"', '"--wrong-config"'),
        ("check_javascript", '["node", "--check", path]', '["node", "--version", path]'),
        ("check_workflow", "security + expressions + directives", "security + expressions + []"),
        ("check_actions", '"--strict-collection"', '"--invalid-collection"'),
        ("check_actionlint", '"-config-file", os.devnull', '"-unreviewed-config", os.devnull'),
    ],
)
def test_docker_selector_proof_preserves_surrounding_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, original: str, replacement: str
) -> None:
    """A changed dispatch or extracted producer still invalidates its fingerprint."""
    assert _digest(name) == _UNCHANGED_FUNCTION_DIGESTS[name]
    source = (_REPO / _owner(name)).read_text()
    assert source.count(original) == 1
    destination = tmp_path / _owner(name)
    destination.parent.mkdir(parents=True)
    assert replacement not in source
    destination.write_text(source.replace(original, replacement, 1))
    rewritten = destination.read_text()
    assert rewritten.count(replacement) == 1
    assert original not in rewritten
    monkeypatch.setattr(sys.modules[__name__], "_REPO", tmp_path)
    assert _digest(name) != _UNCHANGED_FUNCTION_DIGESTS[name]


def test_python_decoder_proof_refuses_wrong_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewed strict decoder cannot silently switch from stdout to stderr."""
    source = (_REPO / "ci/quality/check_dependencies.py").read_text()
    original = "_python_audit_payload(process.stdout)"
    assert source.count(original) == 1
    destination = tmp_path / "ci/quality/check_dependencies.py"
    destination.parent.mkdir(parents=True)
    destination.write_text(source.replace(original, "_python_audit_payload(process.stderr)"))
    monkeypatch.setattr(sys.modules[__name__], "_REPO", tmp_path)
    with pytest.raises(AssertionError, match="Unexpected Python audit decoder"):
        _digest("_audit_python_source")


def test_skip_presence_proof_refuses_empty_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A syntactically similar guard that never observes the row must be rejected."""
    source = (_REPO / "ci/quality/check_dependencies.py").read_text()
    original = 'if "skip_reason" in value:'
    assert source.count(original) == 1
    destination = tmp_path / "ci/quality/check_dependencies.py"
    destination.parent.mkdir(parents=True)
    destination.write_text(source.replace(original, 'if "skip_reason" in {}:'))
    monkeypatch.setattr(sys.modules[__name__], "_REPO", tmp_path)
    with pytest.raises(AssertionError, match="Unexpected skipped-distribution guard"):
        _digest("_distribution_fields")


@pytest.mark.parametrize(
    "mutation", ["digest", "path", "version", "owner", "hook", "manifest", "dropped", "nested"]
)
def test_reviewed_archive_admission_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """A local source is not a generic file: exception or an advisory exemption."""
    relative = "tools/elsewhere/package-lock.json" if mutation == "owner" else _OWNED_LOCK
    lock = tmp_path / relative
    lock.parent.mkdir(parents=True)
    document = json.loads((_REPO / _OWNED_LOCK).read_bytes())
    entry = document["packages"]["node_modules/argocd-mcp"]
    manifest = document["packages"][""]
    if mutation == "digest":
        entry["integrity"] = _INTEGRITY
    elif mutation == "path":
        entry["resolved"] = "file:../other.tar"
    elif mutation == "version":
        entry["version"] = "0.9.1"
    elif mutation == "hook":
        entry["hasInstallScript"] = True
    elif mutation == "dropped":
        del manifest["dependencies"]["argocd-mcp"]
    elif mutation == "nested":
        document["packages"]["node_modules/@umami/mcp/node_modules/argocd-mcp"] = entry
    lock.write_text(json.dumps(document))
    if mutation == "manifest":
        manifest["dependencies"]["argocd-mcp"] = "0.9.0"
    lock.with_name("package.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    if mutation == "hook":
        findings, count = lint._npm_lock_audit(lock, relative)
        assert count == 0
        assert [finding["ruleId"] for finding in findings] == ["DEPENDENCY_INSTALL_SCRIPT"]
        return
    with pytest.raises(ValueError, match="unsupported or unsafe"):
        lint.node_lock_packages(lock)
