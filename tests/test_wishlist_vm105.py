"""Tests for wishlist vm105 deployment moves."""

import os
import pathlib
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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

    @staticmethod
    def render(*options: str):
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
                *options,
            ],
            text=True,
        )
        return [d for d in yaml.safe_load_all(raw) if d]

    def test_production_has_one_writer_exact_image_and_fails_closed_on_empty_data(self) -> None:
        docs = self.render()
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
        (init,) = s["initContainers"]
        assert init["name"] == "require-imported-wishlist"
        assert init["command"] == ["python", "-c"]
        assert init["env"] == [
            {
                "name": "WISHLIST_DATABASE_URL",
                "valueFrom": {
                    "secretKeyRef": {"name": "wishlist-postgres", "key": "url"},
                },
            }
        ]
        # Exercise the rendered read against a synthetic driver, never real
        # credentials or a database. Missing data and connection errors must stop.
        with tempfile.TemporaryDirectory() as t:
            script = pathlib.Path(t) / "guard.py"
            script.write_text(init["args"][0])
            driver = MagicMock()
            connection = driver.connect.return_value.__enter__.return_value
            with (
                patch.dict("sys.modules", psycopg=driver),
                patch.dict(os.environ, WISHLIST_DATABASE_URL="fixture"),
            ):
                for exists in (False, True):
                    driver.reset_mock()
                    connection.execute.return_value.fetchone.return_value = (exists,)
                    if exists:
                        runpy.run_path(str(script))
                    else:
                        with self.assertRaises(AssertionError):
                            runpy.run_path(str(script))
                    driver.connect.assert_called_once_with("fixture", connect_timeout=5)
                    connection.execute.assert_called_once_with("SELECT EXISTS(SELECT FROM users)")
                driver.connect.side_effect = ConnectionError("fixture unavailable")
                with self.assertRaises(ConnectionError):
                    runpy.run_path(str(script))
        old = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
        assert old["metadata"]["name"] == "wishlist-data"

    def test_retained_sqlite_mode_refuses_missing_empty_or_invalid_database(self) -> None:
        docs = self.render("--set", "postgresEnabled=false")
        d = next(
            d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "wishlist"
        )
        (init,) = d["spec"]["template"]["spec"]["initContainers"]
        assert init["name"] == "require-existing-wishlist"
        guard = init["args"][0]
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

    def test_shared_defaults_do_not_repoint_existing_data(self) -> None:
        v = yaml.safe_load((R / "charts/wishlist/values.yaml").read_text())
        assert v["persistence"] == {"existingClaim": "wishlist-data", "requireExistingData": False}
        assert v["hostAliases"] == []


if __name__ == "__main__":
    unittest.main()
