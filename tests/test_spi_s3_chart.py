"""Offline opt-in/rollback and namespace AND pod boundary checks."""

import pathlib
import subprocess
import unittest
from typing import TypedDict
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def render(chart: str, *values: str):
    cmd = ["helm", "template", "test", str(ROOT / "charts" / chart)]
    for value in values:
        cmd += ["--set", value]
    return list(yaml.safe_load_all(subprocess.check_output(cmd, text=True)))


class _ChartMetadata(TypedDict):
    name: str


class _ChartDocument(TypedDict):
    kind: str
    metadata: _ChartMetadata


def resource(docs: list[_ChartDocument | None], kind: str, name: str):
    return next(d for d in docs if d and d["kind"] == kind and d["metadata"]["name"] == name)


class Chart(unittest.TestCase):
    """Render SPI and RustFS charts without a cluster."""

    def test_default_no_new_secret_write_unchanged(self) -> None:
        """Keep the default triage pod on the legacy backend without an S3 volume."""
        pod = resource(render("spi-triage"), "Deployment", "spi-triage")["spec"]["template"]["spec"]
        self.assertNotIn("s3-writer", [v["name"] for v in pod["volumes"]])
        env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
        self.assertEqual(env["SPI_EVIDENCE_BACKEND"], "legacy")
        self.assertEqual(env["WRITE_ENABLED"], "true")

    def test_activation_and_rollback_mount_and_network(self) -> None:
        """Mount the writer secret only for the enabled backend and keep rollback legacy."""
        for toggle, backend in [("enabled", "s3"), ("retainCredentials", "legacy")]:
            docs = render(
                "spi-triage",
                "s3Evidence." + toggle + "=true",
                "s3Evidence.writerSecret=spi-evidence-writer",
            )
            pod = resource(docs, "Deployment", "spi-triage")["spec"]["template"]["spec"]
            volume = next(v for v in pod["volumes"] if v["name"] == "s3-writer")
            self.assertEqual(volume["secret"]["secretName"], "spi-evidence-writer")
            self.assertEqual(volume["secret"]["defaultMode"], 0o440)
            env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
            self.assertEqual(env["SPI_EVIDENCE_BACKEND"], backend)
            self.assertEqual(env["SPI_S3_WRITER_FILE"], "/s3-writer/credentials.json")
            policy = resource(docs, "NetworkPolicy", "spi-triage")["spec"]
            rule = next(
                r for r in policy["egress"] if r["ports"] == [{"port": 9000, "protocol": "TCP"}]
            )
            self.assertEqual(
                rule["to"],
                [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "rustfs"}
                        },
                        "podSelector": {"matchLabels": {"app": "rustfs"}},
                    }
                ],
            )

    def test_fail_closed_secret(self) -> None:
        """Reject writer secret names that are empty or belong to another principal."""
        for name in ["", "rustfs-root", "rustfs-reader", "spi-triage"]:
            result = subprocess.run(
                [
                    "helm",
                    "template",
                    "test",
                    str(ROOT / "charts/spi-triage"),
                    "--set",
                    "s3Evidence.enabled=true",
                    "--set",
                    "s3Evidence.writerSecret=" + name,
                ],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_root_exact_spi_peer(self) -> None:
        """Admit only the SPI triage peer, and no peers when the writer is off."""
        docs = render("rustfs", "enabled=true", "spiWriter.enabled=true")
        policy = resource(docs, "NetworkPolicy", "rustfs-isolation")["spec"]
        self.assertEqual(
            policy["ingress"],
            [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": "automation"}
                            },
                            "podSelector": {"matchLabels": {"app": "spi-triage"}},
                        }
                    ],
                    "ports": [{"port": 9000, "protocol": "TCP"}],
                }
            ],
        )
        self.assertEqual(
            resource(render("rustfs", "enabled=true"), "NetworkPolicy", "rustfs-isolation")["spec"][
                "ingress"
            ],
            [],
        )

    def test_cats_media_is_a_separate_peer(self) -> None:
        """Keep the cats peer distinct from SPI, and absent when both writers are off."""
        docs = render("rustfs", "enabled=true", "catsMedia.enabled=true", "spiWriter.enabled=true")
        policy = resource(docs, "NetworkPolicy", "rustfs-isolation")["spec"]
        peers = [rule["from"] for rule in policy["ingress"]]
        self.assertIn(
            [
                {
                    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "cats"}},
                    "podSelector": {"matchLabels": {"app.kubernetes.io/name": "cats"}},
                }
            ],
            peers,
        )
        self.assertIn(
            [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "automation"}
                    },
                    "podSelector": {"matchLabels": {"app": "spi-triage"}},
                }
            ],
            peers,
        )
        self.assertEqual(
            resource(render("rustfs", "enabled=true"), "NetworkPolicy", "rustfs-isolation")["spec"][
                "ingress"
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
