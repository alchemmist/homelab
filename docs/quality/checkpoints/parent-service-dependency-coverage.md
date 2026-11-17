# Current-main tests and dependency admission coverage

Merged fetched main ffb11bb634fa359cd45a4ac66c0697b3cf550cdd in139fbe42,
including the owner-added swe-mini service, chart and queue regression modules.
No service, autonomous agent, provider-backed acceptance, provisioning script or
selftest was executed. The provider/model and financial/runtime authorizations
of the source-only quality mission are unchanged.

## Reviewed offline test classification

Both new tests/swe_mini modules explicitly join fast, after complete source and
controller import/tick-path inspection. JWT, HTTP and Kubernetes boundaries are
mocked; SQLite state is :memory:. Parent additionally patches controller.github
with a refusal before its credential-file/API implementation can execute, with
unittest cleanup restoring the original callback. All original19cases and12
subtests pass. No real operator credentials, queue state or Kubernetes were used.

## Actual dependency coverage defect repaired

The former dependency collector audited only installed quality-venv packages.
It did not cover services/swe-mini/requirements.txt, and its zero vulnerabilities
was NOT acceptance of this service. Owned Node dependency metadata was likewise
not audited. The gap must block admission, not remain an undocumented green.

- Installed environment now requires pip-audit --strict.
- Every owned requirements.txt/requirements-*.txt lock is audited independently
  using --strict --disable-pip --no-deps --require-hashes. This checks the complete
  pinned, hashed closure without installing anything or invoking package code.
- Before handing any source lock to a tool, bounded source inspection rejects
  includes, alternate indexes, direct references, unsafe paths and symlinks.
  Only exact pins, SHA256 entries, markers, comments and continuation syntax are
  supported. pip-audit itself additionally enforces hashes on every requirement.
- Empty, malformed or skipped audit data and exit/report contradictions refuse
  admission. Same advisory in distinct files or versions remains distinct.
  Only repeated identical (package, version, advisory-ID) entries in one report
  are consolidated; no finding/description truncation or admission-cap changes.
- Other owned lock ecosystems currently emit DEPENDENCY_LOCK_UNAUDITED, and
  unpaired dependency declarations emit DEPENDENCY_LOCK_MISSING. These are OPEN,
  BLOCKING coverage findings, not vulnerability claims or accepted debt.
  The official-MCP Node lock still requires a real supported auditor; nothing
  in this checkpoint claims that implementation is finished.

Real expanded collection:169distributions (71quality +98service),29distinct
service vulnerability findings plus1official-MCP coverage finding =30blocking.
The complete preliminary service tool output has41raw advisory entries; repeated
identical triples account for the difference. Raw preliminary output and complete
expanded findings are private, not committed. No package/image version was
changed or advisory suppressed to achieve a number.

New24offline dependency regressions are explicitly fast-scheduled and pass.
They cover complete source attribution, exit/report binding, duplicate versus
version distinctions, incomplete/malformed/skipped protocols, unsafe requirement
directives, symlinks, missing locks and unsupported ecosystem refusal. The new
module is Ruff ALL/formatter/strict-mypy clean. All six new typed collector helpers
have zero Ruff/mypy findings; existing lint.py debt remains genuinely blocking.
AST comparison proves every original linter function and non-dependency branch
unchanged apart from formatting/import ordering. No other scanner was relaxed.

Exact committed-head whole-suite/audit evidence follows separately. Prior
ba969f65 counts and predecessor hosted results are not current-head acceptance.
PR182 must remain draft/red; neither this checkpoint nor Kind implies production,
backup/restore, autonomous-service, sustained-memory, HA or DR acceptance.
