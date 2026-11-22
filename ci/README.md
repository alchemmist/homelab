# Repository checks

`qg.yaml` selects the Make targets and their dependencies. Run `make <target>`
from the repository root for the same commands as CI. Each custom check has a
Python entry point: `ci/check_*.py` for ownership and generated artifacts,
`ci/quality/check_*.py` for code quality (e.g. `uv run python -m ci.quality.check_yaml`).
Shared inventory, reporting and installer code also lives in `ci/quality/`.
Keep lint policies and tool locks in `quality/`, tests in `tests/`, and live
operations and generators in `scripts/`. CI may import a generator, but its
verification entry point must not regenerate the artifacts.
