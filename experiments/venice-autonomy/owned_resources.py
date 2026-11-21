"""Helpers to find and clean up resources owned by benchmark attempts."""
import json
import pathlib
import subprocess


def _result_text(result) -> str:
    return f"{result.stderr or ''}\n{result.stdout or ''}"


def _daemon_or_auth(text) -> bool:
    lowered = text.lower()
    markers = (
        "cannot connect",
        "permission denied",
        "unauthorized",
        "authentication required",
        "error during connect",
    )
    return any(marker in lowered for marker in markers)


def _already_gone(result) -> bool:
    if result.returncode == 0:
        return False
    text = _result_text(result)
    if _daemon_or_auth(text):
        return False
    lowered = text.lower()
    return "no such" in lowered or "not found" in lowered


def _run(args, timeout) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def remove_container(container_id, expected):
    if not container_id or any(part in container_id for part in ("/", "..", " ")):
        message = "refusing to clean an unsafe container id"
        raise ValueError(message)
    inspection = _run(["docker", "inspect", container_id], 15)
    if inspection.returncode != 0:
        if _already_gone(inspection):
            return
        detail = _result_text(inspection).strip() or "inspect failed"
        message = "refusing to clean a container that cannot be inspected: " + detail
        raise ValueError(message)
    info = json.loads(inspection.stdout)[0]
    labels = (info.get("Config") or {}).get("Labels") or {}
    name = str(info.get("Name") or "")
    if (
        labels.get("venice-autonomy-lab") != "true"
        or labels.get("venice-autonomy-run") != expected
        or not name.startswith("/venice-lab-")
    ):
        message = "refusing to clean a container without this run ownership"
        raise ValueError(message)
    removal = _run(["docker", "rm", "-f", container_id], 25)
    if removal.returncode != 0 and not _already_gone(removal):
        detail = _result_text(removal).strip() or "rm failed"
        message = "container removal failed: " + detail
        raise ValueError(message)


def remove_volume(volume, expected):
    if not volume.startswith("venice-lab-") or any(part in volume for part in ("/", " ")):
        message = "refusing to clean an unrelated volume"
        raise ValueError(message)
    inspection = _run(["docker", "volume", "inspect", volume], 15)
    if inspection.returncode != 0:
        if _already_gone(inspection):
            return
        detail = _result_text(inspection).strip() or "inspect failed"
        message = "refusing to clean a volume that cannot be inspected: " + detail
        raise ValueError(message)
    info = json.loads(inspection.stdout)[0]
    labels = info.get("Labels") or {}
    if labels.get("venice-autonomy-lab") != "true" or labels.get("venice-autonomy-run") != expected:
        message = "refusing to clean a volume without this run ownership"
        raise ValueError(message)
    removal = _run(["docker", "volume", "rm", volume], 20)
    if removal.returncode != 0 and not _already_gone(removal):
        detail = _result_text(removal).strip() or "rm failed"
        message = "volume removal failed: " + detail
        raise ValueError(message)


def cleanup_role(root):
    root = pathlib.Path(root)
    expected = str(root.resolve())
    errors = []
    container_file = root / "container-id"
    if container_file.is_file() and not container_file.is_symlink():
        try:
            remove_container(container_file.read_text().strip(), expected)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(str(error))
    volume_file = root / "volume-name"
    if volume_file.is_file() and not volume_file.is_symlink():
        try:
            remove_volume(volume_file.read_text().strip(), expected)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(str(error))
    if errors:
        raise ValueError("; ".join(errors))
