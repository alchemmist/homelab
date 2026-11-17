# Operator-authorized fifty-six granular Grok repair lanes

The operator explicitly requested50–60Grok4.7subagents. This is a NEW56lane
allocation of current remaining source findings at72419ef6, not a retry or
resurrection of completed prior runs. Read AGENTS.md, llm-wiki/context.md,
docs/quality/strict-mission.md, relevant runbooks and the full mandatory safety,
semantic and evidence contract in docs/quality/parallel-24-mission.md. Those
restrictions still apply. The updated parent cwd is the persistent isolated
homelab-quality-strict-continuation worktree, never the primary checkout.

## Exclusive ownership and bounded progress

Read ONLY your numbered lane in the private allocation JSON supplied in your
task. Files are disjoint across all56lanes. The allocation grants an upper bound,
NOT a demand to finish dozens of files at once: begin with ONE small coherent
repair, finish edit/check/test/COMMIT, then another if safe. Do not spend the run
writing intentions. A completed label with no diff/commit is NOT repair.

Only edit your allocated existing files, optional uniquely named new regression
file tests/test_quality_p56_NN_*.py and optional checkpoint
 docs/quality/checkpoints/parallel56-NN.md (NN=two-digit lane). Parent alone owns
suite registration/import-package architecture. No new __init__ files. Cross-lane
producer/consumer changes require reporting to the parent, not scope expansion.
No recursive delegation, push, merge, force/reset, other worktrees or global
configuration changes. One managed isolated writer per worktree.

## Tools and acceptance

Worktrees do NOT have their own .venv. Use the parent's READ-ONLY pinned tools:
 /Users/antonmoss/code/worktrees/homelab-quality-strict-continuation/.venv/bin/
 python, ruff, mypy; prepend that directory and the parent's .quality-tools/bin
 to PATH for inspected offline tests. Run tools with your worker cwd, NEVER the
parent cwd. Use your local quality/ruff.toml and quality/mypy.ini. No installation,
package/version/image changes, missing-import suppression, Any/cast/getattr tricks,
noqa/ignores, baseline/approval changes or formatter-only success claims.

Native lint exit1is genuine diagnostic data, not a reason to abandon edits:
capture it with subprocess.run(check=False), preserve actual exit status and
before/after counts. A tool/provider/launch/configuration failure must stop and
be reported; no alternate CLI/model/global edits/purchase or automatic retry.
Read tests before execution. Only demonstrably offline scheduled tests, or new
isolated synthetic regression tests, are authorized. Unscheduled tests receive
static analysis unless their side-effect safety is established and reported.
Never execute operational entrypoints, credentials/helpers, deployment scripts,
autonomous/model/provider-backed loops, production SSH/Kubernetes/Ansible, VPN,
identity, backup/archive/restore, finance, public callbacks or public Wiki actions.

Every original assertion/scenario/subtest and real native check remains. Compare
complete fixtures and executable ASTs after explicit annotation/docstring/assertion
normalization; YAML fixes need complete composed graph/scalar-tag/alias-sharing
identity. No string/variable indirection solely to evade scanners. Retain CLI
bytes, public parameter/default/positional behavior, runtime invalid-provider
rejection, refusal-before-effects, ownership/locking and existing-data safeguards.
Frozen inputs, source pointers, panel ledgers, dashboard bytes, secret-reviewed
contexts, data paths, identities, TLS/SSO/PKCE, ACLs and versions stay preserved.

## Special lanes

- Python tests: improve concrete fixtures, real signatures/docstrings and equivalent
  assertions. Do not replace equality/count checks with weaker sets or drop cases.
- Python sources: only source repairs with proved behavior/API preservation. Never
  execute the operational script to validate it; use static proofs and fake bounds.
- YAML: quotes/framing only with composed graph and alias/scalar-tag comparison.
  Generated outputs with non-owned producers must be reported, not hand-edited.
- Ansible: source-only lint/semantic checks; never ansible-playbook execution.
- Shell: preserve arbitrary source/config semantics; no disable directives or hidden
  source fallbacks. Report a precise rule conflict if no safe repair exists.
- Workflow: preserve15semantic DAG nodes, all retained coverage, strict acceptance
  and least permissions. Never manually edit generated Quality Graph workflows.
  swe-mini-release.yml is a separate owning source; no release/dispatch execution.
- Dependency auditor: implement genuine safe Node lock auditing if feasible within
  scripts/quality/lint.py, with new offline protocol/boundary tests. No npm install,
  lifecycle scripts, auth/config/credential reads, dependency upgrades, suppressions
  or weakening Python audit/exit binding. Keep unsupported ecosystems BLOCKING
  until actually audited. Do not count placeholder findings as implementation.

## Durable deliverable

Actually COMMIT coherent source changes in your own managed worktree. Return:
commit hash; exact files; real commands/exit codes and before/after finding counts;
inspected offline tests/results; behavior-preservation proof; remaining blockers.
Keep raw evidence outside Git in a unique private0700directory with0600files;
never print credential values or payloads. No raw source-finding dumps in Git.
Parent independently inspects every patch, validates/integrates compatible commits,
runs exact-head complete suites/audit/native CI and keeps PR182 draft until green.
Native report limits are never solved by truncation, hidden sharding or promotion.
