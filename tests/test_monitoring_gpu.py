import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "ansible/roles/monitoring_gpu/files/collect_gpu.py"
SPEC = importlib.util.spec_from_file_location("collect_gpu", SOURCE)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)
ROW = 'GPU-123, NVIDIA RTX 3090, 0, 50, 20, 30, 1024, 24576, 100, 350, 40, 210, 405, P8, Active, Not Active, Not Active, N/A\n'


class GPUCollectorTests(unittest.TestCase):
    def test_multiple_cards_units_and_unsupported_values(self):
        output = COLLECTOR.parse_metrics(ROW + ROW.replace("GPU-123", "GPU-456").replace(", 50,", ", N/A,"))
        self.assertIn('socrat_gpu_memory_used_bytes{uuid="GPU-123",name="NVIDIA RTX 3090",index="0"} 1073741824', output)
        self.assertIn('socrat_gpu_utilization_ratio{uuid="GPU-123",name="NVIDIA RTX 3090",index="0"} 0.2', output)
        self.assertEqual(output.count("socrat_gpu_temperature_celsius"), 1)
        self.assertNotIn('reason="hw_power_brake_slowdown"', output)
        self.assertIn('reason="sw_thermal_slowdown"} 1', output)

    def test_nonfinite_values_are_not_published(self):
        output = COLLECTOR.parse_metrics(ROW.replace(", 50,", ", inf,"))
        self.assertNotIn("temperature_celsius", output)

    def test_failure_replaces_previous_gpu_values(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nvidia.prom"
            output.write_text(COLLECTOR.parse_metrics(ROW))
            with patch.object(COLLECTOR.subprocess, "run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 20)):
                self.assertEqual(COLLECTOR.collect("nvidia-smi", output), 0)
            self.assertNotIn("temperature", output.read_text())
            self.assertIn("socrat_gpu_collection_success 0", output.read_text())
            self.assertIn("socrat_gpu_collection_timestamp_seconds", output.read_text())
            self.assertEqual(output.stat().st_mode & 0o777, 0o644)
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_malformed_result_is_failure_without_partial_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nvidia.prom"
            result = subprocess.CompletedProcess([], 0, stdout=ROW + "bad,row\n")
            with patch.object(COLLECTOR.subprocess, "run", return_value=result):
                self.assertEqual(COLLECTOR.collect("nvidia-smi", output), 0)
            self.assertNotIn("temperature", output.read_text())


if __name__ == "__main__":
    unittest.main()
