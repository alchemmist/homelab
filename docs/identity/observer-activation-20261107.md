# Observer activation checkpoint — 2026-11-07

**Not a completed human onboarding. Issue #105 remains open.**

## Delivered and checked

- Direct-main activation was explicitly requested. Commits `8818a42`, `2b03392`,
  `585fa16`, `aa29a67` and `cb8f63f` implement the bounded rollout. Concurrent main
  `c0a81c0` was merged normally; its private RustFS boundary was preserved, not
  reverted. Unrelated local monitoring work was not staged or discarded.
- Scoped local CI: **85 tests and 208 subtests passed**. GitHub scoped CI for
  `cb8f63f` succeeded: https://github.com/alchemmist/homelab/actions/runs/42419187186 .
  This is not a repository-wide test claim.
- Both targeted Helm renders passed server-side dry-run. At the last successful
  internal read Rancher, Wiki runtime and Argo CD were Synced/Healthy/Succeeded at
  `cb8f63f`. A consistent native Wiki auth SQLite backup was made before rollout;
  its articles/subjects/passwords were not rewritten by the membership hook.
- Legacy chat admission migrated to `homelab-chat-user`; existing human access and
  data were preserved. The native bootstrap applied safe Rancher new-user defaults,
  human session TTL and native group admission without changing human membership.
- A dedicated synthetic identity performed genuine native browser SSO/JIT in all
  five initially reviewed applications. Grafana was Viewer/not admin; Wiki reader;
  Harbor Guest/not admin in exactly the three declared projects. Rancher allowed
  nodes/namespaces/workloads and denied Secrets/ConfigMaps/RBAC reads. Its 23 native
  SelfSubjectAccessReview checks allowed the reviewed reads and denied logs,
  exec/attach/port-forward/proxy, infrastructure mutations, grants/escalation,
  impersonation, service-account token and extension token/kubeconfig creation.
- **Legacy `/v3/tokens` is an exception:** it returned 201 for a self-owned short
  test token. That token was ownership-checked and deleted (204). The profile no
  longer falsely promises that all self-credential minting is impossible.
- Removing only the synthetic observer principal from Rancher's native cache made
  the existing browser session lose nodes/namespaces/workload access (403). The
  automatic worker's actual remove/re-add and an old independent bearer key still
  need the final live round-trip; a scheduled CronJob is not acceptance evidence.
- After IdP group removal, existing Grafana auth returned 401; Wiki's native
  session returned no authenticated user/writable=false; refreshed Argo claims had
  no groups and its visible application list was empty. Public Wiki content remains
  public by design, not a revocation failure.

## Harbor was closed, not hand-waved green

A real existing synthetic CLI secret obtained registry `pull` after IdP observer
removal despite the five-minute OIDC access-token lifetime. Push/delete were not
granted. Native Guest is read-only but its revocation was not acceptable.

A fresh hash-approved bootstrap performed **exactly four deletes**: the owned
observer Guest membership in `homelab`, `library`, `spi-triage`, and this group's
Harbor admission binding. Owner, robots, unrelated members, native subjects and
passwords were not changed. Readback converged. A subsequent independent public
API check using the old synthetic session/CLI secret saw **zero projects** and
**no actions in a newly issued registry JWT**. Previously issued signed registry
JWTs are not retroactively revoked and can live for their original 30 minutes.
Harbor is explicitly unsupported/gated in the effective observer profile.

## Exact stop condition

During the final round-trip the approved internal SSH path failed to all four
pinned private node endpoints. A new SSH session timed out; an old mux connection
reported broken pipe. Corporate Tunnelblick remained connected. No VPN restart,
route/DNS/cache changes, public-SSH fallback or broad cluster recovery was tried.

The attempted synthetic re-admission did not connect/run. Its next native browser
login remained denied. **Danila's groups, password, MFA and native identity are
unchanged.** Do not treat the deployed configuration/readiness receipt as a
completed onboarding or a verified one-minute revocation SLA.

Once internal access is restored:

1. Read worker Job conditions/logs and the exact native state before any retry.
2. UUID/marker-check the synthetic identity; add only its observer membership.
   Prove the worker updates existing Rancher cache without any user/role creation.
3. Repeat the allow/deny matrix and create a short, self-owned read-only-scope key.
   Check native Wiki MCP-reader denial as well as browser authorization.
4. Remove the synthetic group. Prove old cookie/bearer/MCP credentials lose the
   intended authorization, new login is denied and native re-add works. Clean up
   only the synthetic credentials/account; preserve real humans and machine keys.
5. Only then UUID-check Danila, add observer, remove the erroneous IdP Read-only
   membership, retain the separately approved NetBird membership, and read back.
6. Record final acceptance and update the runbook. Harbor requires a separate
   bounded native revocation solution/acceptance before any observer reopening.

Private receipts/credentials remain on the operator node under
`/var/lib/homelab-observer-rollout/20261107-final` and the guarded bootstrap state
folders, with local browser evidence under the private operator scratch directory.
No credential values are present in this document or Git.
