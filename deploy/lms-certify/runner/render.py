"""Render the standalone certification runner from local Git objects; never apply it."""

import argparse
import json
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REVISION = "10307eea58e346b560749cc6861b1bbb53b209f5"
FILES = (
    "__init__.py",
    "app.py",
    "catalog.py",
    "cleanup.py",
    "engine.py",
    "execution_contract.py",
    "requirements.txt",
    "sandbox_entrypoint.py",
)


def render(repository: Path) -> dict:
    """Read only the reviewed blobs, regardless of the LMS working tree state."""
    data = {
        name: subprocess.check_output(
            ["git", "-C", repository, "cat-file", "blob", f"{REVISION}:runner/{name}"],
            encoding="utf-8",
        )
        for name in FILES
    }
    config, *resources = yaml.safe_load_all((HERE / "resources.yaml").read_text())
    config["data"].update(data)
    return {"apiVersion": "v1", "kind": "List", "items": [config, *resources]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lms_repository", type=Path)
    print(json.dumps(render(parser.parse_args().lms_repository), indent=2))
