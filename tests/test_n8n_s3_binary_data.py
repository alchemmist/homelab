"""Offline checks for n8n binary-data external storage in RustFS."""

import ast
import json
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rustfs" / "n8n_objectstore.py"
VALUES = ROOT / "charts" / "n8n" / "values.yaml"


class N8nS3BinaryData(unittest.TestCase):
    """Prove the reconciler and chart wiring stay within the runbook shape."""

    def test_script_compiles_and_is_offline_shaped(self) -> None:
        """The reconciler parses, never prints secrets and stays explicit-apply."""
        tree = ast.parse(SCRIPT.read_text())
        funcs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef,))}
        assert {"main", "run", "render_secret", "require_private_bucket"} <= funcs
        source = SCRIPT.read_text()
        assert "--apply" in source
        assert "print" in source
        # CLI args come from argparse only; credentials reach mc through stdin.
        assert "sys.argv" not in source
        assert 'stdin=(access + ' in source
        subprocess.run(
            ["python3", "-m", "py_compile", str(SCRIPT)], check=True, capture_output=True
        )

    def test_policy_is_readonly_bucket_scoped(self) -> None:
        """The pinned policy only reads and writes objects inside the bucket."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("n8n_objectstore", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        policy = module.IDENTITY_POLICY
        assert policy["Statement"][0]["Action"] == ["s3:GetObject", "s3:PutObject"]
        assert policy["Statement"][0]["Resource"] == ["arn:aws:s3:::n8n-binary/*"]
        # n8n's startup checkConnection needs HeadBucket/ListBucket on the bucket.
        assert policy["Statement"][1]["Action"] == ["s3:ListBucket"]
        assert policy["Statement"][1]["Resource"] == ["arn:aws:s3:::n8n-binary"]
        assert len(policy["Statement"]) == 2
        assert module.BUCKET == "n8n-binary"

    def test_render_secret_shape(self) -> None:
        """The rendered Secret carries exactly the two S3 credential fields."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("n8n_objectstore", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        import base64

        doc = module.render_secret(
            {"n8n": {"access": "a" * 20, "secret": "b" * 20}}
        )
        assert doc["metadata"] == {
            "name": "n8n-s3-storage",
            "namespace": "automation",
        }
        assert set(doc["data"]) == {"accessKey", "accessSecret"}
        for key, value in doc["data"].items():
            decoded = base64.b64decode(value).decode()
            assert key == "accessKey" and decoded == "a" * 20 or key == "accessSecret" and decoded == "b" * 20

    def test_chart_wires_s3_envs_only_when_enabled(self) -> None:
        """Enabled renders the S3 env block; disabled renders nothing."""
        enabled = subprocess.run(
            ["helm", "template", "n8n", str(ROOT / "charts" / "n8n")],
            capture_output=True,
            text=True,
            check=True,
        )
        for needle in (
            "N8N_DEFAULT_BINARY_DATA_MODE",
            "N8N_EXTERNAL_STORAGE_S3_HOST",
            "N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME",
            "n8n-s3-storage",
        ):
            assert needle in enabled.stdout
        disabled = subprocess.run(
            [
                "helm",
                "template",
                "n8n",
                str(ROOT / "charts" / "n8n"),
                "--set",
                "s3BinaryData.enabled=false",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "N8N_EXTERNAL_STORAGE" not in disabled.stdout

    def test_values_enable_s3_in_chart_and_deploy(self) -> None:
        """Chart values (the live ArgoCD source) enable S3; deploy values match."""
        values = yaml.safe_load(VALUES.read_text())
        assert values["s3BinaryData"] == {
            "enabled": True,
            "secretName": "n8n-s3-storage",
            "host": "rustfs.rustfs.svc.cluster.local:9000",
            "protocol": "http",
            "bucket": "n8n-binary",
            "region": "us-east-1",
        }
        deploy = yaml.safe_load((ROOT / "deploy" / "n8n" / "values.yaml").read_text())
        assert deploy["s3BinaryData"] == {
            "enabled": True,
            "secretName": "n8n-s3-storage",
        }


if __name__ == "__main__":
    unittest.main()
