# Parallel 56 lane 47 — ethernet guard mode quotes

Managed worktree base `3274cb0628152046185f8f4f5488391bfd52d3ed` on
`pi-subagents/p56-47-8ba26af-b958-s0-t0`. Requested parent
`03bb16146e5d23ddb083aa170bdce1cc18c779d6` is an ancestor. The worktree was
not reset or rebased.

One quote repair: `ansible/roles/debian_laptop/tasks/ethernet_guard.yml`
`mode` changed from single quotes to double quotes. The scalar stays the
string `0700`. No playbook was executed. No version, digest, identity, or
generated output was edited.

## Why the quotes stay

Pinned PyYAML 6.0.3 `safe_load` constructs plain `0700` as integer `448`
(`tag:yaml.org,2002:int`). Both `'0700'` and `"0700"` construct as the
string `0700` (`tag:yaml.org,2002:str`). `quality/yamllint.yaml`
`quoted-strings` is `quote-type: double`, `required: only-when-needed`, so
the single-quoted form was the one finding on this file.

## Graph proof

`yaml.compose_all` with the default `Loader` and with `SafeLoader` agreed
before and after. One document. Signature equality held for tags, scalar
values, mapping and sequence order. Alias hits 0 and 55 unique nodes on both
sides. The only style change is scalar index 18: tag
`tag:yaml.org,2002:str`, value `0700`, style `'` to `"`. Two bytes changed,
both quote characters. `safe_load` of the whole file compared equal, and the
template `mode` remained a `str`.

## Pinned yamllint

Tool: parent `.venv/bin/yamllint` 1.38.0, config `quality/yamllint.yaml`,
worker cwd. `yamllint --version` exit 0.

Lane command before and after: `yamllint --format parsable --config-file
quality/yamllint.yaml` on the 54 allocated files, `subprocess.run(check=False)`.

| | Exit | Findings | quoted-strings |
| --- | ---: | ---: | ---: |
| Before | 1 | 610 | 215 |
| After | 1 | 609 | 214 |

Unchanged: `line-length` 180, `indentation` 178, `braces` 30,
`document-end` 5, `document-start` 2. The edited file alone exits 0 with 0
findings. No scheduled offline test covers this file.

## Remaining

609 lane findings remain on the other allocated files. This commit does not
clear them.
