"""Check docker."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci.quality.common import Finding

from pathlib import Path

from ci.quality.common import ROOT, command, finding
from ci.quality.runner import run


def nonsecret_tokenizer_option(path, item):
    """Execute nonsecret_tokenizer_option."""
    # DL3064 matches TOKENIZERS as though it were a credential. This exact
    # public runtime option line contains no secret; any edit loses the exception.
    if path != "services/spi-tokenizer/Dockerfile" or item["code"] != "DL3064":
        return False
    line = (ROOT / path).read_text().splitlines()[item["line"] - 1]
    return line == "ENV TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1 PYTHONPATH=/app"


def docker_targets(names: list[str]) -> list[str]:
    """Include conventional Dockerfile variants without executing build instructions."""
    result: list[str] = []
    for name in names:
        basename = Path(name).name.casefold()
        if (
            basename in ("dockerfile", "containerfile")
            or basename.startswith(("dockerfile.", "containerfile."))
            or basename.endswith((".dockerfile", ".containerfile"))
        ):
            result.append(name)
    return result


def check_docker(names: list[str]) -> tuple[list[Finding], int]:
    """Run the docker linter and return findings and target count."""
    files = docker_targets(names)
    result: list[Finding] = []
    for path in files:
        data = json.loads(
            command(
                [
                    "hadolint",
                    "--config",
                    "quality/hadolint.yaml",
                    "--format",
                    "json",
                    path,
                ],
                allowed=(0, 1),
            ).stdout
        )
        result.extend(
            finding(item["code"], path, item["line"], item["message"])
            for item in data
            if not nonsecret_tokenizer_option(path, item)
        )
    return result, len(files)


if __name__ == "__main__":
    raise SystemExit(run("docker", check_docker))
