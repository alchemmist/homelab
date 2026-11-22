---
name: vps-ip-migration
description: "Migrate the public IPv4 address of socrat-2 after provider reassignment, a planned move or loss of reachability. Use the required Ansible host/source phase, then verify DNS glue, 3x-ui, WireGuard, the Collector, NetBird, GitOps and actual client delivery."
---

# Move socrat-2 to a new public IPv4 address

## Scope and responsibilities

Use **`ansible/playbooks/vps-ip-migration.yml`**, not a sequence of unrecorded `sed`, SQL or SSH commands. The playbook is the reproducible host phase; **its success does not certify the migration**. Use this skill before and after running it.

Automation: [`scripts/vps-ip-migration.py`](../../../scripts/vps-ip-migration.py). Unless noted otherwise, paths are relative to the repository root. For the previous migration's inventory, owners and observed failures, see `docs/records/handoffs/vps-ip-migration-20261105.md`.

- **Playbook:** requires explicit OLD and NEW IPv4 addresses and preflight on all four nodes. It manages allowlisted source files, private preimages, targeted host files, WireGuard endpoints without an interface restart, and native Knot, TCP transport and guard configuration. SQLite operations are limited to read-only audit and online backup. Updating `hosts.address` is a separate native API phase.
- **Operator:** choose the access path, investigate failures and ownership changes, agree downtime, handle the registrar, GitOps, Kubernetes, Secrets and Collector, and verify external VPN delivery, subscriptions and client profiles.
- This checklist is a minimum, not permission to ignore a new dependency. Stop and investigate if schema, identity or ownership has changed.

## 0. Authorization, isolation and access

1. Obtain OLD and NEW from the operator or provider. Do not infer them from DNS: answers can be split, cached or intercepted. Neither a timeout nor a support reply proves TSPU filtering.
2. Confirm whether NEW is assigned or scheduled, whether OLD remains usable, whether short VPN/NetBird interruptions are approved and whether an emergency backup is needed. An IP change does not imply reinstalling the OS or upgrading all software.
3. Read current project instructions and check `git status`. If the checkout is dirty, obtain permission before adding a worktree. If extra checkouts are prohibited, make targeted changes in the agreed checkout. Use one writer per worktree; do not stash, reset, force-push or overwrite others' work.
4. Verify private access via `10.250.0.2` and an independent SSH path or provider console. Do not switch the only working path before testing the replacement. Preserve the pinned host key and `StrictHostKeyChecking`.
5. Verify NEW on the interface, the outbound source route and external DNS/HTTPS. The provider may retain a gateway from the old prefix. **Do not derive the gateway from NEW** or guess a replacement route. Verify persistent address assignment without an unnecessary reboot.
6. Obtain passwords only from the existing private controller or Ansible Vault. Never print secret YAML, tokens, subscription URLs or QR codes, SQL dumps, keys or raw user logs. Use counts, hashes, infrastructure addresses and HTTP status codes as evidence.

## 1. Inventory and backups before changes

- Prioritize a backup outside the VPS over another on-host copy. Establish what has completed and been verified; a `.partial` file is not a backup. Retain completed emergency archives after access returns. Playbook preimages do **not** replace a server backup.
- Use the online backup API and `quick_check` for SQLite, pg_dump/pg_dumpall for PostgreSQL and the native k3s etcd snapshot for embedded etcd. A tar of a running database is not necessarily consistent. A file or checksum is not a restore test.
- Find OLD in active sources, live specs, ConfigMaps, Secrets, native configuration and profiles. Inspect secrets privately and report only paths and counts. Do not bulk-replace OLD in Git history, historical manifests, receipts or backups. Review new active files before adding them to the allowlist.
- Inventory mounts and locate the actual data. `tar --one-file-system` omits other filesystems and virtual mount views.
- Inspect **all 3x-ui tables**, not only settings and inbounds. Previous addresses appeared in `hosts.address`. Never replace strings in a binary `.db` file.
- Record baseline node readiness, pod UIDs, container IDs and restart counts, backend and database identities, native services, resource ownership and alert states. Existing OutOfSync is not permission for blanket sync or prune.

## 2. Required Ansible phase

Read the playbook, role defaults and helper first. They deliberately do not install packages, change keys, deploy all charts or create a Git commit. Create a mode `0600` parameter file **outside Git**:

```yaml
vps_ip_migration_old_ip: "<OLD_PUBLIC_IPV4>"
vps_ip_migration_new_ip: "<NEW_PUBLIC_IPV4>"
vps_ip_migration_apply: false
# Source of truth: the approved checkout, excluding unrelated dirty changes.
# Default backup roots: root-owned /var/backups/... on the nodes;
# private ~/Library/Application Support/homelab/vps-ip-migration on the controller.
```

Check inventory routing. If the old DNS name is unavailable, add a separate private override inventory using existing SSH aliases or verified addresses. Do not change global SSH settings or credentials or use `--limit` to skip preflight. All four nodes must be reachable. The default run audits only; Ansible `--check` does not apply the migration either.

```sh
cd /path/to/approved-homelab/ansible
CROOT="$HOME/Library/Application Support/homelab/otel-controller"
ANSIBLE_NOCOLOR=1 ANSIBLE_SSH_EXECUTABLE=/usr/bin/ssh \
  ansible-playbook -i inventory/hosts.yml \
  playbooks/vps-ip-migration.yml \
  -e @"$CROOT/become.yml" -e @/private/path/ip-migration.yml
```

Before running, check the effective HostName and ProxyJump with `/usr/bin/ssh -G` and verify the actual connection source. An old `$CROOT/bin/ssh` wrapper may silently replace a private alias with a public IP or ProxyJump. Do not treat it as private-only or use it without separate review. Use direct SSH to NEW only with explicit operator approval and the existing pinned host key.

If required, add a second `-i /private/path/access-override.yml`. Review each node's plan and the source diff. NEW must already be assigned to the VPS; otherwise the playbook stops rather than publishing an unusable IP. Only after review and approval for native service restarts, add these arguments to the same invocation:

```sh
-e vps_ip_migration_apply=true \
-e vps_ip_migration_allow_service_restarts=true
```

Order: preflight all nodes, update source, update the VPS, then process `socrat-0/1/3` serially. Default audit rewrites nothing; temporary remote Ansible scripts are not backups.

### Host phase boundaries

- Updates the installed DNS renderer/refresh configuration and, on the VPS, the Knot listener, `/etc/hosts`, WireGuard installer parameters and retained installer metadata.
- Updates persistent `wg-socrat.conf`. At runtime, changes **only the relevant peer endpoint**: no `wg-quick down/up`, key changes, AllowedIPs changes or mesh replacement.
- Updates TCP transport server/client configuration. The guard adds its narrowly scoped new rule before removing the exact old rule. **Never flush the firewall.**
- Acts only on affected, already active native Knot, TCP transport and guard units. It does not start dormant native fallback or legacy VPN services.
- Audits VPS SQLite schema and integrity read-only and takes consistent online preimages. No production SQL writes. `native_api_address_migration_pending` requires a separate native API change with a fresh preimage and compare-and-swap (CAS), limited to `hosts.address`. Preserve IDs, keys, clients, limits and every other field. Do not automatically rewrite the historical legacy database.
- Leave an inactive guard inactive only after explicit per-host review in `vps_ip_migration_reviewed_service_states`. A known transport in activating/auto-restart may receive a targeted restart after review of its current state. Drift or unknown states stop audit/apply. This playbook does not start k3s.
- JSON receipts omit sensitive strings. `native_api_address_migration_pending` identifies outstanding API work; it does **not** mean a Kubernetes reload or restart occurred.

### Failure and retry

Stop on any error. Keep preimages and receipts private. There is no automatic rollback to a blocked IP. A receipt marked `applying` or `partial-failure-stop-and-investigate` prohibits a blind retry.

Inspect each affected file, database, runtime endpoint and service. Privately document recovery or reconciliation to the agreed state. Only after an explicit decision backed by evidence, mark that specific receipt `manually-reconciled`, preserving a separate copy of the original. Audit again. Do not conceal partial source or host changes, restore whole live datasets over new writes, or lose traffic counters. A repeated successful apply should be a no-op, but a no-op is not acceptance. Check earlier receipts for a still-pending reload.

## 3. Review source, GitOps and other runtime owners

Inspect the source diff for active inventory and direct addresses, WireGuard/TCP defaults, public DNS, Traefik edge, blackbox target, bot webhook, NetBird/STUN and RustFS authentication egress. Do not change images, databases or ownership incidentally.

- Run targeted tests and Helm renders. Report their scope, compare existing failures against the baseline and do not weaken tests or alerts to obtain a pass.
- Commit only your files, fetch and rebase on current main, then push normally. If an HTTPS helper is approved, use command-scoped `git -c credential.helper='!gh auth git-credential' ...`; never change global remotes or credentials or force-push. On push error, inspect the remote tip first.
- Hard-refresh only the relevant Argo applications. Check effective values, parameters, revision and rollout. A GitHub commit is not evidence of deployment.
- Render NetworkPolicies for the correct namespace, e.g. `helm template ... --namespace rustfs`. Check the identity gateway separately. Never blindly apply resources for distinct namespaces under one `-n`.
- Audit Services/externalIPs, Deployment arguments and environment, NetworkPolicies, StatefulSets, DaemonSets and Ingresses. Do not rewrite generated status/IP or treat Rancher publicEndpoints as persistent source; it can contain a pod name.
- Inspect ConfigMap/Secret values privately; report only namespace, name, key and count. For a single field, retain a private preimage and use a targeted JSON patch with a resourceVersion precondition. Do not print full configuration or update all Secrets indiscriminately.

### 3x-ui and subscriptions after the host phase

1. The playbook retains a consistent backup. The native writer additionally requires a fresh preimage, CAS and its own invariant checks immediately before writing. If the helper no longer matches the panel schema, investigate the supported API; do not bypass assertions.
2. After changing `hosts.address` through the native API, determine whether a reload is needed. Do not confuse native fallback with the Kubernetes pod. If necessary, agree a short interruption and recreate only the identified x-ui pod under the current Deployment. Verify namespace, UID, image and hostPath first; wait for Ready. Do not restart the VPS, k3s, PostgreSQL or Collector, or run a concurrent SQLite writer.
3. Check every enabled plain **and JSON** subscription without exposing subId, URL or body. Decode base64 and vmess; inspect actual destinations, not raw substrings. Count subscriptions, links, OLD/NEW/other destinations and errors. Classify other destinations: a retained domain can be legitimate.
4. Keys, passwords, IDs and ports must not change. A successful database update or restart does not prove the served links changed. Compare before/after results, `quick_check` and invariants.

### Native Collector: a separate owner for metrics

A ServiceMonitor or Helm change does not reconfigure the saved `otel-cluster-config.data.scrape.yaml`. Prometheus owns OTLP storage and evaluation; **do not move scraping back to Prometheus**.

- Identify the single VPS blackbox job by ownership and `service_id=edge-vps`, not a position such as `.../26` or a whole-YAML replacement. `scripts/otel-scrape-config.py` and `otel-production-cluster.py` already normalize the captured bundle against the chart target.
- Retain a private ConfigMap preimage. Change only the target; keep every other job and `collector.yaml` byte-for-byte identical. Validate the candidate with the pinned Collector.
- Verify the ConfigMap projection actually updated. Activate through `ansible/playbooks/otel-cluster-logs-activate.yml` with a fresh pod UID, exact running container ID, actual imageRef and config/scrape SHA256. Verify the full binary hash. Read the playbook; do not reuse values from an old receipt.
- Do not restart the shared pod or StatefulSet. Target only the Collector container lifecycle. Prometheus, Thanos and reloader container IDs and restart counts must not change.
- Compare before/after receiver refused/failed, exporter failed/enqueue, queue levels and drain, sent metric/log deltas, readiness and sample age. Report any short scrape gap.
- OLD series can remain until lookback expiry. Do not delete them or disable the alert. Wait for `probe_success=1` on NEW and for the alert to clear.
- **Required closeout:** a fresh `probe_success{service_id="edge-vps"}` must identify NEW. Check the exact live expression on panel 906 of `socrat-traffic-light`: 0 means OK. Source, ServiceMonitor and Argo Synced do not establish that result. Record it explicitly before declaring completion.

### NetBird and Telegram

- The NetBird STUN binding and advertised URI are separate settings. The STUN-only listener is GitOps-managed; the URI may be in the private `netbird-runtime` Secret. Change only that field and preserve other bytes and credentials. Secret projection does not prove the server reloaded. Use a separately scoped reload or single-pod recreation with a Ready gate. Do not rotate setup keys or change policy for an IP migration.
- Test an actual external UDP Binding: validate the transaction ID and XOR-MAPPED address, and verify the source was not unexpectedly SNATed. TURN Allocate must not create an open relay. Do not print user source IPs. STUN reachability is not full NetBird acceptance.
- Update bot chart webhookIP through GitOps. Call `getWebhookInfo` from a network that can reach Telegram, keeping the token in memory or private process input. Report only configured IP, pending count and error time/class. A historical last_error is not a new failure; an empty queue does not prove fresh delivery. Do not use drop_pending_updates.

## 4. Registrar: a child A record is not parent glue

The recorded `.xyz` delegation uses `ns1.alchemmist.xyz` (home) and `ns2.alchemmist.xyz` (VPS). A new record inside Knot does not update parent glue.

1. Verify the current registrar and delegation rather than assuming the historical setup still applies.
2. In the existing authorized REG.RU session, open `alchemmist.xyz`, DNS servers, custom list. Preserve both NS names and the ns1 IP. Change **only** the ns2 IP. Do not switch to registrar DNS or remove the delegation.
3. Compare both name/IP pairs before submitting. Save and verify confirmation in the account. Hand control to the user for login or MFA; never request a password in chat.
4. Query at least two authoritative `.xyz` servers directly (`dig @x.nic.xyz ... NS +norecurse` and `@y.nic.xyz`); inspect ADDITIONAL glue. Verify the parent servers actually answered rather than a DNS interceptor. Use an independent network if uncertain. Google/Cloudflare DoH is supplementary; a child A answer does **not** prove a glue update.
5. If the parent still serves OLD, the registrar accepted the request but publication is pending. Do not blame recursive caches for an old authoritative answer. Once the parent serves NEW, recursive caches may retain OLD until TTL expiry. Record observed TTL and time; do not promise immediate global convergence.

## 5. Acceptance from the right observation points

Complete the [acceptance ledger](references/acceptance.md); consult [troubleshooting](references/troubleshooting.md) for deviations. Test actual behavior, not just the list of configured components. If a required result is unknown, do not report completion. Distinguish server-side completion, propagation pending and client action required.

Select current commands and profiles for the situation, but always verify these properties:

- Test TCP/TLS from home, mobile and independent networks, not only a VPS self-hairpin.
- Use `scripts/check-public-ingress.py --check-dns` with TLS verification enabled. Validate login redirects by status and target; an arbitrary 302 is not backend health.
- Use an authenticated VPN client **outside the VPS**, literal NEW, correct TLS SNI and WebSocket path, and HTTPS requests to a neutral destination, Telegram and ChatGPT. Repeat after the final reload. One profile does not certify every Reality/VLESS/WireGuard/AmneziaWG profile. Test protocols in use or record each as unverified. Do not generate traffic with another person's credentials.
- Use a private temporary probe configuration, bounded timeout and specific process/PID. Do not log raw bodies. Delete temporary pods, Secrets and bundles and confirm absence. Keep permanent backups and preimages. Never kill unrelated browsers or processes.
- Recheck CROOT, the local SSH alias, the generated Mac WireGuard profile and the **actually imported** profile. Updating a file does not update a GUI profile.
- Ask the user to refresh the phone subscription and reconnect. A statically imported IP does not update remotely; do not require new keys or QR codes unnecessarily.
- Preventing future blocking is outside this skill. NEW can also become unreachable.

## Final report

Record OLD → NEW, commit/revision, what was applied versus actually delivered, tests and observation points, remaining OutOfSync or unknown states, parent glue, client actions, brief interruptions and retained backup/preimage locations (not contents). Report failures and fixes separately. A short successful test is not an indefinite reliability guarantee.

### Native host-address writer (3x-ui 3.11.0)

`scripts/vps-panel-host-migrate.py --state /private/vpn83-... --old-ip OLD --new-ip NEW` produces a read-only preview. Apply requires that preview's exact `--approve-sha256` and `--apply`. The hosts/update operation needs a temporary worker with admin scope; ordinary sessions remain node-sync. Use unique names per session, 20-minute worker TTL, 30-minute cleanup TTL, an online preimage and cleanup without rotating existing tokens. Do not grant permanent admin or use human authorization.

The native DTO round trip updates host `updated_at`, encodes nullable Boolean false as 0, and expands empty `snis` with a single `sni` into an explicit one-element pool. The writer permits only those verified, semantically equivalent codec effects and a fresh native timestamp **only on rows whose address changed**. Changes to actual SNI, pools, flags, IDs, clients, limits or other tables are not ignored. An unfamiliar diff produces an uncertain receipt. Read back and compare with upstream before doing anything else; do not repeat the original call. After reconciliation, preview only remaining OLD rows with fresh state and new approval.

API success does not prove delivery. Verify URI and JSON for all retained identities: backend and public TLS entry point must agree; OLD must be absent and NEW present. A host-only update does not justify a blind restart. Test both schemes externally against literal NEW while preserving TLS SNI/Host. A hostname-only Trojan test can silently reach a different VPS or HOME. Do not change global routes, DNS, proxies or Mac WireGuard for a per-process probe.
