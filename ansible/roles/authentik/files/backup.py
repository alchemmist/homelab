import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

os.environ["K3S_CONFIG_FILE"] = "/dev/null"
root = Path.home() / ".cache/homelab-authentik"
k = ["kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml", "-n", "identity"]
with tempfile.TemporaryDirectory(dir=root) as work:
    p = Path(work)
    # Resolve the active CNPG primary on each run; never dump the retained legacy PVC.
    pg = [*k[:-1], "postgres"]
    primary = subprocess.check_output(
        pg
        + [
            "get",
            "cluster.postgresql.cnpg.io",
            "pg-critical",
            "-o",
            "jsonpath={.status.currentPrimary}",
        ],
        text=True,
    ).strip()
    if not primary.startswith("pg-critical-") or not primary.removeprefix("pg-critical-").isdigit():
        msg = "Cannot resolve pg-critical primary"
        raise RuntimeError(msg)
    with (p / "database.dump").open("wb") as f:
        subprocess.run(
            pg
            + [
                "exec",
                primary,
                "-c",
                "postgres",
                "--",
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "authentik",
                "-Fc",
            ],
            stdout=f,
            check=True,
        )
    pod = json.loads(
        subprocess.check_output(
            k + ["get", "pods", "-l", "app.kubernetes.io/component=server", "-o", "json"]
        )
    )["items"][0]["metadata"]["name"]
    with (p / "data.tar").open("wb") as f:
        subprocess.run(
            k + ["exec", pod, "-c", "server", "--", "tar", "-C", "/data", "-cf", "-", "."],
            stdout=f,
            check=True,
        )
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
        for name in [
            "credentials.json",
            "oidc-clients.json",
            "values.yaml",
            "foundation.yaml",
            "services.json",
            "owner-login.json",
            "antropophag-login.json",
            "account-mappings.json",
        ]:
            tar.add(root / name, arcname=name)
        # Include machine-identity journal and guarded rollback credentials when present.
        for extra in [
            root / "automation-api.json",
            *root.glob("credentials-before-automation-*.json"),
        ]:
            if extra.exists():
                tar.add(extra, arcname=extra.name)
        for name in ["database.dump", "data.tar"]:
            tar.add(p / name, arcname=name)
