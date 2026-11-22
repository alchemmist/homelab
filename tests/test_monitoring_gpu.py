"""Offline contracts for GPU metric text and failure replacement."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "ansible/roles/monitoring_gpu/files/collect_gpu.py"
SPEC = importlib.util.spec_from_file_location("collect_gpu", SOURCE)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)
ROW = "GPU-123, NVIDIA RTX 3090, 0, 50, 20, 30, 1024, 24576, 100, 350, 40, 210, 405, P8, Active, Not Active, Not Active, N/A\n"


class GPUCollectorTests(unittest.TestCase):
    """Check per-card metrics and replacement of earlier samples on failure."""

    def test_multiple_cards_units_and_unsupported_values(self) -> None:
        """Publish finite per-card units and skip unsupported power-brake samples."""
        output = COLLECTOR.parse_metrics(
            ROW + ROW.replace("GPU-123", "GPU-456").replace(", 50,", ", N/A,")
        )
        assert (
            'socrat_gpu_memory_used_bytes{uuid="GPU-123",name="NVIDIA RTX 3090",index="0"} 1073741824'
            in output
        )
        assert (
            'socrat_gpu_utilization_ratio{uuid="GPU-123",name="NVIDIA RTX 3090",index="0"} 0.2'
            in output
        )
        assert output.count("socrat_gpu_temperature_celsius") == 1
        assert 'reason="hw_power_brake_slowdown"' not in output
        assert 'reason="sw_thermal_slowdown"} 1' in output

    def test_nonfinite_values_are_not_published(self) -> None:
        """Omit temperature when the sample is non-finite."""
        output = COLLECTOR.parse_metrics(ROW.replace(", 50,", ", inf,"))
        assert "temperature_celsius" not in output

    def test_failure_replaces_previous_gpu_values(self) -> None:
        """Replace a previous success text when collection times out."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nvidia.prom"
            output.write_text(COLLECTOR.parse_metrics(ROW))
            with patch.object(
                COLLECTOR.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("nvidia-smi", 20),
            ):
                assert COLLECTOR.collect("nvidia-smi", output) == 0
            assert "temperature" not in output.read_text()
            assert "socrat_gpu_collection_success 0" in output.read_text()
            assert "socrat_gpu_collection_timestamp_seconds" in output.read_text()
            expected_mode = 0o644
            assert output.stat().st_mode & 511 == expected_mode
            assert list(Path(directory).iterdir()) == [output]

    def test_malformed_result_is_failure_without_partial_metrics(self) -> None:
        """Publish failure instead of partial metrics when a row is malformed."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nvidia.prom"
            result = subprocess.CompletedProcess([], 0, stdout=ROW + "bad,row\n")
            with patch.object(COLLECTOR.subprocess, "run", return_value=result):
                assert COLLECTOR.collect("nvidia-smi", output) == 0
            assert "temperature" not in output.read_text()


if __name__ == "__main__":
    unittest.main()
