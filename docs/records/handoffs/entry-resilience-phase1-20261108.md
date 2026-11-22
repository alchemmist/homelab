# Cheap entry resilience — phase1,2026-11-08

Owner approved work without waiting for replacement VPS IP. Preserve native SSO,
TLS verification, credentials, Corporate Tunnelblick, Mac/global DNS/routes,
NetBird/inter-node/recovery WG, databases/history and unrelated dirty SPI/dashboard
work. No agents/worktrees, provider purchase, mass sync/prune or restarts.

##1. Observer diagnostic runner (Git-owned CronJob only)

`deploy/platform/rancher/public-entry/files/observer_runner.py` instruments existing
HTTP opener and runs the UNCHANGED membership controller once. CronJob starts this
wrapper instead of main directly; its own original output remains. New natural
jobs pick up code without restarting Wiki or a running worker. Shared Wiki module
and checksum unchanged: no Recreate Wiki rollout. No role/token/CAS/TTL/quota,
timeout, retry, CPU-limit, NetworkPolicy or alert-rule change.

Failures emit bounded JSON: fixed stage (IDP groups/users, native cache reads/patch,
or unknown snapshot/plan), HTTPS-open versus response-read, safe error kind,
HTTP status if relevant, duration. DNS/SSL-cert/refusal/timeout classified without
exception strings, URLs, IDs, headers, bodies or tokens. Timeout at https_open does
NOT prove TCP vs TLS specifically. Suppressed exception context is inspected only
for bounded wrapper metadata. PATCH failures conservatively indicate possible
application; NO retry. Unknown validation context has mutation uncertainty=null.
Operator must inspect native state, not replay. Success emits duration alongside
unchanged native zero-user/zero-role counters.

Private preimage: socrat-0
`/var/lib/homelab-observer-rollout/resilience-phase1-20261108/`.
Use only normal owning Argo reconciliation; no blanket sync/prune/live override.
Accept by UID + main-module hash preservation, only command field difference in
CronJob spec, exact runner hash, fresh natural jobs/new structured event, unchanged
other ConfigMap data and no freshness alert. Fault modes are unit-tested without
intentionally breaking production Authentik or revoking credentials.

##2. Backend-aware credential-free observation

`scripts/public-entry-health.py` forces one owned entry IPv4 while retaining auth
Host/SNI, standard CA verification and no redirects/proxy/credentials. It checks
TCP→TLS→HTTP200→bounded JSON OIDC discovery with expected Rancher issuer and same
HTTPS origin for public endpoints. Arbitrary TCP443 is not backend health.
At most one request per selected known entry;65536byte body bound,3s per socket
operation. No packet payload capture or DNS mutation. No always-on timer yet.

Vantages are operator labels, NOT independently authenticated ASN/country proof.
Self-entry/private-LAN and workstation-unattested results are local-only. Home
public-IP hairpin is never external-entry acceptance. `internal` probe is home-only.
A separate attested collector identity/network is required before policy use.
Forced-IP checks are not ordinary DNS or browser fallback acceptance.

Initial home observation: home public hairpin backend200, privateHA-VIP backend200,
literalVPS public TCP timeout. Private receipts on home
`/var/lib/homelab-public-entry-observe-20261108/`. VPS vantage launch FAILED before
execution: approved privateSSH10.250.0.2:2222 timed out; no public SSH fallback,
no repeated launch or silent claim of VPS results. Subsequent home checks also
cannot reach VPS private2222/443; node socrat-2 Ready=Unknown, other three Ready.
This is a NEW degradation from the earlier internal-VPS health; no configuration
was modified on VPS in this phase. Cause/provider/IP replacement status unknown.

##3. Shared failover decision prototype — OFFLINE ONLY

`scripts/public-entry-failover-plan.py` is pure/bounded JSON in→stdout, never
publishes/writes DNS or invokes renderer/Knot/systemd. Same state+shared round+
policy gives byte-equivalent decisions for authorities. It is NOT an implemented
consensus protocol or live central publisher.

Three fresh distinct rounds needed to remove/restore an entrance. Required
vantages per entry must be independently attested, non-local and backend-aware.
Duplicate rounds idempotent; conflicting/out-of-order rounds refused. Reused
samples cannot advance hysteresis; stale/future/missing/self-only observations hold.
Mixed reachable/unreachable results are PARTITIONED, not global up/down; hold the
previous publication and require explicit operator policy. Never publish empty;
retain last publication with warning. **Every result ready_to_publish=false.**
Two arbitrary different labels do not prove independent networks. Trusted collector
transport, single-writer authority, leadership/fencing, signed/versioned decision
manifest, freshness leases, safe stale behavior, rollout/rollback and partition
policy need review before a production publisher. No local loopback auto-winner.

Existing public renderer, authoritative zones, refresh timers, records/TTL,
registrar/glue and DNS upstreams unchanged. New IP not required for offline tests;
recovery and actual end-to-end validation still required before live DNS rollout.
DNS cannot guarantee browser failover under arbitrary per-network filtering, nor
restore Authentik/database if home backend or its storage is down.

##4. Internal-call inventory (no bulk rewrite)

- Authentik OIDC/discovery/membership inside pods: existing scoped auth DNS key now
  privateHA-VIP, covers hostname users without changing issuer. Wiki + membership
  acceptance established separately; not all apps' interactive SSO proven.
- Rancher internal HTTPS name: existing rancher-private.server already scoped to
  private nodes; do not replace/delete its key.
- Ansible/bootstrap scripts on hosts are NOT pod DNS consumers; their public API
  calls still need explicit per-process route assessment, not global DNS changes.
- External browser redirects, ACME checks, inbound webhooks and viewer MCP clients
  are intentionally public; do not blindly rewrite them as internal service calls.
- NetBird running peers/control path must be preserved, no forced SSO/reconnect.
  Cluster DNS mapping is not host resolver/peer-endpoint reconfiguration.

Next: validate the Git-owned runner after natural reconciliation, retain observations,
resolve current VPS private unreachability with owner/provider, then design reviewed
collector/publisher + consistency/stale/partition gates. No blind change of public
DNS health thresholds or route all VPN traffic onto HOME infrastructure IP.


## Phase1 acceptance21:23UTC

Git219eddf reconciled naturally by owning rancher Argo application: Synced/Healthy,
operation Succeeded; no manual sync/prune/image override. ConfigMap/CronJob UIDs
preserved, original membership controller bytes unchanged, only added runner key
and changed CronJob command. Full other CronJob spec/ConfigMap data equal preimage.
Three natural NEW runner jobs21:21,21:22,21:23 all succeeded and logged structured
completion (1441/1643/1192ms reconcile time, not full pod startup). Native summaries
all cache_updates=0/users_created=0/roles_modified=0. No forced fault/credential
revocation experiment. Prometheus no pending/firing freshness alert,32.753s since
last success. Root private acceptance/monitoring proof retained in phase1 directory.

Targeted tests93passed+195subtests, covering no-secret diagnostics, one execution/no
retry, uncertain PATCH, unchanged shared Wiki controller, TLS verification, backend
schema versus TCP-only, local-only evidence, deterministic offline planner,
hysteresis, stale/missing/partitioned/total failure and duplicate evidence.

Public DNS behavior is STILL UNCHANGED. Health probe is an on-demand tool, NOT a
new continuous collector/timer or newly provisioned independent external machine.
Planner is a tested prototype, NOT production consensus or guaranteed failover.
VPS private access remains unverified after21:15 failure/ReadyUnknown; no successful
VPS-vantage sample, provider intervention, route repair or new-IP migration claimed.

Expanded final verification:103passed+195subtests including private DNS role tests.
The first expanded run lacked local Jinja2 and failed one test at import; offline
cache could not supply it. Reran in an ephemeral uv environment with Jinja2=3.1.6
(test-controller dependency only, no production install); all103passed. Earlier
93-test result is the narrower suite, not an assertion that missing-dependency run
passed. No CI/reboot/DR/mobile full-protocol or VPS recovery proof implied.
