# Second reviewed integration: real fixes, unchanged admission limits

Reviewed worker source integrated as1226dd6f(pytest),8edb5ea0(YAML),339f8e43(shell).
The shell worker's extra one-line bootstrap test change was explicitly reviewed:
it preserved the same final DROP assertion after bracing CHAIN, not a new scope
exemption. Parent then found and repaired an older formatting-sensitive CAS test:
it now requires the real SHA256 preimage assertion in main, the exact targeted
wg-set argument AST and preservation of remaining peer state. Replacing the CAS
assertion with True, or a comment decoy, is rejected. No admission script was run.
The now-reviewed bootstrap module is scheduled in fast. New synthetic shell tests
are scheduled in medium. Contracts:121/278modules scheduled,157deferred.

Independent parent yaml.compose(SafeLoader) graph fingerprints for all16edited
values documents preserve tags, scalar values, mapping order and alias references.
No image/version/CIDR/resource quantity decoded value was changed. Worker counts:
87quoted-string findings fixed, every other YAML rule count unchanged in scope.

The eight pytest modules retain58tests/60subtests, with340to182Ruff findings in
that exact partition. No negative scenario, failure class or output-leak check
was dropped. Their remaining typing/documentation and security-boundary findings
remain blocking. No claim of global Python cleanliness is made.

Second standalone shell batch fixes111of112in its ownership;23-file inventory
now has8remaining findings: dynamic nightnode source SC1090 and7SC2250in the
untouched backup script. The dynamic config API was not replaced with a fake
static source. No suppression or rule-budget change was added. Backup sources,
implementation, schedules, data and operations were not changed.

Parent combined targeted validation:78passed,60subtests. strict_guard:0inline
suppressions. qg/contracts validation remains required at the final exact HEAD.
Full strict findings must be remeasured, not inferred by subtracting lane totals.

## Restored environment evidence

Old /tmp checkout disappeared, but committed507dda89and Git history survived.
Parent recovered that commit into a new persistent isolated worktree without
reset/prune or modifications to the primary working tree. UV locked tools were
restored. One bounded download timed out; a same-version/checksum promtool retry
succeeded. Completed old fast evidence:691passed/1skip. Fresh507dda89medium:
285passed/5existing skips/1failure. The failure is the actual Docker prerequisite:
local Podman socket missing. No hidden daemon-availability skip was added, no
host provider/systemd/network was changed, and medium is not labelled green.

## Native protocol limits: primary-source research

Locked quality-graph0.2.0 has hard10MiB producer-input and10000-findings limits;
there is no supported per-node budget. The read byte cap fires before the finding
cardinality check. Publisher zip20MiB/uncompressed50MiB limits are different later
checks, not a way around the producer schema. Current upstream examined by the
research worker has the same limits. Compact ea6a5e0dJSON still exceeds10MiB and
42662findings exceed10000. No identifiers/messages/findings were omitted, shortened
or silently sharded to obtain admission. A protocol release/pin would require
separate review and would only admit a still-failing quality result; it would not
make source green. Current work continues repairing actual source findings.

No merge/main promotion, production/SSH/VPN/identity execution, new credentials,
backup/restore or public Wiki operation was performed.
