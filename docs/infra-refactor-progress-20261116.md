# Infrastructure refactoring: implementation checkpoint —16 November 2026

This is a progress record, not a declaration that every infrastructure/security
risk is closed. Original scope: `refactoring-audit-20261116.md`. Production changes
limited to authorized Grafana/Grafana MCP move and Git-owned annotation/dashboard
refresh. Independent monitoring/VPN topology, credentials and app versions retained.

| Area | Implemented and verified | Still open |
|---|---|---|
| R1 Argo ownership | Canonical values + compatibility symlink; explicit empty-bootstrap opt-in, existing workload refusal, install not upgrade; offline regressions | Fresh empty-cluster rehearsal/complete DR not performed |
| R2 issuer transport | One canonical registered route,9consumers; comment-preserving offline regeneration, scoped hostnames/TLS retained; drift tests | Future Service recreation still requires live owner/IP/path validation, not blind generation |
| R3 topology | Mesh/inventory membership/address checks; fixed relay/updater constants checked against mesh/hostvars/peer identity, no relay execution/restart | Remaining address literals/policies/scripts need subsystem-by-subsystem review; intentional recovery pins retained |
| R4 current/history docs | Short current context, former1255lines preserved in separate historical file; canonical Argo links, Wiki claim, Grafana/SPI checkpoint banners and inventory scope corrected | Not every historical statement rewritten; do not treat old dated receipts as current |
| R5 public Wiki | Source README claim corrected; runtime authority and no-concurrent-writer rules preserved | Two public pages checked200; obsolete gated text confirmed. Targeted proposal prepared; native write-scoped Wiki connection unavailable in this session, no publication claimed |
| R6 backup coverage | Actual n8n latest paired archive SHA and independent SQLite restore integrity checked on socrat-3, source socrat-5; Grafana independent cold archive+exact restore | Recurring consistent backups for remaining moved datasets, retention/unpaired archive review, full VM restore/cold boot remain OPEN |
| R7 operational tools | Lifecycle table; active read-only ownership/generation-aware placement CLI and false-positive regressions; append-only alert graph IDs | Not a blanket certification/rewrite of every script or every vendored dependency |
| R8 CI | Locked PyYAML; pinned Helm setup; explicit offline suite wired into generated Quality Graph; real GitHub run850077b8 succeeded | 39targeted offline tests, not exhaustive security/DR acceptance |
| Added Grafana scope | Grafana and MCP accepted socrat-5; exact images/UIDs/container specs, full cold restore, identities/ACL/Secrets, native auth and real query | Grafana recurring backup and owner-led final OIDC callback remain separate from native redirect acceptance |

## Additional real defects corrected, not suppressed

- SPI execution-link CI asserted the old deferred-code list. Existing producer/
  consumer and storage-wait runbook already permit STORAGE_TRANSIENT only at
  Publish. Test updated to that contract and now asserts the Publish-only guard;
  production workflow/source was not changed or executed.
- Alert graph generation was stale. Simply regenerating would have shifted
  historical panel links after an alphabetically earlier new alert. Introduced
  append-only panel-ID ledger seeded from accepted dashboards; old IDs preserved,
  new rule gets new pair, removed IDs never reused. Conditions/routing unchanged.
- Placement verification rejects replica0/old Ready Pods/stale generation and
  checks actual Deployment→ReplicaSet→Pod ownership. A superficial rollout status
  is not migration acceptance.
- Inventory README's old `Socrat:!socrat-3` example no longer meant only
  socrat-0/socrat-1/socrat-2 after adding nodes. Replaced by explicit three-host
  selection; removed obsolete four-node counts and index-derived public SSH claim.

## Continuation: owner deferred backups

The owner explicitly requested continuing the refactoring **without making
backups for now**. Backup implementation/restore work below is deferred, not a
current instruction or a closed risk. This continuation created no archives,
schedules, receiver credentials or restore operations.

- Retired `ansible/playbooks/rancher.yml`, the second competing installer that
  still used upstream Helm, two replicas, placement/strategy patches and auxiliary
  writes. It now has one controller-side fail task, no follow-up plays/imports,
  no privilege escalation or credential requirement. Verified with local-only
  Ansible invocation returning the expected refusal; no cluster connection.
- CI now guards retired Rancher/combined-monitoring entrypoints and compares Argo
  bootstrap version/values against its owning Application.
- Fixed partial alias generation: every consumer is validated before any write,
  preventing late scope errors from leaving earlier files modified. Multiple
  registered IP scalars in one file merge correctly; regression tests cover both.
- 44 targeted offline tests pass after merging concurrent published LiteLLM
  changes. No network/service/storage restart or public Wiki publication.

## Remaining implementation gates (backup gate deferred)

1. Complete remaining backup scheduler/destination inventory; choose each app's
   supported consistency method, then implement/restore-test independent copies.
   No generic tar of live SQLite/WAL, routine financial sync, forced workflow idle
   or scheduled unreviewed outages as a shortcut.
2. Compare authoritative public Wiki content/outbox with Git, then use supported
   editor/import/synchronization. Preserve URLs, queued publications and users;
   don't overwrite the active runtime tree from a stale clone.
3. Expand endpoint/owner/vendored contracts from audited exceptions, not blanket
   regex replacement. Network/root cause/relay HA remain dedicated work.

Parallel owner changes in Wishlist/OTEL/Venice worktrees were preserved. Main
working directory may contain those uncommitted changes; no reset/forced checkout
or claim of a globally clean working tree. This work used its own worktree and
merged concurrent published releases before push.
