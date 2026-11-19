# PR182 integration contract: refactoring + strict CI enablement

## Latest operator decision

The operator explicitly changed this PR's goal from zero findings before integration to reviewed refactoring plus strict CI setup. Existing defects are follow-up work on main-based PRs. The owner is prepared to consider a red-CI merge/bypass separately. This supersedes the former source-green prerequisite for preparing this integration, not the enforcement policy. It does NOT execute a merge/admin bypass, approve findings, remove checks, reset baselines, refresh secret/DNS approvals or authorize production operations.

## Preparation checklist

- Preserve local reviewed commits and synchronize current owner main, including versions/identities and owner source behavior. Review the delta against main, not merely the number of merged files. Do not restore stale image/version/model pins.
- Resolve the former PR-Agent governance conflict by actual current main source: auto push handling is true and `/review -i` is configured. Preserve the saved `/review` assertion, add exact env checks and negative disabled/empty push cases. No manual-only migration or direct model invocation.
- Keep all15semantic nodes, blocking policies and approval prohibitions. Validate generated freshness and strict configuration; do not hand-edit generated workflows.
- Preserve all previously scheduled tests/assertions. Review/classify new modules; never silently discover/import provisioning/autonomy code. Unknown inventory is an integration defect, not deferred lint debt.
- Register exact new ownership/issuer consumers with drift negatives. The OpenHands OIDC hostAlias is one scoped existing verified-TLS issuer route, not new DNS/authentication policy; prior9consumers and all old registry fields remain exact. Count equalities increase only for this additive consumer; IP/scope mutation cases must actually mutate and refuse.
- Run actual fast/medium/contracts/guard/graph and immutable audit on the committed candidate. Report failures without weakening assertions. Retain native report/hosted acceptance limits separately.
- Publish only through the fail-closed draft publisher, then update PR scope/evidence/known failures. A fresh main ancestry refusal means hold, not push anyway. Historical validated local tests are not current published-head hosted success.

## Source and CI-infrastructure follow-ups are distinct

Source/style/type/dependency/manifests failures may remain red under the changed integration goal. Post-merge work should use homogeneous reviewed batches, not another indefinitely accumulating branch. No baselines/automatic approvals hide the old defects.

Two important CI-infrastructure limitations remain explicit: full native Python admission previously failed the unchanged10MiB limit; pinned upstream compiler publisher triggers/permission documentation still produce security findings and cannot be repaired by hand-editing generated output. Tool coverage is not universal: JavaScript is syntax-only and some test modules are explicitly not scheduled. These are open follow-ups/decision points, never claimed complete or green. The owner must see them when deciding red integration.

## Safety and evidence

Work only in the approved continuation worktree. Other checkouts are untouched. Operational scripts, provider/model/worker loops, credentials/helpers, live kubeconfig, SSH/Kubernetes/Ansible maintenance, backup/restore and identity/DNS execution are not authorized. New main backup/autonomy source can be preserved verbatim without running it. Offline tests use private fixtures/fake API calls/local Helm rendering, never apply Jobs or start services.

Private evidence: `ci-enablement-scope-sync/` contains initial PR body, incoming/local inventory, original owner files, format-only conflict list, resolution decisions, exact additive issuer proof and scoped diagnostics. Full source/head-bound results and publication journal are stored under the existing private quality-strict root. Do not publish raw sensitive findings. Historical checkpoints remain historical receipts; current README and exact-head PR evidence take precedence over obsolete counts/rationales.
