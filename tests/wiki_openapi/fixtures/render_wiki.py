"""Offline stand-in for the bot repository's scripts/render_wiki.py.

The production render stage runs the renderer committed next to the OpenAPI
spec in the bot repository, which is not vendored here. This stub keeps the
same contract: read ``openapi.yaml`` from the same directory as the target
path and write a wiki page carrying the required Socrat Bot front matter and
message API section.
"""

import pathlib
import sys

# argv is the program name plus exactly one target path.
EXPECTED_ARGC = 2

FRONT_MATTER = """---
title: "Socrat Bot"
weight: 35
---
"""


def main() -> None:
    """Render the fixture page so the render stage can be exercised offline."""
    if len(sys.argv) != EXPECTED_ARGC:
        message = "Usage: render_wiki.py <target>"
        raise SystemExit(message)
    target = pathlib.Path(sys.argv[1])
    spec = target.with_name("openapi.yaml").read_text()
    if "openapi:" not in spec:
        message = "fixture renderer received no OpenAPI document"
        raise ValueError(message)
    target.write_text(
        FRONT_MATTER
        + "\nFixture page rendered by the offline renderer stub.\n\n"
        + "## Methods\n\n### `POST /v1/messages`\n\nSend a message.\n"
    )


if __name__ == "__main__":
    main()
