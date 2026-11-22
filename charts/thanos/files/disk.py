"""Report Prometheus data disk allocation per Thanos block directory."""
import os
import time
from typing import cast

PROMETHEUS_MARKER = "prometheus-kube-prometheus-stack-prometheus-db"
ROLES = (
    ("raw", "socrat-thanos"),
    ("work", "socrat-thanos-work"),
    ("shelf", "socrat-thanos-5m"),
    ("shelf", "socrat-thanos-1h"),
)


def allocated(path) -> int:
    """Read allocated bytes without following symlinks, falling back to logical size if needed."""
    stat = os.lstat(path)
    blocks = getattr(stat, "st_blocks", None)
    if blocks is None:
        return stat.st_size
    return cast("int", blocks * 512)


def directory_bytes(path) -> int:
    """Sum allocation for the root and its entries without descending into linked directories."""
    total = allocated(path)
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs:
            total += allocated(os.path.join(root, name))
        for name in files:
            total += allocated(os.path.join(root, name))
    return total


def host_path(path, host_root) -> str:
    """Translate a path under the mounted host root to its /var/lib metric label."""
    prefix = host_root.rstrip("/")
    if path == prefix or path.startswith(prefix + "/"):
        return cast("str", "/var/lib" + path[len(prefix) :])
    return cast("str", path)


def rows(host_root) -> "list[tuple[str, str, int]]":
    """Measure configured trees, distinguishing retained raw data from the active workshop."""
    found = []
    storage = os.path.join(host_root, "rancher/k3s/storage")
    if os.path.isdir(storage):
        for name in sorted(os.listdir(storage)):
            if os.environ.get("WARM_WORKSHOP") == "1" and name.endswith("_cattle-monitoring-system_thanos-warm-s1-candidate"):
                warm = os.path.join(storage, name, "workshop-s3")
                if os.path.isdir(warm):
                    found.append(("warm", host_path(warm, host_root), directory_bytes(warm)))
                continue
            if PROMETHEUS_MARKER not in name:
                continue
            path = os.path.join(storage, name)
            if os.path.isdir(path):
                found.append(("prometheus", "/var/lib/prometheus", directory_bytes(path)))
    for role, dirname in ROLES:
        if role == "raw" and os.environ.get("WARM_WORKSHOP") == "1":
            role = "retained"
        if dirname == "socrat-thanos-5m" and os.environ.get("SKIP_OLD_FIVE") == "1":
            continue
        path = os.path.join(host_root, dirname)
        if os.path.isdir(path):
            found.append((role, host_path(path, host_root), directory_bytes(path)))
    return found


def render(node, entries) -> str:
    """Format one Prometheus gauge series per node, role and directory."""
    lines = [
        "# HELP socrat_metrics_directory_bytes Allocated bytes in one metrics cascade directory.",
        "# TYPE socrat_metrics_directory_bytes gauge",
    ]
    for role, path, size in entries:
        lines.append(
            'socrat_metrics_directory_bytes{node="%s",role="%s",path="%s"} %d'
            % (node, role, path, size)
        )
    return "\n".join(lines) + "\n"


def write(path, body) -> None:
    """Replace the textfile only after writing the complete sample beside it."""
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(temporary, path)


def main() -> None:
    """Keep the last complete sample if a compactor renames a file during the periodic walk."""
    node = os.environ["NODE_NAME"]
    host_root = os.environ.get("HOST_VAR_LIB", "/host/var/lib")
    output = os.environ.get("OUTPUT", "/textfile/socrat-metrics-disk.prom")
    interval = int(os.environ.get("INTERVAL_SECONDS", "30"))
    while True:
        try:
            write(output, render(node, rows(host_root)))
        except FileNotFoundError:
            # A compactor renamed a file while walking. Keep the last complete sample.
            pass
        time.sleep(interval)


if __name__ == "__main__":
    main()
