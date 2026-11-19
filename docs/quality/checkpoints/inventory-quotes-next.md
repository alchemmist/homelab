# Inventory quoted-strings checkpoint — owned Ansible inventory

This is not a clean YAML tree. Twelve owned `ansible/inventory/**/*.yml`
files were linted with the locked yamllint. Four of them had nine string
scalars rewritten to the strict `quoted-strings` form: bare when a plain
scalar stays a string, double quotes when the quotes are what keep the
scalar a string. One Jinja template scalar and two SSH public-key scalars
stayed quoted. No yamllint disable, file ignore, debt approval, or policy
change was added. Those paths stay in the owned lint set. No Ansible,
SSH, provisioning, production, backup, VPN, or operator-config command
was run.

Rule in force, unchanged: `quality/yamllint.yaml` `quoted-strings` with
`quote-type: double`, `required: only-when-needed`, `check-keys: false`,
`allow-quoted-quotes: false`. Tool pin: `yamllint==1.38.0`, `pyyaml==6.0.3`.
`uv sync --locked` created the project environment that supplied those pins.

## Inventory

Plain files are the twelve `ansible/inventory/**/*.yml` paths. There are no
`.yaml` files in that tree. `owned()` keeps all twelve: none are under the
vendor prefixes and none are in the seventeen frozen `charts/spi-triage/files/*.py`
inputs. The frozen manifest check passed before ownership was decided.
This batch does not expand ownership past inventory YAML plus this checkpoint.

Seven owned files had zero `quoted-strings` findings and were not edited:
`direct.yml`, `hosts.yml`, `lan.yml`, `host_vars/socrat-0.yml`,
`host_vars/socrat-3.yml`, `host_vars/socrat-4.yml`, and `host_vars/socrat-5.yml`.
Other yamllint rules on those files were left as they are. `group_vars/all.yml`
had one finding and was not edited.

## Commands and exits

```text
uv run yamllint --version
```

Exit 0. `yamllint 1.38.0`.

```text
uv run yamllint --format parsable --config-file quality/yamllint.yaml ansible/inventory
```

Before this batch, exit 1. 23 findings:

| Rule | Count |
| --- | ---: |
| quoted-strings | 12 |
| indentation | 7 |
| line-length | 4 |

The same command after the edits, exit 1. 14 findings. `quoted-strings` fell
from 12 to 3. `indentation` stayed 7 and `line-length` stayed 4. No finding
was added and no other rule appeared.

The NetBird `ansible_ssh_common_args` line went from 175 characters to 173
and is still over the limit of 100, so that `line-length` finding remains.
The `socrat-1.yml` bind line stayed 101 characters. The other two
`line-length` lines were not edited.

`quoted-strings` before, 12 across 5 files:

| File | Before | After | Edited scalars |
| --- | ---: | ---: | ---: |
| `ansible/inventory/group_vars/Socrat.yml` | 3 | 2 | 1 double |
| `ansible/inventory/group_vars/all.yml` | 1 | 1 | 0 |
| `ansible/inventory/host_vars/socrat-1.yml` | 5 | 0 | 5 double |
| `ansible/inventory/host_vars/socrat-2.yml` | 2 | 0 | 2 plain |
| `ansible/inventory/netbird-controller.yml` | 1 | 0 | 1 plain |

Nine scalars changed: six single-quoted strings rewritten with double quotes,
three redundant double quotes removed. Three `quoted-strings` findings remain,
all on unedited tokens.

Graph proof, before each file write and again on the bytes just written,
exit 0. For every edited file, `yaml.compose` over the whole document stream
with the default Loader and with `Loader=yaml.SafeLoader` produced the same
signature before and after: node tags, scalar values, mapping and sequence
order, and alias sharing. None of these four documents had an alias node
(shared-node count 0 on both sides). The two loaders agreed with each other
before and after. `yaml.unsafe_load` was not called. Compose only builds the
node graph.

An independent compare of `HEAD` against the written files repeated that
check and walked every scalar. The only differences were string-scalar
styles, and the style-change counts match the table above: one `' -> "`
in `Socrat.yml`, five in `socrat-1.yml`, and three `" -> plain` across
`socrat-2.yml` and `netbird-controller.yml`. Failures: 0.

```text
uv run pytest -q tests/test_netbird_node_ansible.py tests/test_identity_ssh.py \
  tests/test_socrat5_bootstrap.py tests/test_socrat5_worker.py tests/test_inventory.py \
  tests/test_vpn_transit.py::test_private_authoritative_listener_and_tcp_certificate_identity_preserved \
  tests/test_vpn_transit.py::test_public_key_inventory_has_no_private_material \
  tests/test_vpn_transit.py::test_small_worker_keeps_admission_and_has_no_control_plane_role \
  tests/test_vpn_transit_failover.py::test_machine_https_exception_is_exact_not_a_human_acl_relaxation
```

Exit 0. 52 passed, 39 subtests passed. These load the edited inventory or
assert the parsed listener, passthrough, and public-key values. They are not
an Ansible run and not a production check.

A wider pytest of `tests/test_vpn_transit.py` and
`tests/test_vpn_transit_failover.py` also reported four failures in unmodified
playbook, script, and chart assertions. Those files are outside this diff.
They were not edited and are not claimed as fixed.

## What the edits kept

Each replacement was the scalar token only. Keys, comments, block scalars,
document markers, anchors, and neighboring tokens were not rewritten.

Plain scalars were used only where yamllint called the quotes redundant and
the compose tag stayed `tag:yaml.org,2002:str` with the same value. That is
the two flow-sequence address strings in `socrat-2.yml` and the NetBird SSH
argument string. Parsed text is unchanged, including the listener address and
the passthrough source.

Double quotes replaced single quotes where dropping the quotes would change
the tag or the scalar text. The peer endpoint `socrat-1` stays an empty
string, not null. `_JAVA_AWT_WM_NONREPARENTING` stays the string `1` and
`XCURSOR_SIZE` stays the string `24`, not integers. The three Hyprland bind
scalars keep their trailing space and their `#` text; only the quote
character changed.

## Left unedited on purpose

- `ansible/inventory/group_vars/all.yml:3` is the Jinja template scalar
  `"/home/{{ homelab_user }}"`. Template scalars were not edited. One
  `quoted-strings` finding remains.
- `ansible/inventory/group_vars/Socrat.yml:77` and `:78` are SSH public-key
  strings. Public-key tokens were not edited. Two `quoted-strings` findings
  remain. The WireGuard `public_key` lines in that file were not findings
  and were not edited.
- `ansible/inventory/host_vars/socrat-1.yml` contains
  `homelab_boot_wifi_uuid`. That UUID scalar was not a `quoted-strings`
  finding and was not edited.
- Reviewed public-key and UUID false-positive paths stay outside this batch:
  `scripts/socrat-edge-peer.py`, `scripts/wg-testing-class-admit.py`,
  `scripts/retire-tv-internal-wireguard.py`, and
  `scripts/rustfs/unified_identity.py`. `quality/secret-false-positives.json`
  is byte-identical
  (`f0adf5e9ed7cbb4c0315d51c014aa019e7ff9320e9d7bf4ae8ef01ef6058c1fd`).
  No false-positive id was added, removed, or rewritten.

No candidate was dropped because compose disagreed. The three skips above
were excluded before replacement. Indentation findings were not quote edits
and were left in place.

A strict lint result is not production acceptance. 14 findings remain on
`ansible/inventory`, including the 3 `quoted-strings` findings above.
