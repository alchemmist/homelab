# Shell strict checkpoint — first owned standalone batch

This is not a clean shell tree. Ten owned standalone scripts were repaired
under the quality adapter's ShellCheck invocation. Workflow inline scripts,
templates, generated files, vendor trees, frozen inputs, and `.github`
were not edited. No production SSH, kubeconfig, VPN, inference, backup,
or Helm upgrade was run. No disable directive, debt approval, or rule
weakening was added.

Dialect for standalone scripts is the shebang. The adapter does not pass
`--shell` for those files. Optional checks are `--enable=all`, same as
`scripts/quality/lint.py` `shellcheck_files`.

## Commands and exits

Fixed-file ShellCheck, 0 findings:

```text
shellcheck --norc --enable=all --format=json \
  ansible/files/socrat-sudo \
  ansible/roles/debian_laptop/files/sway/homelab-sway-menu \
  ansible/roles/desktop_panel/files/paru_updates.sh \
  ansible/roles/desktop_panel/files/pacman_updates.sh \
  ansible/roles/desktop_environment/files/layout-listener.sh \
  ansible/roles/desktop_panel/files/battery-degradation.sh \
  ansible/roles/starship/files/arc_state.sh \
  services/spi-tokenizer/build-local.sh \
  ansible/roles/wiki_editor_client/files/wiki-editor-resolver.sh \
  scripts/rustfs/deploy.sh
```

Exit 0.

`bash -n` on each of those ten paths. Exit 0. This does not execute them.

Owned standalone inventory (`shell_targets(owned(tracked()))`, 23 files),
same ShellCheck flags:

- Before this batch: exit 1, 185 findings, 19 files.
- After this batch: exit 1, 119 findings, 9 files.

```text
uv run pytest -q tests/test_shell_strict_regressions.py tests/test_wiki_editor_resolver.py
```

Exit 0. 18 passed. The wiki resolver run is the existing fake-command
fixture, not a live resolver install.

```text
uv run mypy --config-file quality/mypy.ini --strict --follow-imports=silent \
  --warn-unreachable --explicit-package-bases --disallow-any-explicit \
  --disallow-any-unimported --disallow-any-decorated --strict-equality-for-none \
  tests/test_shell_strict_regressions.py
```

Exit 0.

```text
uv run ruff check --config quality/ruff.toml tests/test_shell_strict_regressions.py
```

Exit 1. Two findings, both left visible: `INP001` because `tests/` has no
`__init__.py` (true of every existing test module; this batch does not add
one), and one `S603` at the single subprocess boundary that runs ShellCheck
and the fixtures. No `noqa` was added. `ruff format --check` for that file
exited 0.

Suppression scan of the ten scripts plus the new test: 0 hits.

## What changed

66 findings removed from these scripts:

| Script | Findings cleared | Preservation |
| --- | ---: | --- |
| `ansible/files/socrat-sudo` | 1 | `${PYTHONPATH:+:${PYTHONPATH}}` still omits the suffix when unset or empty. `-m socrat_sudo` and arguments stay. |
| `ansible/roles/debian_laptop/files/sway/homelab-sway-menu` | 2 | Unknown choices still exit 0. The new default arm is a no-op. A known entry still execs. |
| `ansible/roles/desktop_panel/files/paru_updates.sh` | 2 | Initial `0` stays. The count is still `wc -l`. `\|\| true` keeps the previous non-`errexit` continuation. |
| `ansible/roles/desktop_panel/files/pacman_updates.sh` | 2 | Same counter contract for `checkupdates`. |
| `ansible/roles/desktop_environment/files/layout-listener.sh` | 5 | Signal remains `-SIGRTMIN+5 waybar`. Comparison stays a quoted string test. |
| `ansible/roles/desktop_panel/files/battery-degradation.sh` | 6 | Awk program bytes are unchanged. No matching device still calls `upower -i` with no device argument. One device path is now one argument, including a path that contains a space. Fixture full/design 50/100 still prints `50`. |
| `ansible/roles/starship/files/arc_state.sh` | 7 | `arc` failure and an empty sequencer still exit 0 with no symbol. Unknown sequencer values still use the existing rebase symbol. |
| `services/spi-tokenizer/build-local.sh` | 17 | `CDPATH='' cd` is the same empty assignment as `CDPATH= cd`. `${1:?usage: build-local.sh /private/assets}` and `set -eu` stay. The script was not executed. |
| `ansible/roles/wiki_editor_client/files/wiki-editor-resolver.sh` | 20 | Braces only. Existing resolver fixtures passed. |
| `scripts/rustfs/deploy.sh` | 4 | Dirty, untracked, and ignored inputs still exit 2 before Helm. A wrong head still prints usage and exits 2. Short-circuit is preserved: dirty skips `ls-files`, untracked skips the ignored query, and a bad argc skips `rev-parse`. `dirname` failure stays ignored; `cd`/`pwd` failure still aborts under `set -euo pipefail`. |

## Remaining standalone findings (119)

| File | Count |
| --- | ---: |
| `ansible/roles/starship/files/arc-refresh.sh` | 25 |
| `ansible/roles/starship/files/arc_status.sh` | 23 |
| `ansible/roles/desktop_environment/files/caffeine-manager.sh` | 19 |
| `ansible/roles/desktop_panel/files/toggle_noscreenshare.sh` | 14 |
| `ansible/roles/starship/files/arc_metrics.sh` | 12 |
| `ansible/roles/starship/files/arc_dots.sh` | 11 |
| `scripts/nightnode/nightnode` | 7 |
| `charts/lms-database-ha/files/backup.sh` | 7 |
| `scripts/testing-class-wg-guard.sh` | 1 |

Rules still open: `SC2250` 82, `SC2292` 13, `SC2312` 12, `SC2310` 8,
`SC2249` 3, `SC1090` 1.

Not cleared, and not waived:

- `scripts/testing-class-wg-guard.sh` `SC2250` is the `$CHAIN` in
  `-A "$CHAIN" -j DROP`. `tests/test_socrat5_bootstrap.py` asserts that
  exact text. This batch does not edit that test.
- `scripts/nightnode/nightnode` `SC1090` is a non-constant `source`.
  ShellCheck's usual fix is a source directive. Directives are forbidden,
  and the path was not proven constant.
- `charts/lms-database-ha/files/backup.sh` is `SC2250` only. It was left
  for a later batch so this commit does not touch backup behavior.
- `SC2310` in `caffeine-manager.sh` and `nightnode` is a predicate/`set -e`
  interaction. Splitting those calls would change failure behavior, so
  they were not rewritten here.
- Four scripts were already clean and were not edited:
  `android/build.sh`, `scripts/lms-ha/copy-database.sh`,
  `scripts/rustfs/rollback.sh`, and
  `ansible/roles/desktop_environment/files/start-desktop-services.sh`.

Inline workflow ShellCheck remains outside this batch. A strict lint result
is not production acceptance.
