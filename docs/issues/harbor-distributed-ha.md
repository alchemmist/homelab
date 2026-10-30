# Implement distributed Harbor with single-node failure tolerance

> Draft issue body. Not yet published: GitHub MCP was unavailable in the session.

## Goal

Migrate the current public Harbor at https://harbor.socrat.alchemmist.xyz from
single-node socrat-0 to a fully distributed installation that continues authenticated
push/pull after failure of any one participating node, especially socrat-0.
A bounded failover/retry interval is acceptable; define and measure RTO before rollout.

This is **not whole-home failure tolerance**: socrat-0/1 are in the same home failure
domain, so losing both destroys the proposed three-member quorum.

## Current state

- Harbor 2.15.4, official Helm chart 1.19.4; sources in `deploy/harbor/` and
  `ansible/roles/harbor/`, entry point `ansible/playbooks/harbor.yml`.
- All components and local-path registry/PostgreSQL/Redis PVCs on socrat-0.
- Trusted HTTPS through home and VPS ingress. Private `homelab` project, registration
  disabled, separate project-scoped push/pull robots (90-day expiry).
- Push and cross-node authenticated pull verified; existing GHCR deployments unchanged.
- No independent scheduled backups/restore verification yet. Retain is not a backup.

## Proposed architecture

- Two replicas each of core, portal, registry and jobservice on socrat-0/1,
  hostname anti-affinity, PDBs and safe rolling updates. Job logs to stdout.
- Three-member S3 data/metadata storage on socrat-0/1/3; evaluate Garage RF=3.
  Validate Harbor's S3/multipart/range/list/delete semantics, quorum and resync.
  Internal authenticated endpoint; registry redirects disabled.
- CloudNativePG, three PostgreSQL instances on socrat-0/1/3, synchronous replication,
  safe primary election/fencing, TLS and independent persistent volumes.
- Three Redis/Valkey data instances and Sentinels on socrat-0/1/3.
  Harbor external Sentinel configuration, **not Redis Cluster**.
- Preserve public URL, robot identities, DB records, encryption and token-signing keys.
- socrat-2 remains reserved for existing etcd/VPN; no unapproved workloads there.

Products are candidates until exact pinned versions and compatibility are verified.
Do not represent these components as already installed.

## Resource blocker / prerequisite

Initial conservative staging gate failed. Historical evidence:
`deploy/harbor/migration-evidence/capacity-initial.json`.

| Node | Available RAM | Required incl. OTel/reserve | Blocker |
|---|---:|---:|---|
| socrat-0 | 21804 MiB | 5760 MiB | staging disk reserve |
| socrat-1 | 6520 MiB | 7808 MiB | host/scheduler RAM |
| socrat-3 | 927 MiB | 2624 MiB | host/scheduler RAM |

Resolve with more RAM/capacity or explicitly approved placement changes. A potential
hardware direction is socrat-3 to 8 GiB and +4–8 GiB on socrat-1, followed by fresh
measurement. This is a proposal, not an approved purchase or guaranteed sizing.
Measure real storage migration peaks; do not delete originals to fit the disk gate.

Preflight: `scripts/harbor-ha-preflight.py`, policy `deploy/harbor/ha-policy.json`.
OTel reservations are preserved. Passing this gate alone does not authorize cutover.

## Implementation checklist

- [ ] Agree capacity remediation, failure domains, RTO and DB RPO; rerun fresh preflight.
- [ ] Verify N-1 placement, CPU, memory, disk peaks, storage IOPS and WAN/WG latency.
- [ ] Consistent off-node backup of database, registry data and protected secrets.
- [ ] Prove isolated restore before migration; preserve original PVCs.
- [ ] Pin and deploy S3, CNPG and Sentinel as declarative sources with budgets,
      retained PVs, probes, supported TLS/auth, and internal access restrictions.
- [ ] Test S3 compatibility and recovery, DB failover and Harbor Sentinel reconnection.
- [ ] Add HA Helm overlay, required anti-affinity/PDBs and safe update policies.
- [ ] Guard the legacy single-node playbook against accidental downgrade of HA.
- [ ] Controlled write-free migration, verified object prefix/data/DB import and cutover.
- [ ] Document rollback before and after resuming writes; Helm rollback is not data rollback.
- [ ] Configure scheduled independent backups, restore drills and alerts for storage,
      replication, quorum health and expiring robot credentials.
- [ ] Update `docs/harbor.md`, `docs/harbor-ha.md` and `llm-wiki/harbor.md` to actual state.

## Acceptance criteria

- Private push/pull succeeds through both public ingress addresses, before and after
  a single component/node-loss-equivalent failure and subsequent rejoin.
- Same known image digests are retrievable; acknowledged DB state is preserved.
- Stale primary cannot continue accepting conflicting writes; loss of quorum fails safely.
- Surviving nodes remain healthy, and etcd/VPN/OTel capacity is not silently consumed.
- Exact measured RTO/RPO and test coverage are recorded; controlled component tests
  are not claimed as physical whole-node or whole-home outage tests.
- Anonymous/private access remains denied; CI/pull robots retain least privilege.
- Independent restore procedure is verified, not merely documented.

Do not power off nodes, sever their network or disrupt etcd to test this without
explicit approval. No automatic GC/retention deletion during migration.

## References

- `docs/harbor-ha.md` — design, gate and migration/rollback stages.
- `docs/harbor.md` — active single-node deployment.
- `llm-wiki/harbor.md` — usage and agent context.
