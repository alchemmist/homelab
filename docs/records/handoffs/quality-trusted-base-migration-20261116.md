# Trusted-base registration for the semantic quality DAG

The full replacement graph's15workers passed in PR181 atb7a2e28c, run43956764998.
The native aggregate correctly refused admission because the previous trusted
base declaration required a different graph. This is not a test failure waiver.

This registration commit contains ONLY the declaration/generated CI metadata and
this explanation. It registers the reviewed PR graph with exact commands,
profiles, needs, result adapters and fail-closed policies. A local comparison of
`pr_contract(project_graph(..., 'pull-request'))` proves equality with the tested
PR declaration. No branch protection, approval escape or provider security check
is disabled. No artifacts are re-labelled or fabricated.

For base pushes, the original seven bootstrap checks remain executable under
separate bootstrap profiles. New PR-only checks do not invoke helper files that
are not yet merged. Source changes to applications/test implementations remain
in PR181 for review; they are not pulled onto main just to clear the aggregate.

The final PR declaration has the new15-node DAG for both PR and push. Once that
PR is accepted normally, it naturally replaces this temporary base registration
and the legacy push-only bootstrap nodes, with its actual implementation present.
No application maintenance, data/identity operation, backup implementation or
forced reconciliation is part of this registration.
