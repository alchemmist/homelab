"""Keep offline GitOps rendering away from live analytics credentials."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_umami_image_is_immutable_and_secret_external() -> None:
    """Require an immutable Umami image and an external secret name."""
    values = yaml.safe_load((ROOT / "charts/umami/values.yaml").read_text())
    assert re.fullmatch(r"ghcr.io/umami-software/umami@sha256:[0-9a-f]{64}", values["umamiImage"])
    assert values["secretName"] == "umami-env"
    source = (ROOT / "charts/umami/templates/secret.yaml").read_text()
    assert "kind: Secret" not in source
    assert "stringData:" not in source


@pytest.mark.skipif(not shutil.which("helm"), reason="Helm binary required")
def test_offline_render_references_but_never_replaces_credentials() -> None:
    """Require rendered resources to reference credentials without embedding them."""
    rendered = subprocess.check_output(
        ["helm", "template", "umami", str(ROOT / "charts/umami"), "--namespace", "umami"], text=True
    )
    resources = [x for x in yaml.safe_load_all(rendered) if x]
    assert not any(x["kind"] == "Secret" for x in resources)
    deployments = {x["metadata"]["name"]: x for x in resources if x["kind"] == "Deployment"}
    app = deployments["umami"]["spec"]["template"]["spec"]["containers"][0]
    assert app["envFrom"] == [{"secretRef": {"name": "umami-env"}}]
    assert [e for e in app["env"] if e["name"] == "DATABASE_URL"] == [
        {
            "name": "DATABASE_URL",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "umami-pg-common",
                    "key": "DATABASE_URL",
                }
            },
        },
    ]
    assert {"name": "NODE_EXTRA_CA_CERTS", "value": "/etc/pg-common/ca.crt"} in app["env"]
    assert app["volumeMounts"] == [
        {"name": "pg-ca", "mountPath": "/etc/pg-common", "readOnly": True}
    ]
