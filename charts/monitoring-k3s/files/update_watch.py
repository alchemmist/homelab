#!/usr/bin/env python3
"""Compare pinned application versions with the newest stable GitHub release."""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
UNSTABLE_RE = re.compile(r"(rc|alpha|beta|preview|dev|snapshot)", re.IGNORECASE)


def parse_version(text):
    match = VERSION_RE.search(text or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def format_version(version):
    return ".".join(str(part) for part in version)


def latest_stable(releases):
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


def escape_label(value):
    return (
        str(value)
        .replace("\\", r"\\")
        .replace("\n", r"\n")
        .replace('"', r'\"')
    )


def fetch_releases(repo, timeout):
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
        raise ValueError(f"unexpected GitHub response for {repo}")
    return payload


def version_from_image(image):
    """Version embedded in a tag. Digest-only references have no tag."""
    if not image:
        return None
    ref = image.split("@", 1)[0]
    slash = ref.rfind("/")
    colon = ref.rfind(":")
    if colon <= slash:
        return None
    return parse_version(ref[colon + 1 :])


def installed_version(target, images):
    image = None if images is None else images.get(target["id"])
    live = version_from_image(image)
    if live is not None:
        return live
    return parse_version(str(target.get("current", "")))


def evaluate(targets, fetch, timeout, images=None):
    samples = []
    for target in targets:
        app = target["id"]
        current = installed_version(target, images)
        sample = {
            "app": app,
            "title": target.get("title") or app,
            "current": format_version(current) if current else "",
            "latest": "",
            "available": 0,
            "success": 0,
        }
        try:
            if current is None:
                raise ValueError("current version is not a dotted triple")
            releases = fetch(target["github"], timeout)
            latest, _tag = latest_stable(releases)
            if latest is None:
                raise ValueError("no stable release")
            sample["latest"] = format_version(latest)
            sample["available"] = 1 if latest > current else 0
            sample["success"] = 1
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            sample["success"] = 0
        samples.append(sample)
    return samples


def render_metrics(samples):
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
    def __init__(self):
        self.lock = threading.Lock()
        self.body = render_metrics([]).encode()

    def update(self, samples):
        body = render_metrics(samples).encode()
        with self.lock:
            self.body = body


def serve(state, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_response(404)
                self.end_headers()
                return
            with state.lock:
                body = state.body
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _fmt, *_args):
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


def workload_ref(target):
    if target.get("deployment") and target.get("statefulset"):
        raise ValueError("ambiguous workload target")
    if target.get("statefulset"):
        return "statefulsets", target["statefulset"]
    return "deployments", target.get("deployment")


def deployment_image(target, timeout):
    namespace = target.get("namespace")
    resource, name = workload_ref(target)
    container = target.get("container")
    if not (namespace and name and container):
        return None
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    token = open("/var/run/secrets/kubernetes.io/serviceaccount/token", encoding="utf-8").read().strip()
    url = f"https://{host}:{port}/apis/apps/v1/namespaces/{namespace}/{resource}/{name}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    context = None
    import ssl
    context = ssl.create_default_context(cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        payload = json.load(response)
    for item in payload["spec"]["template"]["spec"]["containers"]:
        if item.get("name") == container:
            return item.get("image")
    raise ValueError(f"container {container} not found on {namespace}/{name}")


def load_images(targets, timeout):
    images = {}
    for target in targets:
        if not (target.get("deployment") or target.get("statefulset")):
            continue
        try:
            images[target["id"]] = deployment_image(target, timeout)
        except (OSError, urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError):
            images[target["id"]] = None
    return images


def main():
    catalog = os.environ.get("UPDATE_WATCH_CATALOG", "/etc/update-watch/targets.json")
    interval = int(os.environ.get("UPDATE_WATCH_INTERVAL_SECONDS", "21600"))
    timeout = int(os.environ.get("UPDATE_WATCH_TIMEOUT_SECONDS", "20"))
    port = int(os.environ.get("UPDATE_WATCH_PORT", "8080"))
    with open(catalog, encoding="utf-8") as handle:
        targets = json.load(handle)
    state = State()

    def refresh():
        while True:
            state.update(evaluate(targets, fetch_releases, timeout, load_images(targets, timeout)))
            time.sleep(interval)

    threading.Thread(target=refresh, daemon=True).start()
    serve(state, port)


if __name__ == "__main__":
    main()
