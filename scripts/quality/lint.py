"""Portable static linters; subprocesses only parse source, never run operational code."""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import gzip
import http.client
import io
import json
import math
import os
import re
import shutil
import ssl
import sys
import tempfile
import tokenize
import zlib
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scripts.quality.common import Finding

from common import ROOT, command, failure, finding, owned, report, tracked, use_project_tools

MYPY_ERROR = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?:\d+:)? (?P<level>error|warning): "
    r"(?P<message>.*?)(?:\s+\[(?P<code>[A-Za-z0-9_-]+)\])?$"
)
GITHUB_EXPR = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


class LintToolError(RuntimeError):
    """Raised when a lint subprocess emits output that cannot be parsed."""


_DEPENDENCY_PROTOCOL_FAILURE = "Dependency audit returned malformed, empty, or skipped data"
_DEPENDENCY_PATH_FAILURE = "Dependency metadata must be a tracked regular repository file"
_DEPENDENCY_REQUIREMENT_FAILURE = (
    "Requirement lock contains unsupported or unsafe source directives"
)
_MAX_REQUIREMENT_LOCK_BYTES = 4 * 1024 * 1024
_PINNED_REQUIREMENT = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_.,-]+\])?"
    r"==[A-Za-z0-9][A-Za-z0-9_.+!-]*(?:\s*;[^\n]*)?"
)
_REQUIREMENT_HASH = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}")
_NPM_LOCKFILE_VERSION = 3
_MAX_NPM_DISTRIBUTIONS = 1000
_MAX_ADVISORY_RESPONSE_BYTES = _MAX_REQUIREMENT_LOCK_BYTES
_OSV_HOST = "api.osv.dev"
_OSV_AUDIT_PATH = "/v1/querybatch"
_OSV_TIMEOUT_SECONDS = 30
_OSV_SUCCESS_STATUS = 200
_SHA512_DIGEST_BYTES = 64
_MAX_PACKAGE_PATH_SEGMENTS = 32
_BARE_NAME_SEGMENTS = 1
_SCOPED_NAME_SEGMENTS = 2
_NPM_NAME_PART = r"[a-z0-9~_][a-z0-9._~_-]*"
_NPM_NAME = re.compile(rf"^(?:@{_NPM_NAME_PART}/)?{_NPM_NAME_PART}$")
_NPM_VERSION = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_NPM_RANGE = re.compile(r"^[0-9A-Za-z^~<>=.* |_xX-]+$")
_NPM_LOCK_KEYS = frozenset({"name", "version", "lockfileVersion", "requires", "packages"})
_NPM_ROOT_KEYS = frozenset(
    {"name", "version", "dependencies", "devDependencies", "optionalDependencies"}
)
_NPM_PACKAGE_KEYS = frozenset(
    {
        "bin",
        "cpu",
        "dependencies",
        "dev",
        "devDependencies",
        "engines",
        "funding",
        "hasInstallScript",
        "inBundle",
        "integrity",
        "license",
        "link",
        "name",
        "optional",
        "optionalDependencies",
        "os",
        "peer",
        "peerDependencies",
        "peerDependenciesMeta",
        "resolved",
        "version",
    }
)
_NPM_LOCK_NAMES = ("package-lock.json", "npm-shrinkwrap.json", "package-lock.json.gz")
_NPM_ROOT_DEP_FIELDS = ("dependencies", "devDependencies", "optionalDependencies")
_NPM_NESTED_DEP_FIELDS = ("dependencies", "devDependencies", "optionalDependencies")
_DEPENDENCY_NPM_LOCK_FAILURE = "npm lock contains unsupported or unsafe package sources"


def validate_requirement_lock(path: Path) -> None:
    """Refuse includes, indexes and direct references before an auditor can read them."""
    if path.stat().st_size > _MAX_REQUIREMENT_LOCK_BYTES:
        raise ValueError(_DEPENDENCY_REQUIREMENT_FAILURE)
    pinned = False
    hashed = False
    for line in path.read_text().splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        candidate = candidate.removesuffix("\\").strip()
        if _REQUIREMENT_HASH.fullmatch(candidate) and pinned:
            hashed = True
        elif _PINNED_REQUIREMENT.fullmatch(candidate):
            pinned = True
        else:
            raise ValueError(_DEPENDENCY_REQUIREMENT_FAILURE)
    if not pinned or not hashed:
        raise ValueError(_DEPENDENCY_REQUIREMENT_FAILURE)


def validate_requirement_hashes(path: Path) -> None:
    """Retain legacy source validation and require a hash for every pinned entry."""
    validate_requirement_lock(path)
    pending_hash = False
    for line in path.read_text().splitlines():
        candidate = line.strip().removesuffix("\\").strip()
        if not candidate or candidate.startswith("#"):
            continue
        if _PINNED_REQUIREMENT.fullmatch(candidate):
            if pending_hash:
                raise ValueError(_DEPENDENCY_REQUIREMENT_FAILURE)
            pending_hash = True
        elif _REQUIREMENT_HASH.fullmatch(candidate):
            pending_hash = False
    if pending_hash:
        raise ValueError(_DEPENDENCY_REQUIREMENT_FAILURE)


def _distribution_fields(value: object) -> tuple[str, str, list[object]]:
    """Validate a collected distribution without trusting the auditor's JSON shape."""
    if not isinstance(value, dict):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    if "skip_reason" in value:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    name, version, vulnerabilities = value.get("name"), value.get("version"), value.get("vulns")
    if not isinstance(name, str) or not isinstance(version, str):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    if not name or not version:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    if not isinstance(vulnerabilities, list):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    return name, version, list(vulnerabilities)


def _vulnerability_id(value: object) -> str:
    """Reject malformed advisory identities instead of silently omitting them."""
    if not isinstance(value, dict):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    identity = value.get("id")
    if not isinstance(identity, str):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    if not identity:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    return identity


def dependency_report(payload: object, source: str) -> tuple[list[Finding], int]:
    """Retain every distribution vulnerability and reject incomplete audit protocols."""
    if not isinstance(payload, dict):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    rows = payload.get("dependencies")
    if not isinstance(rows, list):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    if not rows:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    findings: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        name, version, vulnerabilities = _distribution_fields(row)
        for vulnerability in vulnerabilities:
            identity = _vulnerability_id(vulnerability)
            key = (name, version, identity)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                finding(
                    identity,
                    source,
                    1,
                    f"{name} {version}: {identity}",
                    f"{name}:{version}:{identity}",
                )
            )
    return findings, len(rows)


def _audit_python_source(argv: Sequence[str], source: str) -> tuple[list[Finding], int]:
    """Bind the auditor's exit status to its complete vulnerability report."""
    process = command(argv, allowed=(0, 1), timeout=300)
    findings, count = dependency_report(_python_audit_payload(process.stdout), source)
    if (process.returncode == 0) != (not findings):
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    return findings, count


def _finite_audit_float(value: str) -> float:
    """Reject JSON exponents that overflow into an infinite Python float."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    return number


def _python_audit_payload(text: str) -> object:
    """Refuse ambiguous or nonfinite audit JSON without echoing its payload."""
    try:
        payload: object = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_nonfinite_json,
            parse_float=_finite_audit_float,
        )
    except ValueError:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE) from None
    return payload


def _string_key_dict(value: object) -> dict[str, object] | None:
    """Copy a JSON object whose keys are strings."""
    if not isinstance(value, dict):
        return None
    copied: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        copied[key] = item
    return copied


def _read_lock_text(path: Path) -> str | None:
    """Read one regular lock file, refusing links and oversized inputs."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(_DEPENDENCY_PATH_FAILURE)
    size = path.stat().st_size
    if size > _MAX_REQUIREMENT_LOCK_BYTES:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    raw = path.read_bytes()
    if len(raw) != size or len(raw) > _MAX_REQUIREMENT_LOCK_BYTES:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    if path.name == "package-lock.json.gz":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                raw = compressed.read(_MAX_REQUIREMENT_LOCK_BYTES + 1)
        except (OSError, EOFError, zlib.error):
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE) from None
        if len(raw) > _MAX_REQUIREMENT_LOCK_BYTES:
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys instead of silently replacing earlier findings."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
        result[key] = value
    return result


def _reject_nonfinite_json(_value: str) -> None:
    """Reject JavaScript constants that are not valid JSON numbers."""
    raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)


def _parse_json_value(text: str) -> object | None:
    """Parse JSON without treating a decode error as an empty audit."""
    try:
        value: object = json.loads(
            text, object_pairs_hook=_unique_json_object, parse_constant=_reject_nonfinite_json
        )
    except ValueError:
        return None
    return value


def _sha512_integrity(value: object) -> bool:
    """Accept one sha512 Subresource Integrity digest and nothing else."""
    if not isinstance(value, str) or not value.startswith("sha512-"):
        return False
    try:
        digest = base64.b64decode(value.removeprefix("sha512-"), validate=True)
    except binascii.Error:
        return False
    return len(digest) == _SHA512_DIGEST_BYTES


def _registry_tarball(name: str, version: str) -> str:
    """Return the canonical npmjs tarball URL for one exact distribution."""
    filename = name.rsplit("/", 1)[-1]
    return f"https://registry.npmjs.org/{name}/-/{filename}-{version}.tgz"


def _package_name(package_path: str) -> str:
    """Derive the npm package name from a lockfileVersion 3 packages key."""
    if (
        not package_path.startswith("node_modules/")
        or "\\" in package_path
        or len(package_path.split("/")) > _MAX_PACKAGE_PATH_SEGMENTS
    ):
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    segments = package_path.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    indexes = [index for index, segment in enumerate(segments) if segment == "node_modules"]
    for start, end in zip(indexes, [*indexes[1:], len(segments)], strict=True):
        component = "/".join(segments[start + 1 : end])
        if _NPM_NAME.fullmatch(component) is None:
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    rest = segments[indexes[-1] + 1 :]
    if len(rest) == _BARE_NAME_SEGMENTS:
        name = rest[0]
    elif len(rest) == _SCOPED_NAME_SEGMENTS and rest[0].startswith("@") and len(rest[0]) > 1:
        name = f"{rest[0]}/{rest[1]}"
    else:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    if _NPM_NAME.fullmatch(name) is None or not package_path.endswith("node_modules/" + name):
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    return name


def _plausible_range(spec: str) -> bool:
    """Reject alternate sources while still allowing ordinary npm version ranges."""
    if _NPM_RANGE.fullmatch(spec) is None:
        return False
    return any(character.isdigit() or character in "*xX" for character in spec)


def _dependency_map(value: object, *, exact: bool) -> dict[str, str]:
    """Parse a dependency map, refusing aliases, URLs and non-string specs."""
    if value is None:
        return {}
    mapping = _string_key_dict(value)
    if mapping is None:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    parsed: dict[str, str] = {}
    for name, spec in mapping.items():
        if _NPM_NAME.fullmatch(name) is None or not isinstance(spec, str):
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
        allowed = _NPM_VERSION.fullmatch(spec) is not None if exact else _plausible_range(spec)
        if not allowed:
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
        parsed[name] = spec
    return parsed


def _disabled_flag(meta: dict[str, object], key: str) -> None:
    """Refuse metadata that would select install scripts, links or bundles."""
    value = meta.get(key)
    if value is True:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    if value is not None and value is not False:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)


def _optional_peers(meta: dict[str, object]) -> set[str]:
    """Return peer names explicitly marked optional."""
    raw = meta.get("peerDependenciesMeta")
    if raw is None:
        return set()
    mapping = _string_key_dict(raw)
    if mapping is None:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    optional: set[str] = set()
    for name, item in mapping.items():
        if _NPM_NAME.fullmatch(name) is None or not isinstance(item, dict):
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
        flag = item.get("optional")
        if flag is True:
            optional.add(name)
        elif flag is not False and flag is not None:
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    return optional


def _npm_lock_document(path: Path) -> dict[str, object] | None:
    """Return a lockfileVersion 3 object, or None when this is not that document."""
    text = _read_lock_text(path)
    if text is None:
        return None
    value = _parse_json_value(text)
    document = _string_key_dict(value)
    if document is None:
        return None
    version = document.get("lockfileVersion")
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    if version != _NPM_LOCKFILE_VERSION:
        return None
    if set(document) != _NPM_LOCK_KEYS or document.get("requires") is not True:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    return document


def _distribution(package_path: str, meta: object) -> tuple[str, str]:
    """Validate one registry distribution and return its name and exact version."""
    parsed = _string_key_dict(meta)
    if parsed is None or set(parsed) - _NPM_PACKAGE_KEYS:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    for key in ("hasInstallScript", "inBundle", "link"):
        _disabled_flag(parsed, key)
    for key in ("dev", "optional", "peer"):
        value = parsed.get(key)
        if value is not None and not isinstance(value, bool):
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    name = _package_name(package_path)
    version = parsed.get("version")
    if not isinstance(version, str) or _NPM_VERSION.fullmatch(version) is None:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    if parsed.get("resolved") != _registry_tarball(name, version):
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    if not _sha512_integrity(parsed.get("integrity")):
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    declared = parsed.get("name")
    if declared is not None and declared != name:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    return name, version


def _root_pins(root: dict[str, object]) -> dict[str, str]:
    """Return exact root pins from every direct dependency map."""
    if set(root) - _NPM_ROOT_KEYS:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    pins: dict[str, str] = {}
    for field in _NPM_ROOT_DEP_FIELDS:
        for name, version in _dependency_map(root.get(field), exact=True).items():
            previous = pins.get(name)
            if previous is not None and previous != version:
                raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
            pins[name] = version
    return pins


def _lock_identity(document: dict[str, object]) -> tuple[str, str, dict[str, object]]:
    """Return the root name, version and packages map for one version 3 lock."""
    name = document.get("name")
    version = document.get("version")
    packages = _string_key_dict(document.get("packages"))
    if (
        packages is None
        or not isinstance(name, str)
        or _NPM_NAME.fullmatch(name) is None
        or not isinstance(version, str)
        or _NPM_VERSION.fullmatch(version) is None
    ):
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    return name, version, packages


class _InstallScriptsError(ValueError):
    """A lock must be refused before transport if any package selects install scripts."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages
        super().__init__(_DEPENDENCY_NPM_LOCK_FAILURE)


def _located_distributions(packages: dict[str, object]) -> dict[str, tuple[str, str]]:
    """Validate every non-root package entry before any advisory request."""
    scripted = [
        _package_name(path)
        for path, entry in packages.items()
        if path and isinstance(entry, dict) and entry.get("hasInstallScript") is True
    ]
    if scripted:
        raise _InstallScriptsError(sorted(set(scripted)))
    located: dict[str, tuple[str, str]] = {}
    for package_path, meta in packages.items():
        if package_path == "":
            continue
        located[package_path] = _distribution(package_path, meta)
    if not located or len(located) > _MAX_NPM_DISTRIBUTIONS:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    return located


def _require_root_pins(located: dict[str, tuple[str, str]], pins: dict[str, str]) -> None:
    """Require each exact root pin to match its top-level package entry."""
    for dep, spec in pins.items():
        if located.get(f"node_modules/{dep}") != (dep, spec):
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)


def _require_graph_names(parsed: dict[str, object], names: set[str]) -> None:
    """Require declared dependencies to exist in the locked distribution set."""
    for field in _NPM_NESTED_DEP_FIELDS:
        for dep in _dependency_map(parsed.get(field), exact=False):
            if dep not in names:
                raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    optional = _optional_peers(parsed)
    for dep in _dependency_map(parsed.get("peerDependencies"), exact=False):
        if dep not in names and dep not in optional:
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)


def _require_named_dependencies(packages: dict[str, object], names: set[str]) -> None:
    """Apply the graph check to every non-root package entry."""
    for package_path, meta in packages.items():
        if package_path == "":
            continue
        parsed = _string_key_dict(meta)
        if parsed is None:
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
        _require_graph_names(parsed, names)


def _unique_distributions(
    located: dict[str, tuple[str, str]],
) -> list[tuple[str, str]]:
    """Return sorted unique distributions without dropping distinct versions."""
    unique = set(located.values())
    if len(unique) > _MAX_NPM_DISTRIBUTIONS:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    return sorted(unique)


def _require_matching_npm_manifest(path: Path, root: dict[str, object]) -> None:
    """Bind a present manifest to its lock; never skip newly declared dependencies."""
    manifest_path = path.with_name("package.json")
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return
    text = _read_lock_text(manifest_path)
    manifest = _string_key_dict(_parse_json_value(text)) if text is not None else None
    if manifest is None:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    if set(manifest) & {
        "overrides",
        "resolutions",
        "workspaces",
        "bundledDependencies",
        "bundleDependencies",
    }:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    if manifest.get("name") != root.get("name") or manifest.get("version") != root.get("version"):
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    for field in _NPM_ROOT_DEP_FIELDS:
        declared = _dependency_map(manifest.get(field), exact=True)
        if declared != _dependency_map(root.get(field), exact=True):
            raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)


def node_lock_packages(path: Path) -> list[tuple[str, str]] | None:
    """Return every exact npm distribution in a supported lock, without fetching it.

    None means the file is not a lockfileVersion 3 document and must stay a
    blocking coverage finding. A version 3 document with unsafe sources raises
    before any advisory request.
    """
    document = _npm_lock_document(path)
    if document is None:
        return None
    name, version, packages = _lock_identity(document)
    root = _string_key_dict(packages.get(""))
    if root is None or root.get("name") != name or root.get("version") != version:
        raise ValueError(_DEPENDENCY_NPM_LOCK_FAILURE)
    _require_matching_npm_manifest(path, root)
    located = _located_distributions(packages)
    _require_root_pins(located, _root_pins(root))
    names = {dep for dep, _spec in located.values()}
    _require_named_dependencies(packages, names)
    return _unique_distributions(located)


def _advisory_ids(result: object) -> list[str]:
    """Return advisory identities for one distribution, rejecting malformed rows."""
    if not isinstance(result, dict):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    if set(result) - {"vulns", "next_page_token"}:
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    token = result.get("next_page_token", "")
    if not isinstance(token, str) or token:
        # Until pagination is implemented, incomplete results remain blocking.
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    if "vulns" not in result:
        return []
    vulns = result["vulns"]
    if not isinstance(vulns, list):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    identities: list[str] = []
    for item in vulns:
        parsed = _string_key_dict(item)
        if parsed is None:
            raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
        identity = parsed.get("id")
        if not isinstance(identity, str):
            raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
        if not identity or any(character in identity for character in "\n\r\x00"):
            raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
        identities.append(identity)
    return identities


def node_advisory_report(
    payload: object,
    packages: Sequence[tuple[str, str]],
    source: str,
) -> tuple[list[Finding], int]:
    """Retain every advisory for the exact locked distributions and reject gaps."""
    if not isinstance(payload, dict) or set(payload) != {"results"}:
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    results = payload.get("results")
    if not isinstance(results, list):
        raise TypeError(_DEPENDENCY_PROTOCOL_FAILURE)
    if not packages or len(results) != len(packages):
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    findings: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()
    for (name, version), result in zip(packages, results, strict=True):
        for identity in _advisory_ids(result):
            key = (name, version, identity)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                finding(
                    identity,
                    source,
                    1,
                    f"{name} {version}: {identity}",
                    f"{name}:{version}:{identity}",
                )
            )
    return findings, len(packages)


def post_node_advisory_batch(packages: Sequence[tuple[str, str]]) -> object:
    """Ask the fixed OSV batch endpoint about exact npm distributions.

    The connection is a direct TLS request to api.osv.dev. It does not read npm
    configuration, environment credentials, proxies, netrc or package tarballs,
    and it does not run lifecycle scripts or install anything.
    """
    if not packages or len(packages) > _MAX_NPM_DISTRIBUTIONS:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    queries: list[dict[str, object]] = []
    for name, version in packages:
        if _NPM_NAME.fullmatch(name) is None or _NPM_VERSION.fullmatch(version) is None:
            raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
        queries.append({"package": {"ecosystem": "npm", "name": name}, "version": version})
    body = json.dumps({"queries": queries}, separators=(",", ":")).encode("utf-8")
    if len(body) > _MAX_ADVISORY_RESPONSE_BYTES:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(
        _OSV_HOST,
        timeout=_OSV_TIMEOUT_SECONDS,
        context=context,
    )
    try:
        connection.request(
            "POST",
            _OSV_AUDIT_PATH,
            body=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "homelab-quality-node-lock-audit",
            },
        )
        response = connection.getresponse()
        status = response.status
        raw = response.read(_MAX_ADVISORY_RESPONSE_BYTES + 1)
    except (http.client.HTTPException, OSError):
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE) from None
    finally:
        connection.close()
    if status != _OSV_SUCCESS_STATUS or not raw or len(raw) > _MAX_ADVISORY_RESPONSE_BYTES:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE)
    try:
        decoded: object = json.loads(
            raw, object_pairs_hook=_unique_json_object, parse_constant=_reject_nonfinite_json
        )
    except ValueError:
        raise ValueError(_DEPENDENCY_PROTOCOL_FAILURE) from None
    return decoded


def _npm_lock_audit(path: Path, source: str) -> tuple[list[Finding], int] | None:
    """Audit one npm lock. None keeps an unsupported document blocking."""
    try:
        packages = node_lock_packages(path)
    except _InstallScriptsError as error:
        return [
            finding(
                "DEPENDENCY_INSTALL_SCRIPT",
                source,
                1,
                f"{package} declares an install script; lock refused before advisory lookup.",
                package,
            )
            for package in error.packages
        ], 0
    if packages is None:
        return None
    payload = post_node_advisory_batch(packages)
    return node_advisory_report(payload, packages, source)


def _unimplemented_lock_finding(rule: str, name: str) -> Finding:
    """Report one blocking coverage gap without calling it a vulnerability."""
    result: Finding = finding(
        rule,
        name,
        1,
        "Owned dependency metadata lacks complete implemented lockfile auditing.",
        name,
    )
    return result


def check_dependencies(names: Sequence[str]) -> tuple[list[Finding], int]:
    """Audit Python locks and npm lockfileVersion 3 graphs without installing them.

    Requirement hashes and pip-audit exit binding stay in place. Other lock
    ecosystems still produce blocking coverage findings.
    """
    findings, count = _audit_python_source(
        ["pip-audit", "--local", "--strict", "--format", "json"], "uv.lock"
    )
    inventory = set(names)
    for name in sorted(inventory):
        path = Path(name)
        alternate_requirement = path.name.endswith("-requirements.txt")
        requirement = (
            alternate_requirement
            or path.name == "requirements.txt"
            or (path.name.startswith("requirements-") and path.suffix == ".txt")
        )
        npm_lock = path.name in _NPM_LOCK_NAMES
        other_lock = path.name in {
            "poetry.lock",
            "Pipfile.lock",
            "pnpm-lock.yaml",
            "yarn.lock",
            "bun.lock",
            "bun.lockb",
            "pylock.toml",
        } or (path.name == "uv.lock" and name != "uv.lock")
        missing_lock = (
            path.name == "requirements.in" and str(path.with_suffix(".txt")) not in inventory
        ) or (
            path.name == "package.json"
            and not any(
                str(path.with_name(lock)) in inventory
                for lock in (
                    *_NPM_LOCK_NAMES,
                    "pnpm-lock.yaml",
                    "yarn.lock",
                    "bun.lock",
                    "bun.lockb",
                )
            )
        )
        if not (requirement or npm_lock or other_lock or missing_lock):
            continue
        actual = ROOT / path
        if path.is_absolute() or not actual.resolve().is_relative_to(ROOT):
            raise ValueError(_DEPENDENCY_PATH_FAILURE)
        if actual.is_symlink() or not actual.is_file():
            raise ValueError(_DEPENDENCY_PATH_FAILURE)
        if requirement:
            try:
                validate_requirement_hashes(actual)
            except ValueError:
                if not alternate_requirement:
                    raise
                findings.append(
                    finding(
                        "DEPENDENCY_LOCK_INVALID",
                        name,
                        1,
                        "Owned Python requirement source is not a complete safe hashed lock.",
                        name,
                    )
                )
                continue
            rows, scanned = _audit_python_source(
                [
                    "pip-audit",
                    "--strict",
                    "--disable-pip",
                    "--no-deps",
                    "--require-hashes",
                    "--requirement",
                    name,
                    "--format",
                    "json",
                ],
                name,
            )
            findings.extend(rows)
            count += scanned
        elif npm_lock:
            audited = _npm_lock_audit(actual, name)
            if audited is None:
                findings.append(_unimplemented_lock_finding("DEPENDENCY_LOCK_UNAUDITED", name))
            else:
                rows, scanned = audited
                findings.extend(rows)
                count += scanned
        else:
            rule = "DEPENDENCY_LOCK_MISSING" if missing_lock else "DEPENDENCY_LOCK_UNAUDITED"
            findings.append(_unimplemented_lock_finding(rule, name))
    return findings, count


def sarif(data, prefix=""):
    """Execute sarif."""
    result = []
    for run in data["runs"]:
        for item in run.get("results", []):
            location = item.get("locations", [])[0]["physicalLocation"]
            path = unquote(location["artifactLocation"]["uri"])
            if path.startswith("file:"):
                path = urlparse(path).path
            if not Path(path).is_absolute() and not (ROOT / path).is_file():
                path = str(Path(prefix) / path)
            rule = item["ruleId"]
            line = location.get("region", {}).get("startLine", 1)
            result.append(finding(rule, path, line, f"{rule}: inspect this source location."))
    return result


def nonsecret_tokenizer_option(path, item):
    """Execute nonsecret_tokenizer_option."""
    # DL3064 matches TOKENIZERS as though it were a credential. This exact
    # public runtime option line contains no secret; any edit loses the exception.
    if path != "services/spi-tokenizer/Dockerfile" or item["code"] != "DL3064":
        return False
    line = (ROOT / path).read_text().splitlines()[item["line"] - 1]
    return line == "ENV TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1 PYTHONPATH=/app"


def yaml_targets(names):
    # Helm and Ansible templates are Go/Jinja text, not YAML documents.
    """Execute yaml_targets."""
    return [
        p
        for p in names
        if p.endswith((".yml", ".yaml")) and "/templates/" not in p and not p.endswith(".j2")
    ]


def shell_targets(names):
    """Execute shell_targets."""
    result = []
    for name in names:
        if "/templates/" in name or name.endswith(".j2"):
            continue
        if name.endswith(".sh"):
            result.append(name)
            continue
        if Path(name).suffix:
            continue
        try:
            first = (ROOT / name).read_text(errors="ignore").splitlines()[:1]
        except OSError:
            continue
        if first and first[0].startswith("#!") and re.search(r"(?:bash|dash|ksh|\bsh)\b", first[0]):
            result.append(name)
    return result


def shell_dialect(spec):
    """Execute shell_dialect."""
    token = spec.split()[0]
    if token in {"bash", "sh", "dash", "ksh"}:
        return token
    if token in {"python", "python3"}:
        return "python"
    return None


def walk_runs(node, shell="bash"):
    """Execute walk_runs."""
    if isinstance(node, dict):
        current = node["shell"] if isinstance(node.get("shell"), str) else shell
        script = node.get("run")
        if isinstance(script, str) and script.strip():
            yield current, script
        for key, value in node.items():
            if key != "run":
                yield from walk_runs(value, current)
    elif isinstance(node, list):
        for item in node:
            yield from walk_runs(item, shell)


def workflow_runs(names):
    """Execute workflow_runs."""
    import yaml

    result = []
    for name in names:
        if not name.startswith(".github/") or not name.endswith((".yml", ".yaml")):
            continue
        if "/templates/" in name:
            continue
        try:
            document = yaml.safe_load((ROOT / name).read_text())
        except yaml.YAMLError:
            continue
        for spec, script in walk_runs(document):
            result.append((name, spec, script))
    return result


def workflow_files(names):
    """Execute workflow_files."""
    return [
        p for p in names if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    ]


def parse_mypy(text):
    """Execute parse_mypy."""
    result = []
    for line in text.splitlines():
        match = MYPY_ERROR.match(line)
        if not match:
            continue
        result.append(
            finding(
                match.group("code") or "mypy",
                match.group("path"),
                int(match.group("line")),
                match.group("message"),
            )
        )
    return result


def mypy_argv(files):
    """Execute mypy_argv."""
    return [
        "mypy",
        "--config-file",
        "quality/mypy.ini",
        "--no-error-summary",
        "--no-pretty",
        "--no-color-output",
        "--hide-error-context",
        "--show-error-codes",
        "--follow-imports=silent",
        "--no-incremental",
        *files,
    ]


def mypy_status(parsed, code, text):
    """Separate a finished type-check from a fatal run that did not cover its files."""
    if any(
        marker in text
        for marker in (
            "Duplicate module",
            "Traceback (most recent call last)",
            "INTERNAL ERROR",
        )
    ):
        return "incomplete"
    if code in (0, 1):
        return "complete"
    if code == 2 and parsed and all(item["ruleId"] == "syntax" for item in parsed):
        return "syntax"
    return "incomplete"


def mypy_invoke(files, timeout):
    """Execute mypy_invoke."""
    process = command(mypy_argv(files), allowed=(0, 1, 2), timeout=timeout)
    parsed = parse_mypy(process.stdout) + parse_mypy(process.stderr)
    text = process.stdout + "\n" + process.stderr
    return parsed, mypy_status(parsed, process.returncode, text)


def python_syntax_findings(files):
    """Real parser failures. They must not abort type-checking of every other file."""
    findings = []
    clean = []
    for name in files:
        source = (ROOT / name).read_text()
        try:
            ast.parse(source, filename=name)
        except (SyntaxError, ValueError) as error:
            line = error.lineno if isinstance(error, SyntaxError) and error.lineno else 1
            findings.append(
                finding(
                    "python-syntax",
                    name,
                    line,
                    "Python parser rejected this file before type checking.",
                )
            )
        else:
            clean.append(name)
    return findings, clean


def mypy_on(files, timeout):
    """Execute mypy_on."""
    if not files:
        return []
    parsed, status = mypy_invoke(files, timeout)
    if status == "complete":
        return parsed
    if len(files) == 1:
        if status == "syntax":
            return parsed
        raise RuntimeError("mypy coverage incomplete")
    groups = {}
    for name in files:
        groups.setdefault(str(Path(name).parent), []).append(name)
    if len(groups) == 1 or len(groups) == len(files):
        result = []
        for name in files:
            result.extend(mypy_on([name], min(timeout, 180)))
        return result
    result = []
    for group in groups.values():
        result.extend(mypy_on(group, min(timeout, 600)))
    return result


def mypy_findings(files):
    """Execute mypy_findings."""
    syntax, remaining = python_syntax_findings(files)
    syntax_names = {item["location"]["path"] for item in syntax}
    if syntax_names | set(remaining) != set(files) or syntax_names & set(remaining):
        raise RuntimeError("mypy coverage incomplete")
    # Exit 2 is a fatal mypy stop. Retry smaller sets instead of keeping a partial report.
    return syntax + mypy_on(remaining, 2400)


def format_findings(files):
    """Execute format_findings."""
    process = command(
        ["ruff", "format", "--check", "--config", "quality/ruff.toml", *files],
        allowed=(0, 1, 2),
        timeout=300,
    )
    result = []
    for line in process.stderr.splitlines():
        marker = "Failed to parse "
        if marker not in line:
            continue
        detail = line.split(marker, 1)[1]
        path, separator, rest = detail.partition(":")
        line_no, _, message = rest.partition(":")
        if not separator or not line_no.isdigit():
            continue
        result.append(
            finding(
                "ruff-syntax",
                path.strip(),
                int(line_no),
                message.strip() or "Ruff could not parse this file",
            )
        )
    if process.returncode:
        for line in process.stdout.splitlines():
            prefix = "Would reformat: "
            if line.startswith(prefix):
                result.append(
                    finding(
                        "ruff-format",
                        line.removeprefix(prefix).strip(),
                        1,
                        "Ruff format check failed",
                    )
                )
    if process.returncode not in (0, 1) and not result:
        raise RuntimeError("ruff format failed without a file list")
    return result


def shellcheck_files(files):
    """Execute shellcheck_files."""
    if not files:
        return []
    process = command(
        ["shellcheck", "--norc", "--enable=all", "--format=json", *files],
        allowed=(0, 1),
        timeout=180,
    )
    data = json.loads(process.stdout.strip() or "[]")
    return [
        finding("SC" + str(item["code"]), item["file"], item["line"], item["message"])
        for item in data
    ]


def workflow_script_findings(names, kind):
    """Execute workflow_script_findings."""
    result = []
    grouped = {"bash": [], "sh": [], "dash": [], "ksh": []}
    with tempfile.TemporaryDirectory(prefix="homelab-shellcheck-") as temp:
        labels = {}
        for name, spec, script in workflow_runs(names):
            dialect = shell_dialect(spec)
            if dialect == "python":
                if kind != "python":
                    continue
                try:
                    ast.parse(script)
                except SyntaxError as error:
                    result.append(
                        finding(
                            "python-syntax",
                            name,
                            error.lineno or 1,
                            "Inline workflow Python was rejected by the parser.",
                            script,
                        )
                    )
                continue
            if kind != "shell":
                continue
            if dialect is None:
                result.append(
                    finding(
                        "workflow-shell-unreviewed",
                        name,
                        1,
                        "Inline workflow script has no pinned parser: " + spec.split()[0],
                        spec + "\n" + script,
                    )
                )
                continue
            sanitized = GITHUB_EXPR.sub("GH_EXPR", script)
            path = Path(temp) / f"script-{len(labels)}.sh"
            path.write_text(sanitized)
            labels[str(path)] = name
            grouped[dialect].append(str(path))
        for dialect, paths in grouped.items():
            if not paths:
                continue
            process = command(
                [
                    "shellcheck",
                    "--norc",
                    "--enable=all",
                    "--shell",
                    dialect,
                    "--format=json",
                    *paths,
                ],
                allowed=(0, 1),
                timeout=180,
            )
            for item in json.loads(process.stdout.strip() or "[]"):
                source = labels.get(
                    str(Path(item["file"]).resolve()), labels.get(item["file"], item["file"])
                )
                result.append(
                    finding(
                        "SC" + str(item["code"]),
                        source,
                        1,
                        f"Inline workflow script line {item['line']}: {item['message']}",
                        source + "\n" + item["message"],
                    )
                )
    return result


def docker_targets(names: list[str]) -> list[str]:
    """Include conventional Dockerfile variants without executing build instructions."""
    result: list[str] = []
    for name in names:
        basename = Path(name).name.casefold()
        if (
            basename in ("dockerfile", "containerfile")
            or basename.startswith(("dockerfile.", "containerfile."))
            or basename.endswith((".dockerfile", ".containerfile"))
        ):
            result.append(name)
    return result


def check_python(names: list[str]) -> tuple[list[Finding], int]:
    """Run the python linter and return findings and target count."""
    files = [p for p in names if p.endswith(".py")]
    process = command(
        ["ruff", "check", "--config", "quality/ruff.toml", "--output-format", "json", *files],
        allowed=(0, 1, 2),
        timeout=300,
    )
    try:
        data = json.loads(process.stdout or "[]")
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, list):
        raise LintToolError("ruff failed")
    result = [
        finding(
            item.get("code") or "ruff-syntax",
            item["filename"],
            item["location"]["row"],
            item["message"],
        )
        for item in data
    ]
    result.extend(format_findings(files))
    result.extend(mypy_findings(files))
    result.extend(workflow_script_findings(names, "python"))
    return result, len(files)


def check_yaml(names: list[str]) -> tuple[list[Finding], int]:
    """Run the yaml linter and return findings and target count."""
    from yamllint import linter
    from yamllint.config import YamlLintConfig

    config = YamlLintConfig(file=str(ROOT / "quality/yamllint.yaml"))
    files = yaml_targets(names)
    result = [
        finding(
            "yaml-" + (item.rule or "syntax"),
            path,
            item.line,
            "YAML " + (item.rule or "syntax") + ": " + item.desc,
        )
        for path in files
        for item in linter.run((ROOT / path).read_text(), config, filepath=path)
    ]
    return result, len(files)


def check_shell(names: list[str]) -> tuple[list[Finding], int]:
    """Run the shell linter and return findings and target count."""
    files = shell_targets(names)
    result = shellcheck_files(files)
    result.extend(workflow_script_findings(names, "shell"))
    return result, len(files)


def check_actions(names: list[str]) -> tuple[list[Finding], int]:
    """Run the actions linter and return findings and target count."""
    files = workflow_files(names)
    return sarif(
        json.loads(
            command(
                [
                    "zizmor",
                    "--no-config",
                    "--strict-collection",
                    "--persona",
                    "auditor",
                    "--format",
                    "sarif",
                    *files,
                ],
                allowed=(0, 1),
                timeout=180,
            ).stdout
        ),
        ".github/workflows",
    ), len(files)


def python_directive_lines(source: str) -> set[int]:
    """Find noqa comment tokens in Python run steps, not YAML prose or shell data."""
    import yaml

    def fields(node: yaml.Node | None) -> dict[str, yaml.Node]:
        if not isinstance(node, yaml.MappingNode):
            return {}
        return {key.value: value for key, value in node.value if isinstance(key, yaml.ScalarNode)}

    def shell(node: yaml.Node | None, fallback: str) -> str:
        return node.value if isinstance(node, yaml.ScalarNode) else fallback

    def default_shell(mapping: dict[str, yaml.Node], fallback: str) -> str:
        run = fields(fields(mapping.get("defaults")).get("run"))
        return shell(run.get("shell"), fallback)

    document = fields(yaml.compose(source, Loader=yaml.SafeLoader))
    lines = set()
    for job in fields(document.get("jobs")).values():
        config = fields(job)
        steps = config.get("steps")
        if not isinstance(steps, yaml.SequenceNode):
            continue
        inherited = default_shell(config, default_shell(document, "bash"))
        for step in steps.value:
            values = fields(step)
            script = values.get("run")
            if (
                not isinstance(script, yaml.ScalarNode)
                or shell_dialect(shell(values.get("shell"), inherited)) != "python"
            ):
                continue
            for token in tokenize.generate_tokens(io.StringIO(script.value).readline):
                if token.type == tokenize.COMMENT and re.match(
                    r"#\s*noqa(?:\s*:|\s*$)", token.string, re.I
                ):
                    if script.style == "|":
                        offset = token.start[0]
                    else:
                        # Folding/quoting can remove physical newlines. If the
                        # comment has a unique verbatim spelling inside this scalar,
                        # report its source line. Escaped/ambiguous spellings can
                        # only be attributed reliably to the scalar as a whole.
                        raw = source[script.start_mark.index : script.end_mark.index]
                        comment = token.string.rstrip()
                        offset = (
                            raw[: raw.index(comment)].count("\n") if raw.count(comment) == 1 else 0
                        )
                    lines.add(script.start_mark.line + 1 + offset)
    return lines


def workflow_directives(name: str) -> list[Finding]:
    """Reject inline audit waivers without treating shell/YAML data as Python."""
    source = (ROOT / name).read_text()
    lines = python_directive_lines(source)
    for number, line in enumerate(source.splitlines(), 1):
        if re.search(r"#\s*(?:zizmor:\s*ignore|shellcheck\s+disable=)", line, re.I):
            lines.add(number)
    return [
        finding("workflow-suppression", name, number, "Workflow lint suppression is not allowed.")
        for number in sorted(lines)
    ]


def check_actionlint(names: list[str]) -> tuple[list[Finding], int]:
    """Run the actionlint linter and return findings and target count."""
    files = workflow_files(names)
    for helper in ("shellcheck", "pyflakes"):
        if shutil.which(helper) is None:
            raise LintToolError(f"Missing required actionlint helper: {helper}")
    process = command(
        ["actionlint", "-config-file", os.devnull, "-format", "{{json .}}", *files],
        allowed=(0, 1),
        timeout=180,
    )
    data = json.loads(process.stdout or "[]")
    result: list[Finding] = [
        finding(item["kind"], item["filepath"], item["line"], item["message"]) for item in data
    ]
    return result, len(files)


def check_ansible(names: list[str]) -> tuple[list[Finding], int]:
    """Run the ansible linter and return findings and target count."""
    os.environ["ANSIBLE_CONFIG"] = str(ROOT / "ansible/ansible.cfg")
    os.environ["ANSIBLE_COLLECTIONS_PATH"] = str(ROOT / ".quality-tools/collections")
    files = [p for p in names if p.startswith("ansible/") and p.endswith((".yml", ".yaml"))]
    data = json.loads(
        command(
            [
                "ansible-lint",
                "--offline",
                "--project-dir",
                str(ROOT),
                "--config-file",
                str(ROOT / "quality/ansible-lint.yaml"),
                "--format",
                "sarif",
                *[str(ROOT / p) for p in files],
            ],
            allowed=(0, 2),
            timeout=1800,
        ).stdout
    )
    return sarif(data), len(files)


def check_docker(names: list[str]) -> tuple[list[Finding], int]:
    """Run the docker linter and return findings and target count."""
    files = docker_targets(names)
    result: list[Finding] = []
    for path in files:
        data = json.loads(
            command(
                ["hadolint", "--config", "quality/hadolint.yaml", "--format", "json", path],
                allowed=(0, 1),
            ).stdout
        )
        result.extend(
            finding(item["code"], path, item["line"], item["message"])
            for item in data
            if not nonsecret_tokenizer_option(path, item)
        )
    return result, len(files)


def check_javascript(names: list[str]) -> tuple[list[Finding], int]:
    """Run the javascript linter and return findings and target count."""
    files = [p for p in names if p.endswith(".js")]
    result = []
    for path in files:
        process = command(["node", "--check", path], allowed=(0, 1))
        if process.returncode:
            from common import digest

            result.append(
                finding(
                    "javascript-syntax",
                    path,
                    1,
                    "JavaScript parser rejected this source; code was not executed.",
                    digest((ROOT / path).read_text()),
                )
            )
    return result, len(files)


def check_secrets(_names: list[str]) -> tuple[list[Finding], int]:
    """Run the secrets linter and return findings and target count."""
    with tempfile.TemporaryDirectory(prefix="homelab-secret-scan-") as temp:
        stage = Path(temp) / "source"
        tracked_names = tracked()
        for name in tracked_names:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        out = Path(temp) / "redacted.json"
        command(
            [
                "gitleaks",
                "dir",
                str(stage),
                "--redact=100",
                "--no-banner",
                "--report-format",
                "json",
                "--report-path",
                str(out),
            ],
            allowed=(0, 1),
            timeout=240,
        )
        data = json.loads(out.read_text())
        result = []
        for item in data:
            path = (
                Path(item["File"]).relative_to(stage)
                if Path(item["File"]).is_absolute()
                else Path(item["File"])
            )
            result.append(
                finding(
                    item["RuleID"],
                    path,
                    item["StartLine"],
                    "Potential secret: inspect privately; do not paste its value into reports.",
                )
            )
        return result, len(tracked_names)


def check(tool: str) -> tuple[list[Finding], int]:
    """Execute check."""
    use_project_tools()
    names = owned(tracked())
    if tool == "workflow":
        security, count = check("actions")
        expressions, _ = check("actionlint")
        directives = [item for name in workflow_files(names) for item in workflow_directives(name)]
        return security + expressions + directives, count
    if tool == "dependencies":
        return check_dependencies(names)
    tools = {
        "python": check_python,
        "yaml": check_yaml,
        "shell": check_shell,
        "actions": check_actions,
        "actionlint": check_actionlint,
        "ansible": check_ansible,
        "docker": check_docker,
        "javascript": check_javascript,
        "secrets": check_secrets,
    }
    checker = tools.get(tool)
    if checker is None:
        raise ValueError("Unknown linter")
    return checker(names)


def main():
    """Execute main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tool",
        choices=[
            "workflow",
            "python",
            "yaml",
            "shell",
            "actions",
            "actionlint",
            "ansible",
            "docker",
            "secrets",
            "javascript",
            "dependencies",
        ],
    )
    args = parser.parse_args()
    output = ROOT / f"reports/{args.tool}.json"
    try:
        findings, count = check(args.tool)
        return report(args.tool, findings, count, output)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        failure(output, error)
        print(
            f"{args.tool}: {type(error).__name__}; tool failure, NOT an accepted lint result",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
