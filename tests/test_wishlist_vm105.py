import pathlib, subprocess, tempfile, unittest, yaml

R = pathlib.Path(__file__).resolve().parents[1]


class WishlistMove(unittest.TestCase):
    def test_new_storage_is_local_retained_prebound_and_not_old_claim(self) -> None:
        pv, pvc = list(yaml.safe_load_all((R / "deploy/storage/wishlist-socrat5.yaml").read_text()))
        self.assertEqual(pv["spec"]["persistentVolumeReclaimPolicy"], "Retain")
        self.assertEqual(pv["spec"]["local"]["path"], "/mnt/files/homelab/wishlist/data")
        self.assertEqual(
            pv["spec"]["claimRef"], {"namespace": "wishlist", "name": "wishlist-socrat5"}
        )
        self.assertEqual(pvc["spec"]["volumeName"], pv["metadata"]["name"])
        self.assertNotEqual(pvc["metadata"]["name"], "wishlist-data")

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
        self.assertEqual(d["spec"]["replicas"], 1)
        self.assertEqual(d["spec"]["strategy"], {"type": "Recreate"})
        self.assertEqual(s["nodeSelector"], {"kubernetes.io/hostname": "socrat-5"})
        self.assertEqual(
            next(v for v in s["volumes"] if v["name"] == "data")["persistentVolumeClaim"][
                "claimName"
            ],
            "wishlist-socrat5",
        )
        self.assertEqual(s["containers"][0]["image"], s["initContainers"][0]["image"])
        self.assertEqual(
            s["hostAliases"], [{"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}]
        )
        guard = s["initContainers"][0]["args"][0]
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / "db"
            g = guard.replace("/data/wishlist.sqlite", str(p))
            for payload in [None, b"", b"not a sqlite database file"]:
                if payload is not None:
                    p.write_bytes(payload)
                result = subprocess.run(["python3", "-c", g], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
            p.write_bytes(b"SQLite format 3\x00" + b"verified-header")
            result = subprocess.run(["python3", "-c", g], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        old = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
        self.assertEqual(old["metadata"]["name"], "wishlist-data")

    def test_shared_defaults_do_not_repoint_existing_data(self) -> None:
        v = yaml.safe_load((R / "charts/wishlist/values.yaml").read_text())
        self.assertEqual(
            v["persistence"], {"existingClaim": "wishlist-data", "requireExistingData": False}
        )
        self.assertEqual(v["hostAliases"], [])


if __name__ == "__main__":
    unittest.main()
