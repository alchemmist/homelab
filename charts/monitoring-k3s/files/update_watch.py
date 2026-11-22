#!/usr/bin/env python3
"""Compare pinned application versions with the newest stable GitHub release."""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TypedDict, override

type Version = tuple[int, int, int]
type Target = Mapping[str, str]
type Images = Mapping[str, str | None]


class Release(TypedDict, total=False):
    """Fields used to rank GitHub releases and versioned image tags."""

    draft: bool
    prerelease: bool
    tag_name: str


class Sample(TypedDict):
    """Labels and gauges for one update-watch target."""

    app: str
    title: str
    current: str
    latest: str
    available: int
    success: int


VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
UNSTABLE_RE = re.compile(r"(rc|alpha|beta|preview|dev|snapshot)", re.IGNORECASE)


def parse_version(text: str | None) -> Version | None:
    match = VERSION_RE.search(text or "")
    if not match:
        return None
    return int(match[1]), int(match[2]), int(match[3])


def format_version(version: Version) -> str:
    return ".".join(str(part) for part in version)


def latest_stable(releases: Iterable[Release]) -> tuple[Version | None, str | None]:
    best = None
    best_tag = None
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name") or ""
        if UNSTABLE_RE.search(tag):
            continue
        version = parse_version(tag)
        if version is None:
            continue
        if best is None or version > best:
            best = version
            best_tag = tag
    return best, best_tag


def escape_label(value: object) -> str:
    return str(value).replace("\\", r"\\").replace("\n", r"\n").replace('"', r"\"")


def fetch_releases(repo: str, timeout: int) -> list[Release]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=30",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "socrat-update-watch",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        message = f"unexpected GitHub response for {repo}"
        raise ValueError(message)
    return payload


def searxng_image_tags(timeout: int) -> list[Release]:
    # Upstream publishes rolling date-SHA images, not GitHub Releases.
    url = "https://hub.docker.com/v2/repositories/searxng/searxng/tags?page_size=100&ordering=last_updated"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        msg = "unexpected Docker Hub response"
        raise ValueError(msg)
    return [
        {"tag_name": item["name"]}
        for item in payload["results"]
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}-[0-9a-f]{7,40}", item["name"])
    ]


def version_from_image(image: str | None) -> Version | None:
    """Version embedded in a tag. Digest-only references have no tag."""
    if not image:
        return None
    ref = image.split("@", 1)[0]
    slash = ref.rfind("/")
    colon = ref.rfind(":")
    if colon <= slash:
        return None
    return parse_version(ref[colon + 1 :])


def installed_version(target: Target, images: Images | None) -> Version | None:
    image = None if images is None else images.get(target["id"])
    live = version_from_image(image)
    if live is not None:
        return live
    return parse_version(str(target.get("current", "")))


def evaluate(
    targets: Iterable[Target],
    fetch: Callable[[str, int], Iterable[Release]],
    timeout: int,
    images: Images | None = None,
) -> list[Sample]:
    samples = []
    for target in targets:
        app = target["id"]
        current = installed_version(target, images)
        sample: Sample = {
            "app": app,
            "title": target.get("title") or app,
            "current": format_version(current) if current else "",
            "latest": "",
            "available": 0,
            "success": 0,
        }
        try:
            if current is None:
                message = "current version is not a dotted triple"
                raise ValueError(message)
            releases = (
                searxng_image_tags(timeout)
                if target.get("source") == "searxng-image-tags"
                else fetch(target["github"], timeout)
            )
            latest, _tag = latest_stable(releases)
            if latest is None:
                message = "no stable release"
                raise ValueError(message)
            sample["latest"] = format_version(latest)
            sample["available"] = 1 if latest > current else 0
            sample["success"] = 1
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            sample["success"] = 0
        samples.append(sample)
    return samples


def render_metrics(samples: Iterable[Sample]) -> str:
    lines = [
        "# HELP socrat_software_update_available Pinned version is older than the newest stable GitHub release.",
        "# TYPE socrat_software_update_available gauge",
        "# HELP socrat_software_update_check_success Latest-release lookup succeeded.",
        "# TYPE socrat_software_update_check_success gauge",
    ]
    for sample in samples:
        labels = (
            f'app="{escape_label(sample["app"])}",'
            f'title="{escape_label(sample["title"])}",'
            f'current="{escape_label(sample["current"])}",'
            f'latest="{escape_label(sample["latest"])}"'
        )
        lines.append(f"socrat_software_update_available{{{labels}}} {sample['available']}")
        lines.append(
            "socrat_software_update_check_success"
            f'{{app="{escape_label(sample["app"])}"}} {sample["success"]}'
        )
    return "\n".join(lines) + "\n"


class State:
    """Mutable state collected by the update watcher."""

    def __init__(self) -> None:

        self.lock = threading.Lock()
        self.body = render_metrics([]).encode()

    def update(self, samples: Iterable[Sample]) -> None:
        """Regenerate the metrics body from fresh samples under the lock."""
        body = render_metrics(samples).encode()
        with self.lock:
            self.body = body


def actionable_metrics(alerts: list[dict]) -> bytes:
    """Count Alertmanager instances after silencing and inhibition, not rule states."""
    if not isinstance(alerts, list):
        msg = "expected Alertmanager alert list"
        raise ValueError(msg)
    counts = {"critical": 0, "warning": 0}
    for alert in alerts:
        labels = alert["labels"]
        severity = labels.get("severity")
        if (
            alert["status"]["state"] == "active"
            and severity in counts
            and labels["alertname"] not in {"Watchdog", "InfoInhibitor"}
        ):
            counts[severity] += 1
    return "".join(
        f'socrat_actionable_alerts{{severity="{severity}"}} {count}\n'
        for severity, count in counts.items()
    ).encode()


def serve(state: State, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/actionable-alerts":
                try:
                    with urllib.request.urlopen(
                        "http://kube-prometheus-stack-alertmanager:9093/api/v2/alerts",
                        timeout=4,
                    ) as response:
                        body = actionable_metrics(json.load(response))
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    self.send_error(503, "Alertmanager data unavailable")
                    return
            elif self.path == "/metrics":
                with state.lock:
                    body = state.body
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        @override
        def log_message(self, _fmt: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


def workload_ref(target: Target) -> tuple[str, str | None]:
    if target.get("deployment") and target.get("statefulset"):
        message = "ambiguous workload target"
        raise ValueError(message)
    if target.get("statefulset"):
        return "statefulsets", target["statefulset"]
    return "deployments", target.get("deployment")


def deployment_image(target: Target, timeout: int) -> str | None:
    namespace = target.get("namespace")
    resource, name = workload_ref(target)
    container = target.get("container")
    if not (namespace and name and container):
        return None
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    token = (
        open("/var/run/secrets/kubernetes.io/serviceaccount/token", encoding="utf-8").read().strip()
    )
    url = f"https://{host}:{port}/apis/apps/v1/namespaces/{namespace}/{resource}/{name}"
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    context = None
    import ssl

    context = ssl.create_default_context(
        cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    )
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        payload = json.load(response)
    for item in payload["spec"]["template"]["spec"]["containers"]:
        if item.get("name") == container:
            image: str | None = item.get("image")
            return image
    message = f"container {container} not found on {namespace}/{name}"
    raise ValueError(message)


def load_images(targets: Iterable[Target], timeout: int) -> dict[str, str | None]:
    images = {}
    for target in targets:
        if not (target.get("deployment") or target.get("statefulset")):
            continue
        try:
            images[target["id"]] = deployment_image(target, timeout)
        except (
            OSError,
            urllib.error.URLError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ):
            images[target["id"]] = None
    return images


def main() -> None:
    catalog = os.environ.get("UPDATE_WATCH_CATALOG", "/etc/update-watch/targets.json")
    interval = int(os.environ.get("UPDATE_WATCH_INTERVAL_SECONDS", "21600"))
    timeout = int(os.environ.get("UPDATE_WATCH_TIMEOUT_SECONDS", "20"))
    port = int(os.environ.get("UPDATE_WATCH_PORT", "8080"))
    with open(catalog, encoding="utf-8") as handle:
        targets: list[Target] = json.load(handle)
    state = State()

    def refresh() -> None:
        while True:
            state.update(evaluate(targets, fetch_releases, timeout, load_images(targets, timeout)))
            time.sleep(interval)

    threading.Thread(target=refresh, daemon=True).start()
    serve(state, port)


if __name__ == "__main__":
    main()
