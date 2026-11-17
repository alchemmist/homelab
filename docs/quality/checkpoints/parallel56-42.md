# Parallel 56 lane 42 checkpoint

One source repair: Harbor `CONFIG_OVERWRITE_JSON` in
`ansible/roles/identity_integrations/files/integrate.py` repeated
`project_creation_restriction` with the same `adminonly` constant. The second
literal was removed. Python dict evaluation already kept the first insertion
position and that value, so the composed JSON object is unchanged.

The operational script was not executed. Proof is an executable AST comparison
of the saved pre-change module against the edited module: stripping later
duplicate constant keys from the pre-change AST reproduces the post-change AST.
Both copies of the key had identical value ASTs. Key order matches first
insertion. `ruff format --check` on the edited file exits 0.

Offline test `tests/test_quality_p56_42_harbor_overwrite.py` parses that mapping
and checks uniqueness, constant values, client-field subscript chains, and the
insertion-order JSON rule. It does not import or run the script.

Pinned tools were the parent `.venv/bin` `ruff`, `mypy`, and `python`, with
`.quality-tools/bin` also prepended to `PATH`. Commands ran in this worktree
with `quality/ruff.toml` and `quality/mypy.ini`. Counts use
`subprocess.run(check=False)`.

| Check | Command | Before | After | Exit |
| --- | --- | --- | --- | --- |
| Ruff lane files | `ruff check --config quality/ruff.toml --output-format json` on the 42 allocated files | 1798 findings, 1 `F601` | 1797 findings, 0 `F601` | 1, then 1 |
| Ruff edited file | same command, `integrate.py` only (counted from the lane JSON) | 50 | 49 | included above |
| Ruff new test | `ruff check --config quality/ruff.toml` on the new test | n/a | 0 | 0 |
| Ruff format | `ruff format --check --config quality/ruff.toml` on the edited file and the new test | n/a | both formatted | 0 and 0 |
| Mypy lane files | `mypy --config-file quality/mypy.ini --follow-imports=silent --no-incremental` plus the adapter flags `--no-error-summary --no-pretty --no-color-output --hide-error-context --show-error-codes` | 847 errors in 40 files; 47 in `integrate.py` | 847 errors in 40 files; 47 in `integrate.py`; 0 in the new test | 1, then 1 |
| Pytest | `python -m pytest tests/test_quality_p56_42_harbor_overwrite.py -p no:cacheprovider -q` | n/a | 2 passed | 0 |

No scheduled offline tests were allocated to this lane. Existing Harbor and IAM
suites were not run because they belong to other lanes or execute integration
entrypoints.

Remaining blockers on the allocated files: 1797 Ruff findings and 847 strict
mypy errors. On `integrate.py` the remaining Ruff codes are `ANN001` (9),
`TRY003` (7), `EM101` (7), `T201` (6), `E501` (5), `ANN201` (4), `D103` (4),
`I001` (2), and one each of `INP001`, `S603`, `PLW1510`, `S310`, and `PLC0415`.
`S603` and `S310` are the intentional `kubectl` and Authentik HTTP calls;
rewriting them would change the operational entrypoint. The other allocated
scripts still need separate behavior-preserving repairs. Historical
`quality/debt/python.json` still records the old `F601` and was not refreshed.
