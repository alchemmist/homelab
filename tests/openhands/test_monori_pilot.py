"""The retired mutation pilot is not shipped in the chart or campaign declarations."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative",
    [
        "charts/openhands/files/pilot",
        "charts/openhands/templates/mutation-pilot.yaml",
        "docs/n8n/monori-pilot/campaign.json",
    ],
)
def test_retired_pilot_payload_is_absent(relative: str) -> None:
    """Guard against repackaging dormant executable code as well as re-enabling the role."""
    assert not (ROOT / relative).exists()
