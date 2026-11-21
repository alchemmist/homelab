"""Tests for wishlist vm105 deployment moves."""

import pathlib
import subprocess
import tempfile
import unittest

import yaml

R = pathlib.Path(__file__).resolve().parents[1]


class WishlistMove(unittest.TestCase):
    """Tests or helper for WishlistMove."""

    def test_new_storage_is_local_retained_prebound_and_not_old_claim(self) -> None:
        pv, pvc = list(yaml.safe_load_all((R / "deploy/storage/wishlist-socrat5.yaml").read_text()))
        assert pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
        assert pv["spec"]["local"]["path"] == "/mnt/files/homelab/wishlist/data"
        assert pv["spec"]["claimRef"] == {"namespace": "wishlist", "name": "wishlist-socrat5"}
        assert pvc["spec"]["volumeName"] == pv["metadata"]["name"]
        assert pvc["metadata"]["name"] != "wishlist-data"

    def test_production_has_one_writer_exact_image_and_fails_closed_on_empty_data(self) -> None:
        raw = subprocess.check_output(
            [
                "helm",
                "template",
                "wishlist",
                str(R / "charts/wishlist"),
                "-n",
                "wishlist",
                "-f",
                str(R / "deploy/wishlist/values.yaml"),
            ],
            text=True,
        )
        docs = [d for d in yaml.safe_load_all(raw) if d]
        d = next(d for d in docs if d["kind"] == "Deployment")
        s = d["spec"]["template"]["spec"]
        assert d["spec"]["replicas"] == 1
        assert d["spec"]["strategy"] == {"type": "Recreate"}
        assert s["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
        assert (
            next(v for v in s["volumes"] if v["name"] == "data")["persistentVolumeClaim"][
                "claimName"
            ]
            == "wishlist-socrat5"
        )
        assert s["containers"][0]["image"] == s["initContainers"][0]["image"]
        assert s["hostAliases"] == [
            {"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}
        ]
        guard = s["initContainers"][0]["args"][0]
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / "db"
            g = guard.replace("/data/wishlist.sqlite", str(p))
            for payload in [None, b"", b"not a sqlite database file"]:
                if payload is not None:
                    p.write_bytes(payload)
                result = subprocess.run(["python3", "-c", g], capture_output=True)
                assert result.returncode != 0
            p.write_bytes(b"SQLite format 3\x00" + b"verified-header")
            result = subprocess.run(["python3", "-c", g], capture_output=True)
            assert result.returncode == 0, result.stderr
        old = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
        assert old["metadata"]["name"] == "wishlist-data"

    def test_shared_defaults_do_not_repoint_existing_data(self) -> None:
        v = yaml.safe_load((R / "charts/wishlist/values.yaml").read_text())
        assert v["persistence"] == {"existingClaim": "wishlist-data", "requireExistingData": False}
        assert v["hostAliases"] == []


if __name__ == "__main__":
    unittest.main()
