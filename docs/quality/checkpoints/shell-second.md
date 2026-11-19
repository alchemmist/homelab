# Shell strict checkpoint — second owned standalone batch

This is not a clean shell tree. Eight owned standalone scripts were repaired
under ShellCheck 0.11.0 with `--norc --enable=all` and the shebang dialect.
`charts/lms-database-ha/files/backup.sh` was not edited. No production SSH,
kubeconfig, VPN, GPU, inference, backup, or host `iptables`/`limactl`/`systemctl`
run was performed. No disable directive, debt approval, or rule weakening was
added.

The adapter does not pass `--shell` for standalone scripts. Optional checks are
`--enable=all`, same as `scripts/quality/lint.py` `shellcheck_files`.

## Commands and exits

`uv sync --locked` in the isolated worktree. Exit 0. It created `.venv` and
installed the locked tools. `uv.lock` was not changed.

Seven repaired scripts, 0 findings:

```text
shellcheck --norc --enable=all --format=json \
  ansible/roles/desktop_environment/files/caffeine-manager.sh \
  ansible/roles/desktop_panel/files/toggle_noscreenshare.sh \
  ansible/roles/starship/files/arc-refresh.sh \
  ansible/roles/starship/files/arc_dots.sh \
  ansible/roles/starship/files/arc_metrics.sh \
  ansible/roles/starship/files/arc_status.sh \
  scripts/testing-class-wg-guard.sh
```

Exit 0. Stdout was `[]`.

`scripts/nightnode/nightnode` with the same flags:

```text
scripts/nightnode/nightnode:27:12: warning: ShellCheck can't follow non-constant source. Use a directive to specify location. [SC1090]
```

Exit 1. One finding. The source line is still `source "${CONFIG_FILE}"`. No
constant path and no directive were added.

`bash -n` on the bash scripts and `/bin/sh -n` on `arc-refresh.sh` and
`scripts/testing-class-wg-guard.sh`. Exit 0. Those checks do not execute the
scripts.

Owned standalone inventory (`shell_targets(owned(tracked()))`, 23 files), same
ShellCheck flags:

- Before this batch, from `docs/quality/checkpoints/shell-next.md`: exit 1,
  119 findings, 9 files.
- After this batch: exit 1, 8 findings, 2 files.

```text
nightnode 1 (SC1090)
backup.sh 7 (SC2250)
```

Rules still open: `SC1090` 1, `SC2250` 7. The seven `SC2250` hits are all in
`charts/lms-database-ha/files/backup.sh`, which this lane did not touch.

```text
uv run pytest -q tests/test_shell_strict_second_batch.py \
  tests/test_socrat5_bootstrap.py::BootstrapTests::test_guard_is_pre_dnat_and_source_scoped
```

Exit 0. 16 passed. Widget cases use a temporary `HOME` and a fake `arc` /
`python3`. They do not call a real Arc, Lima, iptables, systemctl, or pkill.
Caffeine, the screenshare toggle, nightnode, and the WireGuard guard were not
executed.

```text
uv run pytest -q tests/test_shell_strict_regressions.py
```

Exit 0. 12 passed.

```text
uv run mypy --config-file quality/mypy.ini --strict --follow-imports=silent \
  --warn-unreachable --explicit-package-bases --disallow-any-explicit \
  --disallow-any-unimported --disallow-any-decorated --strict-equality-for-none \
  tests/test_shell_strict_second_batch.py
```

Exit 0.

```text
uv run ruff check --config quality/ruff.toml tests/test_shell_strict_second_batch.py
```

Exit 1. Two findings, both left visible: `INP001` because `tests/` has no
`__init__.py`, and one `S603` at the single subprocess boundary. No `noqa` was
added.

```text
uv run ruff format --check --config quality/ruff.toml tests/test_shell_strict_second_batch.py
```

Exit 0.

Suppression scan of the eight scripts plus the new test: 0 hits.

`tests/test_socrat5_bootstrap.py::BootstrapTests::test_peer_admission_is_cas_and_no_transport_restart`
fails on this base because it looks for `==EXPECTED` and the unchanged
`scripts/wg-testing-class-admit.py` has `== EXPECTED`. That file was not edited.

## What changed

111 findings removed. One owned finding remains.

| Script | Cleared | Still open | Preservation |
| --- | ---: | ---: | --- |
| `ansible/roles/starship/files/arc-refresh.sh` | 25 | 0 | POSIX `sh`. Missing args, a held lock, and a failed `cd` still exit 0. The lock is created with `mkdir` and removed only by the existing trap. A helper's stdout is still written when that helper exits non-zero, and later segments are still written. |
| `ansible/roles/starship/files/arc_status.sh` | 23 | 0 | `arc info` failure and `arc status` failure still exit 0 with no symbol. The status failure still discards that snapshot. Unknown status lines still increment the printed total. Empty `*)` arms do not reject them. Stash stdout is still counted when `arc stash` fails. |
| `ansible/roles/desktop_environment/files/caffeine-manager.sh` | 19 | 0 | The same three status strings. Predicates are refreshed and then tested, so `set -e` stays on around the caller and off around `pgrep`, `systemctl`, and `grep`. The two original `pkill ... \|\| true` lines remain. Not executed. |
| `ansible/roles/desktop_panel/files/toggle_noscreenshare.sh` | 14 | 0 | The same `sed -i` programs and the same JSON class/alt output. Not executed. |
| `ansible/roles/starship/files/arc_metrics.sh` | 12 | 0 | Missing `arc info`, or a diff with no `changed` line, still exits 0 with empty stdout. A failing `arc diff` that printed a stat line still formats `+N` and `-M`. |
| `ansible/roles/starship/files/arc_dots.sh` | 11 | 0 | Unknown side and missing `arc info` still exit 0. No `remote_head` still uses `arcadia/trunk`. A failing `arc log` still contributes the lines it printed. Zero lines still print nothing and exit 0. |
| `scripts/nightnode/nightnode` | 6 | 1 | Config is still sourced from `${CONFIG_FILE}`. `vm_status` keeps command stdout when `limactl` fails and does not abort the caller. An empty menu resource line still fails the script before it prints. The original kubectl cordon, drain, delete, and InternalIP `\|\| true` lines remain. Not executed. |
| `scripts/testing-class-wg-guard.sh` | 1 | 0 | The DROP rule is now `-A "${CHAIN}" -j DROP`. The chain, addresses, and refusal text are unchanged. Not executed. |

`tests/test_socrat5_bootstrap.py` now looks for the braced DROP rule. That is
the same rule, with braces required by `SC2250`.

No `|| true` was added. Widget scripts still have no `set -e`. Their explicit
continuations remain `|| exit 0` on missing metadata, lock contention, a bad
directory, and a failed status snapshot. Direct assignments replace nested
command substitutions so ShellCheck can see each command status without
discarding stdout.

## Remaining blocker

`scripts/nightnode/nightnode` `SC1090` is a non-constant `source`. `CONFIG_FILE`
is `${NIGHTNODE_CONFIG_DIR:-${HOME}/.config/homelab/nightnode}/config.env`.
ShellCheck's usual fix is a source directive or a constant path. A directive is
forbidden, and pinning one path would change config loading. The finding stays
visible. It was not given a fake file for ShellCheck to follow.

`charts/lms-database-ha/files/backup.sh` remains `SC2250` only and was not
modified.

A strict lint result is not production acceptance.
