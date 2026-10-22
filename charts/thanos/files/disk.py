import os
import time

PROMETHEUS_MARKER = "prometheus-kube-prometheus-stack-prometheus-db"
ROLES = (
    ("raw", "socrat-thanos"),
    ("work", "socrat-thanos-work"),
    ("shelf", "socrat-thanos-5m"),
    ("shelf", "socrat-thanos-1h"),
)


def allocated(path):
    stat = os.lstat(path)
    blocks = getattr(stat, "st_blocks", None)
    if blocks is None:
        return stat.st_size
    return blocks * 512


def directory_bytes(path):
    total = allocated(path)
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs:
            total += allocated(os.path.join(root, name))
        for name in files:
            total += allocated(os.path.join(root, name))
    return total


def host_path(path, host_root):
    prefix = host_root.rstrip("/")
    if path == prefix or path.startswith(prefix + "/"):
        return "/var/lib" + path[len(prefix):]
    return path


def rows(host_root):
    found = []
    storage = os.path.join(host_root, "rancher/k3s/storage")
    if os.path.isdir(storage):
        for name in sorted(os.listdir(storage)):
            if PROMETHEUS_MARKER not in name:
                continue
            path = os.path.join(storage, name)
            if os.path.isdir(path):
                found.append(("prometheus", "/var/lib/prometheus", directory_bytes(path)))
    for role, dirname in ROLES:
        path = os.path.join(host_root, dirname)
        if os.path.isdir(path):
            found.append((role, host_path(path, host_root), directory_bytes(path)))
    return found


def render(node, entries):
    lines = [
        "# HELP socrat_metrics_directory_bytes Allocated bytes in one metrics cascade directory.",
        "# TYPE socrat_metrics_directory_bytes gauge",
    ]
    for role, path, size in entries:
        lines.append(
            'socrat_metrics_directory_bytes{node="%s",role="%s",path="%s"} %d' % (node, role, path, size)
        )
    return "\n".join(lines) + "\n"


def write(path, body):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(temporary, path)


def main():
    node = os.environ["NODE_NAME"]
    host_root = os.environ.get("HOST_VAR_LIB", "/host/var/lib")
    output = os.environ.get("OUTPUT", "/textfile/socrat-metrics-disk.prom")
    interval = int(os.environ.get("INTERVAL_SECONDS", "30"))
    while True:
        write(output, render(node, rows(host_root)))
        time.sleep(interval)


if __name__ == "__main__":
    main()

