# Native observer — accepted 2026-11-08

Canonical runbook: [observer profile](../docs/identity/observer-profile.md).
Live evidence: [accepted rollout](../docs/identity/observer-acceptance-20261108.md).

- Effective `homelab-observer` scope is **Rancher, Grafana, Wiki, Argo CD**.
  Add the IdP group; native SSO/JIT resolves local accounts/roles. No future
  per-human Rancher bindings, account mappings, SQL edits or provisioning daemon.
- Danila's UUID-guarded initial correction is complete: observer added, erroneous
  IdP Read-only removed, approved NetBird membership preserved. No password/MFA
  writes, human impersonation or native human account provisioning was performed.
- Existing owner/editor/direct privileges are additive and preserved; observer
  cannot downgrade an already privileged account. NetBird admission is separate.
- Rancher legacy `/v3/tokens` can mint self credentials despite denied extension
  token/kubeconfig API permissions. Do not claim universal mint denial. Actual
  old-cookie/live-bearer reads were denied after the native group cache removal.
- The minute worker updates only existing native observer membership cache entries.
  A legacy cache-less orphan must not block unrelated viewers, but a mismatched
  cache carrying observer privilege stops safely. It never provisions users/roles.
  Dedicated IdP machine token has only user/group view permissions. Native worker
  failures/missing success and missing worker have Prometheus rules.
- Wiki's native reader cookie/MCP checks current IdP admission, <=60s cached,
  fail closed; owner/editor/unlinked machine identities are not rewritten.
- Grafana groups/roles are explicit, missing groups have no Viewer fallback,
  native browser token rotation is one minute. Argo default is unprivileged;
  live Secret data redaction and negative sync were tested.
- Revocation is not a universal instant-logout SLA: native OAuth/JWT caches have
  independent expiry; worker availability matters. The acceptance records actual
  cookie/bearer/MCP/new-login behavior and successful automatic remove/re-add.
- **Harbor stays gated** after real CLI revocation failed. Its observer admission
  and three owned Guest grants were removed. Do not recreate them from an old
  bootstrap assumption/readiness receipt. Native fix/reacceptance: issue #134.
  Owner, robots and unrelated project memberships are untouched.
- Temporary synthetic identity was disabled and removed from observer; its own
  test keys and Rancher sessions were removed, and its native cache cleared.
- Scoped CI: 89 tests +208 subtests, not repository-wide or independent approval.
  All four nodes Ready, the four apps Synced/Healthy, both revocation alerts loaded
  and healthy at closeout. Unrelated local monitoring work remains unstaged.
