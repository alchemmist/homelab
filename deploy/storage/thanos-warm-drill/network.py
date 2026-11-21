"""Run a bounded isolated 0 -> 1 shipper outage drill (no live bucket mounted)."""

import json, secrets, subprocess, sys, time
from copy import deepcopy
from job import PYTHON, PROM, THANOS, container

NS = "cattle-monitoring-system"
RUN = "warm-net-" + secrets.token_hex(4)
SEL = {"warm-drill": RUN}
made = []
RUST = "rustfs/rustfs:1.0.4@sha256:ed9210d6411d77ffceb70d94b964a3cb7d225983368bc25bebe01e995293dcc2"


def k(*args, data=None, check=True):
    proc = subprocess.run(
        ["kubectl", "--request-timeout=15s", "-n", NS, *args],
        input=data,
        text=True,
        capture_output=True,
        timeout=25,
    )
    if check and proc.returncode:
        raise RuntimeError(str(args[:3]) + ": " + proc.stderr[-400:])
    return proc


def add(kind, spec, tail="", api="v1"):
    name = RUN + tail
    obj = {
        "apiVersion": api,
        "kind": kind,
        "metadata": {"name": name, "labels": SEL},
        **spec,
    }
    k("create", "-f", "-", data=json.dumps(obj))
    made.append((kind, name))
    return name


def wait(fn, seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        result = fn()
        if result:
            return result
        time.sleep(3)
    raise RuntimeError("timeout: " + fn.__name__)


def ex(p, c, *args):
    return k("exec", p, "-c", c, "--", *args, check=False)


def mount(name, path, ro=False):
    return {"name": name, "mountPath": path, "readOnly": ro}


def pod(node, containers, vols, init=None):
    return {
        "spec": {
            "nodeSelector": {"kubernetes.io/hostname": node},
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 3,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "runAsGroup": 10001,
                "fsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "initContainers": init or [],
            "containers": containers,
            "volumes": [{"name": "scratch", "emptyDir": {"sizeLimit": "1Gi"}}, *vols],
        }
    }


def drill():
    access, secret = secrets.token_hex(10), secrets.token_hex(32)
    obj = json.dumps(
        {
            "type": "S3",
            "config": {
                "bucket": "warm-test",
                "endpoint": RUN + ":9000",
                "insecure": True,
                "access_key": access,
                "secret_key": secret,
                "bucket_lookup_type": "path",
            },
        }
    )
    add(
        "Secret",
        {"stringData": {"access": access, "secret": secret, "objstore.yml": obj}},
    )
    add(
        "NetworkPolicy",
        {
            "spec": {
                "podSelector": {"matchLabels": SEL},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [{"podSelector": {"matchLabels": SEL}}],
                        "ports": [{"protocol": "TCP", "port": 9000}],
                    }
                ],
            }
        },
        api="networking.k8s.io/v1",
    )
    add(
        "Service",
        {"spec": {"selector": {**SEL, "role": "bucket"}, "ports": [{"port": 9000}]}},
    )
    data = mount("candidate", "/candidate")
    init = container(
        "prepare",
        PYTHON,
        ["python3", "-Bc"],
        [
            f"from pathlib import Path; p=Path('/candidate/{RUN}'); (p/'.rustfs/events').mkdir(parents=True,exist_ok=True); (p/'.rustfs/audit').mkdir(parents=True,exist_ok=True)"
        ],
        data,
    )
    rust = container(
        "bucket", RUST, [], [], {**mount("candidate", "/data"), "subPath": RUN}
    )
    del rust["command"], rust["args"]
    rust["resources"] = {
        "requests": {"cpu": "250m", "memory": "512Mi"},
        "limits": {"cpu": "2", "memory": "3Gi"},
    }
    rust["env"] = [
        {
            "name": "RUSTFS_" + key,
            "valueFrom": {"secretKeyRef": {"name": RUN, "key": v}},
        }
        for key, v in [("ACCESS_KEY", "access"), ("SECRET_KEY", "secret")]
    ] + [
        {"name": k, "value": v}
        for k, v in [
            ("RUSTFS_VOLUMES", "/data"),
            ("RUSTFS_CONSOLE_ENABLE", "false"),
            ("RUSTFS_OBS_LOG_DIRECTORY", "/tmp"),
            ("RUSTFS_OBS_LOGGER_LEVEL", "warn"),
        ]
    ]
    backend = pod(
        "socrat-1",
        [rust],
        [
            {
                "name": "candidate",
                "persistentVolumeClaim": {"claimName": "thanos-warm-s1-candidate"},
            }
        ],
        [init],
    )
    backend["metadata"] = {"name": RUN + "-s", "labels": {**SEL, "role": "bucket"}}

    def server():
        add("Pod", deepcopy(backend), "-s")
        wait(
            lambda: (
                ex(
                    RUN + "-s",
                    "bucket",
                    "curl",
                    "-fsS",
                    "http://localhost:9000/health/ready",
                ).returncode
                == 0
            ),
            120,
        )

    server()
    r = ex(
        RUN + "-s",
        "bucket",
        "sh",
        "-ec",
        'curl -fsS --aws-sigv4 aws:amz:us-east-1:s3 -u "$RUSTFS_ACCESS_KEY:$RUSTFS_SECRET_KEY" -X PUT http://localhost:9000/warm-test',
    )
    assert r.returncode == 0, r.stderr
    config = {
        "global": {"scrape_interval": "2s", "external_labels": {"fixture": RUN}},
        "scrape_configs": [
            {"job_name": "fixture", "static_configs": [{"targets": ["127.0.0.1:8000"]}]}
        ],
    }
    add("ConfigMap", {"data": {"prom.yml": json.dumps(config)}})
    fixture = """from http.server import BaseHTTPRequestHandler,HTTPServer
class H(BaseHTTPRequestHandler):
    n=0
    def do_GET(self):
        H.n+=1; b=f'warm_number {H.n}\\n'.encode();self.send_response(200);self.send_header('Content-Type','text/plain; version=0.0.4');self.end_headers();self.wfile.write(b)
    def log_message(self,*args): pass
HTTPServer(('127.0.0.1',8000),H).serve_forever()"""
    client = RUN + "-c"
    cfg = mount("config", "/etc/drill", True)
    scfg = mount("s3", "/etc/s3", True)
    flags = ["--objstore.config-file=/etc/s3/objstore.yml"]
    cs = [
        container("fixture", PYTHON, ["python3", "-Bc"], [fixture]),
        container(
            "prom",
            PROM,
            ["/bin/prometheus"],
            [
                "--config.file=/etc/drill/prom.yml",
                "--storage.tsdb.path=/tmp/tsdb",
                "--storage.tsdb.min-block-duration=30s",
                "--storage.tsdb.max-block-duration=30s",
                "--storage.tsdb.retention.time=2h",
                "--web.listen-address=127.0.0.1:9090",
            ],
            cfg,
        ),
        container(
            "sidecar",
            THANOS,
            ["/bin/thanos"],
            [
                "sidecar",
                *flags,
                "--tsdb.path=/tmp/tsdb",
                "--prometheus.url=http://127.0.0.1:9090",
                "--http-address=127.0.0.1:10902",
                "--grpc-address=127.0.0.1:10901",
            ],
            scfg,
        ),
        container(
            "store",
            THANOS,
            ["/bin/thanos"],
            [
                "store",
                *flags,
                "--data-dir=/tmp/store",
                "--sync-block-duration=5s",
                "--http-address=127.0.0.1:11902",
                "--grpc-address=127.0.0.1:11901",
            ],
            scfg,
        ),
        container(
            "query",
            THANOS,
            ["/bin/thanos"],
            [
                "query",
                "--endpoint=127.0.0.1:11901",
                "--http-address=127.0.0.1:12902",
                "--grpc-address=127.0.0.1:12901",
            ],
        ),
    ]
    add(
        "Pod",
        pod(
            "socrat-0",
            cs,
            [
                {"name": "config", "configMap": {"name": RUN}},
                {
                    "name": "s3",
                    "secret": {
                        "secretName": RUN,
                        "items": [{"key": "objstore.yml", "path": "objstore.yml"}],
                    },
                },
            ],
        ),
        "-c",
    )

    def samples(port, end=None):
        t = "" if end is None else "&time=" + str(end)
        code = f"import urllib.request,json;d=json.load(urllib.request.urlopen('http://127.0.0.1:{port}/api/v1/query?query=warm_number%5B20m%5D&partial_response=false{t}',timeout=4));assert not d.get('warnings');print(json.dumps(d['data']['result'][0]['values']))"
        r = ex(client, "fixture", "python3", "-c", code)
        return json.loads(r.stdout) if r.returncode == 0 else []

    wait(lambda: samples(12902), 240)
    print("remote Store read before outage: OK", flush=True)
    k("delete", "pod", RUN + "-s", "--wait=false")
    wait(lambda: k("get", "pod", RUN + "-s", check=False).returncode != 0, 60)
    a = samples(9090)
    assert a
    time.sleep(72)
    b = samples(9090)
    assert len(b) - len(a) >= 25
    logs = k("logs", client, "-c", "sidecar", "--since=90s").stdout
    assert any(
        "upload" in line.lower() and ("err=" in line or "level=warn" in line)
        for line in logs.splitlines()
    ), "shipper outage not observed"
    print("backend absent; new local samples:", len(b) - len(a), flush=True)
    end = b[-1][0]
    expected = samples(9090, end)
    assert expected and all(
        int(float(y[1])) == int(float(x[1])) + 1 for x, y in zip(expected, expected[1:])
    )
    server()
    wait(lambda: samples(12902, end) == expected, 240)
    print(
        "strict Store-only read matches local timestamps and values:",
        len(expected),
        flush=True,
    )


if __name__ == "__main__":
    if sys.argv[1:] != ["--run"]:
        sys.exit("use --run explicitly")
    if (
        subprocess.check_output(
            ["kubectl", "config", "current-context"], text=True
        ).strip()
        != "Socrat"
    ):
        sys.exit("expected Socrat kube context")
    print(RUN, flush=True)
    try:
        drill()
    finally:
        for typ, n in reversed(list(dict.fromkeys(made))):
            k("delete", typ, n, "--ignore-not-found", "--wait=false", check=False)
