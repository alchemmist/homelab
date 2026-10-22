import importlib.util
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "charts/thanos/files/disk.py"
SPEC = importlib.util.spec_from_file_location("metrics_disk", SOURCE)
DISK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DISK)


class MetricsDiskTest(unittest.TestCase):
    def test_counts_prometheus_raw_and_shelf_without_other_volumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prom = root / "rancher/k3s/storage" / (
                "pvc-1_cattle-monitoring-system_" + DISK.PROMETHEUS_MARKER + "-0"
            )
            other = root / "rancher/k3s/storage/pvc-2_other"
            raw = root / "socrat-thanos"
            shelf = root / "socrat-thanos-5m"
            for directory in (prom, other, raw, shelf):
                directory.mkdir(parents=True)
            (prom / "block").write_bytes(b"a" * 1000)
            (other / "secret").write_bytes(b"b" * 5000)
            (raw / "meta.json").write_bytes(b"c" * 200)
            (shelf / "thanos").write_bytes(b"d" * 300)

            found = {role: (path, size) for role, path, size in DISK.rows(str(root))}
            self.assertEqual(set(found), {"prometheus", "raw", "shelf"})
            self.assertEqual(found["prometheus"][0], "/var/lib/prometheus")
            self.assertGreaterEqual(found["prometheus"][1], 1000)
            self.assertLess(found["prometheus"][1], 5000)
            self.assertEqual(found["raw"][0], "/var/lib/socrat-thanos")
            self.assertEqual(found["shelf"][0], "/var/lib/socrat-thanos-5m")

            body = DISK.render("socrat-0", DISK.rows(str(root)))
            self.assertIn('node="socrat-0"', body)
            self.assertIn('role="raw"', body)
            self.assertIn('path="/var/lib/socrat-thanos"', body)
            self.assertNotIn("secret", body)


if __name__ == "__main__":
    unittest.main()
