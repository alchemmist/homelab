#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import selectors
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

SOURCE_COMMIT = "d2b324b30a0c11fe7599368bc11269b53dd34484"
GRADER_COMMIT = "85437b7ab921b8f2a099bed6e648ccec9ab2d35e"
WHITELIST = ("main.py", "agent_protocol.py")
GRADER_SOURCE = "tests/test_protocol_recovery.py"
GRADER_NAME = "test_protocol_recovery.py"
ALLOWED_METHODS = ("_answer", "_generate_on_page")
SELECTED_TESTS = (
    "test_protocol_recovery.RecoveryTests.test_source_failure_is_typed_but_literal_marker_is_valid_text",
    "test_protocol_recovery.RecoveryTests.test_pending_source_is_not_a_fatal_extraction_failure",
)
LABEL = "historical_regression_exercise"
CLAIM = "not_fresh_bug_discovery"
PILOT_LABEL = "venice-autonomy.owner=protocol-regression"
BASE_IMAGE = "python:3.12-slim"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_repo(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    raw = os.environ.get("PROTOCOL_REGRESSION_REPO")
    if not raw:
        raise ValueError("pass --repo or set PROTOCOL_REGRESSION_REPO")
    return Path(raw)


def resolve_python(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    raw = os.environ.get("PROTOCOL_REGRESSION_PYTHON")
    if raw:
        return Path(raw)
    return Path(sys.executable)


def git_show(repo: Path, rev_path: str) -> bytes:
    if rev_path.startswith("-") or ".." in rev_path.split(":", 1)[-1]:
        raise ValueError(f"refused path {rev_path}")
    completed = subprocess.run(
        ["git", "-C", str(repo), "show", "--no-textconv", rev_path],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def git_blob(repo: Path, rev_path: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", rev_path],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def method_spans(source: str) -> dict[str, tuple[int, int]]:
    tree = ast.parse(source)
    spans: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "BrowserSession":
            continue
        for child in node.body:
            if isinstance(child, ast.AsyncFunctionDef) and child.name in ALLOWED_METHODS:
                if child.name in spans:
                    raise ValueError("duplicate allowed method")
                spans[child.name] = (child.lineno, child.end_lineno or child.lineno)
    if tuple(sorted(spans)) != tuple(sorted(ALLOWED_METHODS)):
        raise ValueError("snapshot is missing BrowserSession._answer or _generate_on_page")
    return spans


def mask_allowed_methods(source: str) -> str:
    spans = method_spans(source)
    lines = source.splitlines(keepends=True)
    pieces: list[str] = []
    index = 1
    while index <= len(lines):
        matched = None
        for name, (start, end) in spans.items():
            if start == index:
                matched = (name, end)
                break
        if matched is None:
            pieces.append(lines[index - 1])
            index += 1
            continue
        name, end = matched
        pieces.append(f"# <allowed BrowserSession.{name}>\n")
        index = end + 1
    return "".join(pieces)


def allowed_edit_report(baseline: str, candidate: str) -> dict:
    try:

        def signatures(source):
            tree = ast.parse(source)
            return {
                child.name: (
                    ast.dump(child.args, include_attributes=False),
                    ast.dump(child.returns, include_attributes=False) if child.returns else None,
                    tuple(
                        ast.dump(item, include_attributes=False)
                        for item in getattr(child, "type_params", [])
                    ),
                    child.type_comment,
                )
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == "BrowserSession"
                for child in node.body
                if isinstance(child, ast.AsyncFunctionDef) and child.name in ALLOWED_METHODS
            }

        unchanged_signatures = signatures(baseline) == signatures(candidate)
        same_outside = (
            mask_allowed_methods(baseline) == mask_allowed_methods(candidate)
            and unchanged_signatures
        )
        if not unchanged_signatures:
            expected = [
                "async def "
                + child.name
                + "("
                + ast.unparse(child.args)
                + ")"
                + (" -> " + ast.unparse(child.returns) if child.returns else "")
                for node in ast.parse(baseline).body
                if isinstance(node, ast.ClassDef) and node.name == "BrowserSession"
                for child in node.body
                if isinstance(child, ast.AsyncFunctionDef) and child.name in ALLOWED_METHODS
            ]
            return {
                "allowed": False,
                "detail": "candidate changes a method signature; edit only method bodies",
                "expected_signatures": expected,
            }
        detail = (
            "outside the two allowed methods matches the historical baseline"
            if same_outside
            else "candidate changes main.py outside BrowserSession._answer and BrowserSession._generate_on_page"
        )
        return {"allowed": same_outside, "detail": detail}
    except (SyntaxError, ValueError) as exc:
        return {"allowed": False, "detail": str(exc)}


def file_record(relative: str, data: bytes, git_blob_id: str) -> dict:
    return {
        "path": relative,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "git_blob": git_blob_id,
    }


def export_snapshot(repo: Path, dest: Path) -> dict:
    if dest.exists():
        raise FileExistsError(dest)
    agent = dest / "agent"
    grader = dest / "grader"
    agent.mkdir(parents=True)
    grader.mkdir(parents=True)
    records = []
    for name in WHITELIST:
        spec = f"{SOURCE_COMMIT}:{name}"
        data = git_show(repo, spec)
        write_bytes(agent / name, data)
        records.append(file_record(f"agent/{name}", data, git_blob(repo, spec)))
    grader_spec = f"{GRADER_COMMIT}:{GRADER_SOURCE}"
    grader_bytes = git_show(repo, grader_spec)
    write_bytes(grader / GRADER_NAME, grader_bytes)
    records.append(file_record(f"grader/{GRADER_NAME}", grader_bytes, git_blob(repo, grader_spec)))
    baseline = (agent / "main.py").read_text(encoding="utf-8")
    method_spans(baseline)
    manifest = {
        "label": LABEL,
        "claim": CLAIM,
        "source_commit": SOURCE_COMMIT,
        "grader_commit": GRADER_COMMIT,
        "whitelist": list(WHITELIST),
        "allowed_edits": [
            "main.py:BrowserSession._answer",
            "main.py:BrowserSession._generate_on_page",
        ],
        "selected_tests": list(SELECTED_TESTS),
        "grader_kept_out_of_agent_snapshot": True,
        "files": records,
    }
    encoded = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    write_bytes(dest / "manifest.json", encoded)
    manifest["manifest_sha256"] = sha256_bytes(encoded)
    return manifest


def load_manifest(snapshot: Path) -> dict:
    return json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))


def verify_snapshot(snapshot: Path) -> dict:
    manifest = load_manifest(snapshot)
    problems = []
    if manifest.get("label") != LABEL or manifest.get("claim") != CLAIM:
        problems.append("manifest is not labeled as a historical exercise")
    agent = snapshot / "agent"
    if (agent / GRADER_NAME).exists() or (agent / "tests").exists():
        problems.append("grader is inside the agent snapshot")
    if any(
        path.name == ".git" or ".git" in path.parts for path in snapshot.rglob("*") if path.exists()
    ):
        problems.append("snapshot contains .git")
    expected = {item["path"]: item for item in manifest["files"]}
    present = []
    for path in sorted(snapshot.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            present.append(str(path.relative_to(snapshot)))
    if set(present) != set(expected):
        problems.append(f"snapshot files {present} differ from manifest")
    for relative, item in expected.items():
        data = (snapshot / relative).read_bytes()
        if sha256_bytes(data) != item["sha256"] or len(data) != item["bytes"]:
            problems.append(f"hash mismatch for {relative}")
    if problems:
        raise ValueError("; ".join(problems))
    return manifest


def clean_env(agent: Path, home: Path, rejection: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(agent),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "HOME": str(home),
        "AGENT_REJECTION_DIR": str(rejection),
        "LC_ALL": "C",
        "LANG": "C",
    }


def bounded_test_process(args, cwd=None, env=None, timeout=120, limit=131072):
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    for name in output:
        selector.register(getattr(process, name), selectors.EVENT_READ, name)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("test process deadline exceeded")
            for key, _ in selector.select(min(remaining, 1)):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(data)
                if len(output[key.data]) > limit:
                    raise ValueError("test process output limit exceeded")
        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        return subprocess.CompletedProcess(
            args,
            code,
            output["stdout"].decode("utf-8", errors="replace"),
            output["stderr"].decode("utf-8", errors="replace"),
        )
    finally:
        selector.close()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def test_completed(exit_code, stderr):
    return (
        exit_code == 0
        and re.search(r"(?m)^Ran 1 test in [0-9.]+s$", stderr) is not None
        and stderr.strip().endswith("\nOK")
    )


def run_selected_tests(python: Path, agent: Path, grader: Path) -> dict:
    agent = agent.resolve()
    grader = grader.resolve()
    results = []
    with tempfile.TemporaryDirectory(prefix="protocol-regression-") as temp:
        root = Path(temp)
        env = clean_env(agent, root / "home", root / "rejections")
        (root / "home").mkdir()
        (root / "rejections").mkdir()
        for test in SELECTED_TESTS:
            completed = bounded_test_process(
                [str(python.absolute()), "-m", "unittest", test],
                cwd=grader,
                env=env,
                timeout=120,
            )
            tail = "\n".join((completed.stderr or "").strip().splitlines()[-40:])
            results.append(
                {
                    "test": test,
                    "exit_code": completed.returncode,
                    "stderr_tail": tail,
                    "completed": test_completed(completed.returncode, completed.stderr),
                }
            )
    return {
        "passed": all(item["exit_code"] == 0 and item["completed"] for item in results),
        "tests": results,
    }


def materialize_known_fixed(repo: Path, snapshot: Path, dest: Path) -> Path:
    dest.mkdir(parents=True)
    fixed = git_show(repo, f"{GRADER_COMMIT}:main.py")
    write_bytes(dest / "main.py", fixed)
    shutil.copyfile(snapshot / "agent" / "agent_protocol.py", dest / "agent_protocol.py")
    return dest


def grade_candidate(python: Path, snapshot: Path, candidate: Path) -> dict:
    verify_snapshot(snapshot)
    baseline = (snapshot / "agent" / "main.py").read_text(encoding="utf-8")
    candidate_main = (candidate / "main.py").read_text(encoding="utf-8")
    protocol_same = (candidate / "agent_protocol.py").read_bytes() == (
        snapshot / "agent" / "agent_protocol.py"
    ).read_bytes()
    edit = allowed_edit_report(baseline, candidate_main)
    report = {
        "allowed_edits": edit,
        "agent_protocol_unchanged": protocol_same,
        "graded": False,
    }
    if not protocol_same:
        report["detail"] = "agent_protocol.py is outside the allowed edit set"
        report["passed"] = False
        return report
    if not edit["allowed"]:
        report["detail"] = edit["detail"]
        report["passed"] = False
        return report
    graded = run_selected_tests(python, candidate, snapshot / "grader")
    report["graded"] = True
    report["grade"] = graded
    report["passed"] = graded["passed"]
    return report


def docker_env() -> dict[str, str]:
    kept = {}
    for key in (
        "PATH",
        "HOME",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "XDG_RUNTIME_DIR",
        "TMPDIR",
        "USER",
    ):
        if key in os.environ:
            kept[key] = os.environ[key]
    return kept


def docker_run(
    docker: str,
    args: list[str],
    check: bool = True,
    text: bool = True,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [docker, *args],
        check=check,
        capture_output=True,
        text=text,
        input=None if input_bytes is None else input_bytes,
        env=docker_env(),
        timeout=300,
    )


def pinned_base_digest(dockerfile: Path) -> str:
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        if line.startswith("FROM "):
            image = line.split()[1]
            marker = "@sha256:"
            if marker not in image or not image.startswith(BASE_IMAGE + marker):
                raise ValueError(f"worker base is not a pinned {BASE_IMAGE} digest")
            return image.split("@", 1)[1]
    raise ValueError("worker Dockerfile has no FROM")


def verify_pinned_base(docker: str, dockerfile: Path) -> dict:
    pinned = pinned_base_digest(dockerfile)
    completed = docker_run(docker, ["manifest", "inspect", BASE_IMAGE], check=False, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"docker manifest inspect {BASE_IMAGE} failed: {detail}")
    document = json.loads(completed.stdout)
    matches = []
    for item in document.get("manifests", []):
        digest = item.get("digest")
        if digest == pinned:
            matches.append(item.get("platform"))
    if not matches:
        raise RuntimeError(
            f"pinned digest {pinned} is absent from registry manifest for {BASE_IMAGE}"
        )
    return {
        "base_image": BASE_IMAGE,
        "pinned_digest": pinned,
        "registry_platforms": matches,
        "manifest_media_type": document.get("mediaType"),
    }


def tar_bytes(files: list[tuple[str, bytes]]) -> bytes:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    return payload.getvalue()


def copy_into(docker: str, container: str, dest: str, files: list[tuple[str, bytes]]) -> None:
    completed = subprocess.run(
        [docker, "cp", "-", f"{container}:{dest}"],
        input=tar_bytes(files),
        capture_output=True,
        env=docker_env(),
        timeout=60,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"docker cp into {dest} failed: {detail}")


def container_limits() -> list[str]:
    return [
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--cpus",
        "1",
        "--memory",
        "512m",
        "--pids-limit",
        "128",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=128m",
        "--user",
        "nobody",
        "--label",
        PILOT_LABEL,
    ]


def remove_own_container(docker: str, name: str) -> None:
    if not name.startswith("protocol-regression-"):
        raise ValueError(name)
    subprocess.run(
        [docker, "rm", "-f", name],
        capture_output=True,
        env=docker_env(),
        timeout=60,
    )


def run_container(
    docker: str,
    image: str,
    command: list[str],
    copies: list[tuple[str, list[tuple[str, bytes]]]],
    workdir: str,
) -> dict:
    name = f"protocol-regression-{uuid.uuid4().hex[:12]}"
    create = docker_run(
        docker,
        [
            "create",
            "--name",
            name,
            "--workdir",
            workdir,
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONNOUSERSITE=1",
            "--env",
            "PYTHONPATH=/opt/agent",
            "--env",
            "HOME=/tmp",
            "--env",
            "LC_ALL=C",
            "--env",
            "LANG=C",
            *container_limits(),
            image,
            *command,
        ],
        check=False,
    )
    if create.returncode != 0:
        detail = (create.stderr or create.stdout or "").strip()
        raise RuntimeError(f"docker create failed: {detail}")
    try:
        for dest, files in copies:
            copy_into(docker, name, dest, files)
        started = bounded_test_process(
            [docker, "start", "-a", name],
            env=docker_env(),
            timeout=180,
        )
        inspect = docker_run(
            docker, ["inspect", "--format", "{{.State.ExitCode}}", name], check=False
        )
        exit_code = started.returncode
        if started.returncode == 0 and inspect.returncode == 0 and inspect.stdout.strip().isdigit():
            exit_code = int(inspect.stdout.strip())
        tail = "\n".join((started.stderr or started.stdout or "").strip().splitlines()[-40:])
        return {
            "exit_code": exit_code,
            "stderr_tail": tail,
            "container": name,
            "completed": test_completed(exit_code, started.stderr),
        }
    finally:
        remove_own_container(docker, name)


def candidate_files(candidate: Path) -> list[tuple[str, bytes]]:
    files = []
    for name in WHITELIST:
        path = candidate / name
        if not path.is_file():
            raise ValueError(f"candidate is missing {name}")
        files.append((name, path.read_bytes()))
    return files


def grader_files(snapshot: Path) -> list[tuple[str, bytes]]:
    path = snapshot / "grader" / GRADER_NAME
    return [(GRADER_NAME, path.read_bytes())]


def run_selected_tests_container(docker: str, image: str, candidate: Path, snapshot: Path) -> dict:
    results = []
    copies = [
        ("/opt/agent", candidate_files(candidate)),
        ("/opt/grader", grader_files(snapshot)),
    ]
    for test in SELECTED_TESTS:
        result = run_container(
            docker,
            image,
            ["python", "-m", "unittest", test],
            copies,
            "/opt/grader",
        )
        results.append(
            {
                "test": test,
                "exit_code": result["exit_code"],
                "stderr_tail": result["stderr_tail"],
                "completed": result["completed"],
            }
        )
    return {
        "passed": all(item["exit_code"] == 0 and item["completed"] for item in results),
        "tests": results,
    }


def grade_candidate_container(docker: str, image: str, snapshot: Path, candidate: Path) -> dict:
    verify_snapshot(snapshot)
    baseline = (snapshot / "agent" / "main.py").read_text(encoding="utf-8")
    candidate_main = (candidate / "main.py").read_text(encoding="utf-8")
    protocol_same = (candidate / "agent_protocol.py").read_bytes() == (
        snapshot / "agent" / "agent_protocol.py"
    ).read_bytes()
    edit = allowed_edit_report(baseline, candidate_main)
    report = {
        "allowed_edits": edit,
        "agent_protocol_unchanged": protocol_same,
        "graded": False,
        "runtime": "container",
    }
    if not protocol_same:
        report["detail"] = "agent_protocol.py is outside the allowed edit set"
        report["passed"] = False
        return report
    if not edit["allowed"]:
        report["detail"] = edit["detail"]
        report["passed"] = False
        return report
    graded = run_selected_tests_container(docker, image, candidate, snapshot)
    report["graded"] = True
    report["grade"] = graded
    report["passed"] = graded["passed"]
    return report


def image_facts(docker: str, image: str) -> dict:
    inspect = docker_run(docker, ["image", "inspect", image], check=True)
    document = json.loads(inspect.stdout)[0]
    probe = (
        "import importlib.metadata as m, os, sys\n"
        "names=['fastapi','jsonschema','playwright','uvicorn','pydantic','starlette','anyio']\n"
        "print(sys.version.split()[0])\n"
        "print({name: m.version(name) for name in names})\n"
        "print(os.path.exists('/opt/agent/main.py'))\n"
        "print(os.path.exists('/usr/local/bin/pip'))\n"
        "print(os.path.exists('/opt/grader/test_protocol_recovery.py'))\n"
    )
    ran = docker_run(
        docker,
        ["run", "--rm", *container_limits(), image, "python", "-c", probe],
        check=False,
    )
    if ran.returncode != 0:
        detail = (ran.stderr or ran.stdout or "").strip()
        raise RuntimeError(f"image probe failed: {detail}")
    version, imports, baked_main, pip_present, baked_grader = ran.stdout.splitlines()
    if baked_main != "False" or baked_grader != "False" or pip_present != "False":
        raise RuntimeError("image contains a solution, grader, or pip")
    return {
        "image_id": document["Id"],
        "created": document.get("Created"),
        "size": document.get("Size"),
        "user": document.get("Config", {}).get("User"),
        "python_version": version,
        "imports": ast.literal_eval(imports),
        "solution_baked": False,
        "pip_present": False,
    }


def collect_evidence(repo: Path, snapshot: Path, docker: str, image: str, dockerfile: Path) -> dict:
    manifest = verify_snapshot(snapshot)
    base = verify_pinned_base(docker, dockerfile)
    facts = image_facts(docker, image)
    baseline = grade_candidate_container(docker, image, snapshot, snapshot / "agent")
    with tempfile.TemporaryDirectory(prefix="protocol-fixed-") as temp:
        fixed = materialize_known_fixed(repo, snapshot, Path(temp) / "candidate")
        known_fixed = grade_candidate_container(docker, image, snapshot, fixed)
    return {
        "label": LABEL,
        "claim": CLAIM,
        "source_commit": SOURCE_COMMIT,
        "grader_commit": GRADER_COMMIT,
        "manifest_sha256": sha256_bytes((snapshot / "manifest.json").read_bytes()),
        "manifest_file_count": len(manifest["files"]),
        "base_image": base,
        "worker_image": facts,
        "baseline_must_fail": baseline,
        "known_fixed_must_pass": known_fixed,
        "historical_gate_holds": (not baseline["passed"]) and bool(known_fixed["passed"]),
        "runtime": {
            "network": "none",
            "read_only_root": True,
            "cap_drop": "ALL",
            "no_new_privileges": True,
            "cpus": "1",
            "memory": "512m",
            "pids_limit": 128,
            "copy": "docker cp stdin tar",
            "separate_agent_and_grader": True,
            "runtime_installs": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Historical protocol regression pilot")
    parser.add_argument("command", choices=("export", "verify", "grade", "evidence"))
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--python", type=Path, default=None)
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--image", default=None)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--dockerfile", type=Path, default=None)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args(argv)
    repo = None
    if args.command in ("export", "evidence") or args.repo is not None:
        repo = resolve_repo(args.repo)
    python = resolve_python(args.python)
    if args.command == "export":
        if args.dest is None:
            parser.error("export requires --dest")
        manifest = export_snapshot(repo, args.dest)
        print(json.dumps({"manifest_sha256": manifest["manifest_sha256"]}, sort_keys=True))
        return 0
    if args.snapshot is None:
        parser.error(f"{args.command} requires --snapshot")
    if args.command == "verify":
        manifest = verify_snapshot(args.snapshot)
        print(
            json.dumps(
                {"files": len(manifest["files"]), "label": manifest["label"]}, sort_keys=True
            )
        )
        return 0
    if args.command == "grade":
        if args.candidate is None:
            parser.error("grade requires --candidate")
        if args.container:
            if not args.image:
                parser.error("container grade requires --image")
            report = grade_candidate_container(
                args.docker, args.image, args.snapshot, args.candidate
            )
        else:
            report = grade_candidate(python, args.snapshot, args.candidate)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["passed"] else 1
    if not args.image:
        parser.error("evidence requires --image")
    dockerfile = args.dockerfile or Path(__file__).with_name("worker.Dockerfile")
    evidence = collect_evidence(repo, args.snapshot, args.docker, args.image, dockerfile)
    encoded = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.evidence is not None:
        write_bytes(args.evidence, encoded.encode("utf-8"))
    print(encoded, end="")
    return 0 if evidence["historical_gate_holds"] else 1


if __name__ == "__main__":
    sys.exit(main())
