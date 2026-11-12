# Alertmanager delivery / internal DNS recovery — 12 November 2026

## Symptom and evidence

`AlertmanagerClusterFailedToSendAlerts` was genuinely firing for integration
`webhook`, not a stale Grafana display. Alertmanager received HTTP503 from its
`socrat-bot` receiver: `Triage queue unavailable; retry delivery`. The actual
handoff is Alertmanager → n8n → SPI triage durable enqueue. The custom webhook
correctly refuses to acknowledge a handoff that was not durably accepted.

Read-only checks from the existing n8n pod on5 showed:

- SPI triage podIP and ClusterIP `/healthz` both returned200.
- `spi-triage.automation.svc` resolution intermittently timed out/EAI_AGAIN.
- Direct UDP DNS to old CoreDNS1 endpoint intermittently timed out, including AAAA;
  old CoreDNS3 endpoint answered in paired samples. TCP53 was reachable.
- Merely using an absolute service FQDN did NOT solve the problem:5of10 bounded
  health checks still failed EAI_AGAIN. No FQDN/IP workaround was deployed.
- Filtered, short raw-socket observations were made on1/5 and in n8n's network
  namespace; only diagnostic tuple/DNS question summaries were retained privately.
  No general packet payload export or public user-content dump was made.

This localizes the immediate failure to DNS availability seen by n8n, but does
not prove the underlying reason for UDP losses/delay or a defective CoreDNS
binary. Recreating/moving the DNS pods is an availability recovery, NOT final
transport root-cause closure. The rollout also recreated the replica on3.

## Narrow change accepted

At approximately16:35UTC (19:35MSK), CoreDNS rolled to0and3,2replicas Ready.
Required node affinity is now In[socrat-0,socrat-3]. Existing topology spread,
container configuration, DNS zones, RBAC, volumes and selectors were preserved.
Rollout budget maxSurge1/maxUnavailable0 preserved DNS replicas during migration.
No n8n restart, PVC/data migration, credentials change, manual workflow execution,
node/k3s/WG restart, policy disable, table flush or alert silence was performed.

Source commit1474d79c contains:

- `ansible/roles/k3s_ha_dependencies/defaults/main.yml`: future DNS nodes0/3.
- `ansible/playbooks/coredns-placement-recovery.yml`: one-time guarded recovery.

The scoped play requires reviewed private before/candidate/patch JSON; tests
bound the change to DNS affinity and rollout budget. It preflights both verified
manifest writers0/1 against the exact SHA, preserves root0700/0600 preimages,
stages a candidate, applies a deployment UID/full-spec JSON CAS, then atomically
activates the same candidate on both writers. It stops on any host failure.

### Source/runtime drift found and reconciled

Existing writer files on0/1 were byte-identical but pinned0/2, while the live
Deployment used NotIn[2] and happened to run on1/3. The source manifest was absent
on2. Live Addon ownership identified `homelab-coredns-ha`; only its verified0/1
files were changed. No generic dependency role or server-wide manifest replay.
The old source is NOT the immediately previous live placement. Do not use the
stale0/2 file as an automatic runtime rollback. Inspect private before-live spec
and current UID/spec before any narrowly approved rollback.

Backup root on0/1: `/var/lib/homelab-recovery/20261112-coredns-placement/`.
Controller receipts/private plan: `/tmp/socrat-alert-dns-repair/`.
Temporary sudo credential file was removed after operations.

## Functional acceptance

- Rollout completed:2desired/2updated/2ready; replicas on0and3.
- All6nodes Ready; n8n pod identity, restart count13 and placement5 unchanged.
- Ten actual short-name SPI health fetches from n8n all200 after rollout.
- Eighteen direct DNS checks from n8n: each new CoreDNS endpoint and the ServiceIP,
  three A and three AAAA checks per destination. A returned expected serviceIP;
  AAAA returned expected ENODATA in this IPv4 service. All6–14ms, no timeouts.
- **Natural delivery acceptance:** Alertmanager logged Notify success at
  16:35:17–16:35:38UTC for queued notification groups, including this critical
  delivery alert itself. No synthetic enqueue or manual workflow was executed.
- At16:37UTC, failed-notification counters had no increase over2minutes (there
  were also no new completed sends in that last2minute slice). Earlier explicit
  Notify success logs, not zero activity alone, establish recovery.
-14Python tests plus5native webhook tests passed; Ansible syntax-check and
  git diff --check passed.

## Alert closeout boundary

At16:37UTC the critical rule was STILL firing: its condition uses a15minute
failure-rate window and includes pre-recovery errors. No threshold/window or
severity was weakened. Expect automatic resolution once the old failures leave
that window, provided delivery remains successful. A Normal-state readback is
still required; do not call the alert cleared based only on pod readiness.

Residual work: observe another natural notification/recovery cycle, verify the
rule transitions Normal, investigate the avoided old1↔5 DNS path and broader
mixed-backend/transport symptoms separately. Successful short samples are not a
universal mesh or DNS fault-tolerance acceptance.
