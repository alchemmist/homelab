# Parent continuation checkpoint: source boundaries and evidence integrity

This is a partial strict cleanup, not global lint acceptance. No production,
identity reconciliation, VPN, financial synchronization, backup/restore or public
Wiki operation was performed. No source was pushed to main.

## Concrete source changes

- `8fef93ca`: Authentik's bootstrap prerequisite checks the actual reviewed AST
  recipe, journal/token refusal, both administrative credential removals and use
  of the filtered map before manifest construction. Comments/strings cannot
  satisfy it. Genuine negative mutations are rejected. Other source contracts
  tolerate equivalent quote/layout changes without removing security scenarios.
- `80ebf48f`: exactly17preexisting frozen SPI compatibility files are verified
  against the existing manifest and bytes before ownership exclusion. The entire
  directory is not excluded; new neighbours remain owned. No original manifest
  or source checksum was refreshed. Secrets scanning still covers all tracked
  files. See [frozen inputs](../frozen-inputs.md).
- `213e1a18`: PyYAML stubs are exactly pinned and locked instead of ignoring an
  untyped dependency. Dependency audit checked71installed targets with0findings.
- `5b3e59cf`:576YAML files received explicit document framing only after equality
  of composed tags, scalar values, mapping order, structure and alias sharing.
  The alert-graph **generator** was updated to own its generated framing; ledger,
  inventory and30dashboard JSON files stayed byte-identical. A fixture now
  inserts additional fields before the actual document-end token.
- `6ec1ab07`: merged current main, including the separately owned SPI release and
  n8n transport changes. Neither was reverted to manufacture a passing test.
- `1a23de74`: the historically malformed Grafana preparation writer is a tiny
  executable refusal-only entrypoint. It imports only sys, reads no credentials,
  does not forward execution and exits2. All-rule Ruff and strict mypy passed for
  that script. Four actual CLI cases refused with empty stdout and unchanged
  synthetic sentinel files. AST/capability and negative-mutation tests cover it.

The historical migration comparison keeps its original BASE and all existing
assertions. Only the before-render receives the current SPI image inputs from the
canonical application profile. This separates a later legitimate release from a
placement change; it does not normalize away current image/template deviations.
Four actual rendered mutations (wrong image, UI placement, UI environment, extra
claim) were still rejected. No application image was changed by that test repair.

## Report integrity

Each full audit now has a new commit-labelled UUID directory beneath the private
`quality-strict/runs/` directory. Both boundaries must have the same clean source
commit. A dirty tree or mid-run commit is incomplete evidence, not success.
The latest index starts explicitly incomplete before collection. Interruptions
cannot leave a previous clean index posing as a finished current audit.

Evidence files are atomically published from initially0600temporary files;
private run directories are0700. Symlink destinations/directories are rejected
before touching targets. A failed suppression/provenance scan is caught and
recorded as a tool failure while other diagnostic collectors still run. Logging
never emits arbitrary exception values. Fault-injection tests cover dirty input,
commit races, collector/configuration failure, interrupted collection, separate
reruns, permissions and symlink refusal. Reads of current detailed evidence must
follow `summary.json`'s `evidenceDirectory`; legacy top-level JSONL files are not
implicitly current. A complete collection is not clean source or hosted artifact
admission.

Two earlier YAML-disable rationales were wrong and removed: empty-value checks do
not reject `{}`, and quote checks do not demand coercing booleans/numbers into
strings. Both rules now block violations. Real pinned-tool stdin tests preserve
least-privilege empty permissions and typed values while rejecting implicit nulls
and unnecessary/inconsistent quotes. Further key-ordering scope, remaining
Ansible policy boundaries and missing stack-specific checks still need review.

## Actual evidence and remaining work

- Curated fast after these repairs:641passed,1existing fixture skip,329subtests.
- Curated medium:274passed,5existing platform skips,313subtests.
- strict_guard:0inline suppressions; qg validate and25offline schemas passed.
- Private logs: parent-final-fast.txt, parent-final-medium.txt,
  parent-stateful-boundary-mutations.json and parent-yaml-markers.json.
- The complete audit at **6ec1ab07**, before the later evidence/YAML-policy changes,
  measured48815blocking findings, configurationReady=true, sourceClean=false,
  with no command blockers. That is historical, not the final/current count.
- Five scanner findings at that audit were existing reviewed public keys, native
  object UUIDs or prose contexts. Their Python ASTs were unchanged from3ea04fa4;
  formatting invalidated old exact-context IDs. They remain blocking. No new
  approvals, registry entries or baseline refresh were made.
- Strict helper typing/import contexts and large owned-code lint partitions remain
  unfinished. The report helper itself still has actual typing findings; its new
  evidence safeguards do not imply that helper/package lint is fully clean.
- No current-head hosted aggregate,15-artifact admission, Kind acceptance or
  production acceptance is claimed. PR182must remain an honestly labelled draft.

The next actual full report must be read at its exact recorded HEAD, not inferred
from this checkpoint or from earlier green PR181. New rules may reveal more
findings; a changed count under stronger policy is not a same-policy benchmark.
