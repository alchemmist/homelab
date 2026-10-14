#!/usr/bin/env python3
import csv
import json
import shutil
import subprocess
from pathlib import Path


def sample():
    tool = shutil.which("nvidia-smi")
    if tool:
        try:
            result = subprocess.run(
                [tool, "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2, check=True,
            )
            row = next(csv.reader(result.stdout.splitlines(), skipinitialspace=True))
            name, usage, temperature, used, total = (value.strip() for value in row)
            percentage = float(usage)
            if not 0 <= percentage <= 100:
                raise ValueError("invalid GPU utilization")
            return {"text": f"GPU {percentage:.0f}%", "percentage": round(percentage), "tooltip": f"{name}\nLoad: {usage}%\nTemperature: {temperature} °C\nVRAM: {used} / {total} MiB", "class": "active"}
        except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
            pass
    for path in sorted(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")):
        try:
            usage = int(path.read_text().strip())
            if 0 <= usage <= 100:
                return {"text": f"GPU {usage}%", "percentage": usage, "tooltip": "GPU load", "class": "active"}
        except (OSError, ValueError):
            pass
    return {"text": "GPU n/a", "tooltip": "GPU utilization is unavailable from the current driver. NVIDIA GPUs require a working NVIDIA driver and nvidia-smi.", "class": "unavailable"}


if __name__ == "__main__":
    print(json.dumps(sample(), ensure_ascii=False))
