# Harbor HA migration — capacity stage

Status: **not deployed; production Harbor remains single-node**. The operator
requested fully distributed Harbor. This document and the preflight start that
implementation; they are not evidence of completed HA or permission to cut over.

## Availability contract

Target: after loss of any one participating node, authenticated push/pull remains
available after bounded failover, without manually restoring data. Primary target
is loss of socrat-0. Existing sessions may fail and need safe retries; zero dropped
connections is not promised. PostgreSQL acknowledged-transaction RPO should be zero
for a single failure through synchronous replication, to be validated in staging.

This three-member layout on socrat-0/1/3 **does not survive loss of both home nodes**:
that removes two of three storage/DB voters. Whole-home availability requires an
additional independent, adequately provisioned failure domain and a different
quorum placement. socrat-2 remains reserved for etcd/VPN; it is not a spare storage
server. Node diversity is not site diversity.

## Candidate architecture (requires compatibility validation)

- Two replicas each of Harbor core, portal, registry and jobservice on socrat-0/1;
  required hostname anti-affinity within each component, topology-aware scheduling,
  rolling updates, and PodDisruptionBudgets. Use stdout job logs, not local PVC logs.
- Three independent S3 data/metadata members on socrat-0/1/3; evaluate **Garage**
  with replication factor three, write/read quorums appropriate to one node loss.
  A replication setting alone does not prove safety: validate Harbor's actual S3
  operations, multipart uploads, range reads, deletes, listing and recovery.
  API access must be internal/authenticated, data/RPC encrypted across WG as
  supported, no public bucket. Disable registry redirects so Docker clients do
  not need to access the internal S3 endpoint.
- **CloudNativePG** three-instance PostgreSQL on socrat-0/1/3; synchronous standby
  requirement, primary service endpoint, local persistent volumes, TLS and separate
  application credentials. Pin operator and database versions after checking the
  currently deployed Harbor database version and operator support. Two operator
  replicas must use supported leader election; confirm chart support before install.
- Three Redis/Valkey data members plus three **Sentinels** on socrat-0/1/3. Harbor
  supports external Sentinel, not Redis Cluster. Authenticate both data and
  Sentinel according to the precise Harbor client capabilities. Validate failover
  of core, jobservice and registry clients, not just a standalone redis-cli probe.
- Preserve existing Harbor encryption key, token signing keys and certificate,
  robot accounts, admin credentials and public URL across migration.

S3 and database choices are candidates, not an assertion of tested compatibility.
Pin all images/charts and validate upstream configuration before producing the
production manifests. Avoid Rook/Ceph or replicated NFS solely to solve this registry:
current small nodes have neither the spare resources nor independent data disks.

## Implemented preflight

Files:

- `deploy/harbor/ha-policy.json`: conservative initial component envelopes;
- `scripts/harbor-ha-preflight.py`: read-only host and Kubernetes capacity gate;
- `tests/test_harbor_ha_preflight.py`: gate regression tests.

Run from the repository root:

```sh
python3 scripts/harbor-ha-preflight.py collect --output /tmp/harbor-ha-inventory-UNIQUE.json
python3 scripts/harbor-ha-preflight.py check \
  --inventory /tmp/harbor-ha-inventory-UNIQUE.json \
  --output /tmp/harbor-ha-capacity-UNIQUE.json
```

Exit 0: preliminary capacity gate passes; 1: capacity blocker; 2: invalid, stale or
incomplete inspection. Inventories expire after 15 minutes. Files use mode 0600,
exclusive creation and never overwrite previous reports. No Secret objects,
credential files or application log bodies are collected. SSH uses strict host key
verification. socrat-0 uses the verified home IP/host key alias, not the dual-address
public DNS. Other aliases must already work from the administrator machine.

Initial envelopes, MiB per node:

| Component | socrat-0 | socrat-1 | socrat-3 |
|---|---:|---:|---:|
| Core + portal + jobservice + registry | 960 | 960 | 0 |
| S3 member | 1024 | 1024 | 1024 |
| PostgreSQL instance | 512 | 512 | 512 |
| Redis + Sentinel | 320 | 320 | 320 |
| DB operator | 128 | 128 | 0 |
| **Additional Harbor staging budget** | **2944** | **2944** | **1856** |

These are **design budgets, not measured product minima**. The gate preserves
512 MiB host reserve and additionally reserves all planned OTel components from
`deploy/monitoring/otel-migration-policy.json` when present, with a committed
minimum floor in `ha-policy.json` when that in-progress file is absent. The larger
of the floor and live policy reservation is used. It does not silently consume that
already-agreed capacity or assume swap is spare RAM.

Memory checks use both MemAvailable and node allocatable minus active Pod requests;
init requests are summed conservatively. No credit is taken for removing the
current Harbor: migration needs staging overlap. The checker rejects unhealthy,
cordoned or tainted nodes and incomplete observations.

Storage starts with 120 GiB additional staging envelope per member, retaining the
larger of the node-specific disk reserve and 20% filesystem capacity. This envelope
is provisional: actual backup, old/new copies, WAL, object replication, resync and
maintenance peaks must be measured separately. The checker is deliberately not a
scheduler, N-1 model, IOPS benchmark or restore certification. CPU/network/latency,
PVC binding, topology and Pod startup constraints need their own validation.

## Blocking observations (2026-10-30)

Read-only inspection found approximately 1 GiB host MemAvailable and 0.8 GiB
unreserved scheduler memory on socrat-3. socrat-1 had about 6.3 GiB MemAvailable,
but planned OTel alone reserves 4.25 GiB before host reserve and Harbor staging.
Therefore do not install the distributed dependencies on these hosts yet.

Resolve with added RAM/new independent capacity or an explicitly approved workload
and OTel re-placement. Do not lower budgets merely to turn the gate green. S3, DB
and Redis must be measured under representative load if tighter sizing is proposed.

## Next implementation stages

1. **Capacity remediation:** choose hardware/workload changes, remeasure live
   capacity, validate surviving-node resources and quorum placement. Changes to
   previously agreed OTel placement require approval, not implicit reallocation.
2. **Independent protected backup:** export Harbor PostgreSQL and registry data
   consistently during a controlled write-free window; preserve bootstrap secrets,
   token signing keys and Helm settings. Copy off socrat-0, checksum, and test an
   isolated restore. Do not print secrets. Do not migrate without restore proof.
3. **Isolated HA foundation:** install pinned S3, CNPG and Sentinel manifests,
   explicit budgets, retained PVs, internal NetworkPolicies/TLS as supported, probes
   and monitoring. Use fresh storage; never overwrite production Harbor PVCs.
4. **Compatibility and failure validation:** upload/download by digest, multipart,
   large/slow layers, robot authorization, PG failover, Sentinel failover and S3
   quorum/rejoin. Only component-scoped controlled tests with approval; do not power
   off nodes, sever WG or disrupt the production etcd quorum.
5. **Data migration:** freeze writes, final verified dump and registry tree copy
   into the appropriate S3 prefix, import into HA database, verify counts/digests.
   Reuse token signing and encryption secrets; do not regenerate identities.
6. **Cutover:** versioned Helm HA overlay, external DB/Sentinel/S3, replica placement,
   PDBs and readiness. Ensure the legacy single-node playbook refuses to downgrade
   an HA installation. Preserve both old PVCs and independent backup.
7. **Acceptance:** public push/pull through both entrances, across failover and
   rejoin, with durable image/DB verification. Set and measure explicit RTOs; failure
   tests must not be mistaken for full physical outage coverage.
8. **Operations:** scheduled independent backups with tested restore, capacity and
   replication alerts, robot-expiry alerts, upgrades and rollback runbooks. Quorum
   replication is not a backup against deletion, corruption or credential loss.

Before writes resume, rollback may return to the old data set. After writes resume,
returning to the old database/object store loses new state: stop writers and perform
coordinated reverse migration or restore. Never treat Helm rollback alone as a data
rollback. Keep automatic deletion/GC disabled throughout migration.

References: upstream Harbor HA Helm documentation and the actual 1.19.4 chart
values/templates. Upstream older prose may lag chart support (e.g. Redis TLS);
validate against the pinned chart and application rather than copying examples.

### First reproducible gate result

`deploy/harbor/migration-evidence/capacity-initial.json` preserves the historical
result, not a reusable approval. The live gate additionally found socrat-0 disk
headroom insufficient for the provisional 120 GiB staging copy **and** a 20%
filesystem reserve (about 155.7 GiB left versus 176.7 GiB required). Do not delete
telemetry history or other data to satisfy this check without approval. Resolve
with extra disk or a measured smaller staging projection approved after the real
registry/backup footprint is known.

| Node | MemAvailable observed | Required incl. OTel + reserve | Scheduler free | Result |
|---|---:|---:|---:|---|
| socrat-0 | 21804 MiB | 5760 MiB | 10470 MiB | disk staging reserve blocked |
| socrat-1 | 6520 MiB | 7808 MiB | 5366 MiB | memory and requests blocked |
| socrat-3 | 927 MiB | 2624 MiB | 803 MiB | memory and requests blocked |

These are time-specific observations and conservative planning requirements,
not an assertion that any product has an irreducible memory minimum of that size.
