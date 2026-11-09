# Requested VPS migration109.120.141.97→109.120.141.60

Status: **blocked at access preflight; no migration apply performed**.
Owner supplied new address and explicitly requested full migration using the
project skill. Read `.agents/skills/vps-ip-migration/SKILL.md`, its troubleshooting,
playbook/role/helper and previous acceptance before execution. Earlier explicit
no-subagents/no-extra-checkout and private-only pinnedSSH constraints retained;
unrelated dirty dashboard/untracked resources preserved.

## Current evidence

- New literal public443/32053 times out from controller and home node.
- Approved privateVPS10.250.0.2:2222 also times out from home.
- Home runtime WG peer for10.250.0.2/32 uniquely identified; still has OLD endpoint
  109.120.141.97:51830. Public peer fingerprint only, no key output.
- Native TCP transport unit inactive on home; do not start it as a blind repair.
- Whether provider assignedNEW inside guest, removedOLD, changed persistent NIC
  settings or only allocated an address is UNKNOWN. Owner asked to confirm before
  endpoint/address/publication mutations. Do not infer netmask/gateway from NEW.
- Mandatory Ansible playbook was actually run with apply=false, no --limit.
  First controller audit stopped due backup-root mode guard; investigated, selected
  a NEW private0700 repository-preimage child, preserved original log; no apply or
  mutation receipt existed. Corrected read-only audit passed controller and stopped
  at unreachable socrat-2; recap all changed=0. No blind apply/replay or bypass.

Private controller parameters/audit logs:
`~/Library/Application Support/homelab/vps-ip-migration/new-109.120.141.60-20261108/`.
Both audit attempts retained. Do not paste logs/configs/credentials wholesale.

## Required continuation, NOT acceptance

1. Confirm provider stage/oldIP retention and authorized console availability.
   If NEW already configured, an explicitly bounded saved-preimage WG endpoint
   bootstrap for the one known VPS peer may restore approved privateSSH using
   existing cryptographic identity, before full four-node preflight. If guest NIC
   not configured, needs provider console; no publicSSH fallback or guessed route.
2. Preserve existing completed off-VPS backups; verify inventory/mounts/data and
   fresh consistent native backups. Host preimages are not disaster recovery.
3. Update reviewed automation BEFORE apply: old helper directly writes panelSQLite;
   current explicit native-owner/API-only constraint prohibits repeating that.
   Defer panel host changes to scoped native API, preserve all client/key/quota/
   publication/retirement invariants, do not mutate retained historical DB blindly.
   Mandatory host/source playbook remains the deterministic host phase.
4. Extend source allowlist after reviewing NEW active dependencies sinceNov5,
   notably public-entry-health.py and active VPN-hardening IP policy references.
   Historical receipts/docs must NOT undergo global address replacement.
5. Full four-node preflight, exact plans/preimages, targeted active services only;
   no K3s/node/database restart, WG interface bounce, wholesale key rotation, firewall
   flush, globalMac/corporateVPN/DNS change or blanket Argo sync/prune.
6. Deliver GitOps/live endpoints, NetBird STUN advertised private config, Collector
   saved scrape target/isolated activation, bot pinned webhookIP, registrarNS2 glue,
   all URI/JSON subscriptions and generated/imported profile checks per skill.
7. Correct forced-IP public HTTPS + authenticatedREALITY/Trojan outsideVPS after
   final native reload; preserve guard12096/32087, retired32063, auth privateHA DNS
   and safe observer diagnostic runner. Independent network/mobile acceptance,
   parent glue and propagation/client refresh are separate gates.

Do not report complete, assignedNEW, changed peer/NIC/DB/zone/glue/subscriptions,
or successful end-to-end acceptance from these access/audit results.

## 2026-11-09: console recovery, NOT full migration acceptance

The preceding November 8 evidence is historical. Through the authorized provider
console, current guest `socrat-2` has `109.120.141.60/24` on eth0 and default route
via `109.120.141.1`. Both gateway and 1.1.1.1 answered ICMP. These are observed
values, not a computed gateway. Persistent NIC configuration has not been verified.
Controller TCP probes to literal NEW:443 and NEW:32053 succeeded; this is not
an authenticated proxy acceptance test.

Provider keyboard input proved unsafe for long/shifted text: one long read-only
payload was truncated; case synchronization produced command-not-found/NameError
before any backup/configuration mutation. Short slower input and the provider's
on-screen Caps key restored verified literal input. No password copied into
commands, files, Git or this report. No server/network restart performed.

### Accepted emergency bootstrap only

All five VPS wg-socrat peers initially had no runtime endpoint and zero handshake.
Existing keys and AllowedIPs were retained. A root-only mode0600 exclusive preimage
`/root/vps-bootstrap-20261109.wg-dump` was saved. An exact fresh dump CAS and unique
`10.250.0.1/32` peer selection preceded setting ONLY that runtime peer endpoint to
known HOME `109.173.40.247:51830`. Exclusive `.attempt` receipt retained. No persistent
WireGuard config edited, no interface bounce, no other peer changed.

Console readback: handshake established, 2/2 pings to 10.250.0.1 passed, ~45ms.
Full private dump comparison verified unchanged interface identity, all five peer
identities/preshared keys, AllowedIPs/keepalive and all unrelated endpoints.
`/root/vps-bootstrap-20261109.accepted` records this limited acceptance; these
VPS-local preimages are NOT an off-VPS backup or full migration receipt.

### Controller recovery and route discrepancy — stop gate

NetBird daemon reported LoginFailed; safe config flags remained disableDns=true,
disableClientRoutes=false, disableServerRoutes=true. No login/credential rotation
or NetBird restart attempted. Existing standalone `wg-socrat-admin` activated as
an explicit emergency fallback, NOT NetBird acceptance. Revoked `socrat-assistant`
profile was not activated. Internal TCP2222 subsequently open at .1/.3/.5; .2 still
timed out (imported recovery profile VPS endpoint not yet updated).

Private Mac baseline is under the existing migration controller directory,
`mac-recovery-20261109/baseline.json` (0600). After fallback activation, sampled
internet gateway/interfaces, OpenVPN process IDs and full scutil DNS hash were
unchanged. No corporate VPN/default route/global DNS changes made.

CRITICAL: read-only probes through the old CROOT/bin/ssh wrapper unexpectedly used
its stale public HOME mappings and socrat-3 ProxyJump. Actual SSH_CONNECTION and
subsequent ssh -G established this; these are NOT private SSH acceptance. No remote
writes were made through that path; wrapper use stopped once discovered. Do not
reuse run-private-node.py/CROOT wrapper unchanged for further work. Ordinary
/usr/bin/ssh aliases currently resolve to exact 10.250.0.1/.3/.2/.5:2222, retained
host-key aliases and strict checking, without ProxyJump. Further fresh SSH and
mandatory playbook execution must explicitly use the approved internal path;
prior assumptions that the wrapper itself guaranteed private access are invalid.

Those read-only observations showed k3s activating on both home servers, Kubernetes
API access failing, and etcd/leader/timeout journal classifications; socrat-1 SSH
reachable is NOT evidence it is Kubernetes Ready. No k3s/node/database restart,
cluster reset or membership change attempted. VPS k3s and k3s-agent inactive.
Control-plane recovery requires diagnosis and the existing restart/fencing gates.

Remaining: restore/verify controller private SSH to all four (including imported
VPS endpoint), diagnose control plane, review API-only migration adaptation,
repeat mandatory all-four preflight, then full host/source/GitOps/native API,
parent glue, subscription/client delivery and authenticated external acceptance.
No publication/panel/native fallback ownership changes in this recovery step.

### 2026-11-09: owner-authorized direct NEW-IP SSH supersedes access block

Owner explicitly instructed to stop touching WireGuard and connect by IP. No
further Mac profile edits/imports/toggles performed. Direct `/usr/bin/ssh` to
`109.120.141.60:2222`, using socrat-2's existing identity, retained host-key alias,
StrictHostKeyChecking=yes and ProxyJump=none succeeded: hostname socrat-2, uid1003,
SSH destination109.120.141.60:2222. No host-key replacement or public fallback to
OLD. This specific public management path is now owner-authorized; it is not
claimed as private-mesh acceptance.

Ordinary direct aliases also verified fresh private SSH on socrat-0/1/3, all
source10.250.0.4 to exact respective internal IP:2222, without jump-host. This
supersedes the earlier wrapper-based, incorrectly classified SSH observations.
The stale CROOT wrapper remains unused and unmodified.

Mandatory playbook actually rerun apply=false, all four nodes, no --limit,
ANSIBLE_SSH_EXECUTABLE=/usr/bin/ssh and private inventory override ONLY socrat-2
ansible_host=NEW. Private audit directory:
`direct-ssh-audit-20261109T090637Z/` under existing controller migration state.
All unreachable=0, changed=0; controller source audit passed. VPS preflight
stopped at inactive affected-native-service gate, not SSH/authentication.
No apply attempted, no source/DB/zone/service mutations by this audit.

Read-only direct SSH established:
- Persistent /etc/network/interfaces already has NEW, netmask255.255.255.0 and
  gateway109.120.141.1; this is readback, not an assistant NIC change or reboot test.
- knot active/running; backend guard active/exited.
- wireguard-tcp-transport activating/auto-restart; guard inactive/dead.
- k3s/k3s-agent inactive/dead; / and /srv on same40G volume,15G available.

Review the transport's exact failure/old listener binding before any correction;
never activate its dormant guard blindly or conflate Mac-profile prohibition with
permission to mutate server WireGuard. Full migration still requires service-state
review and API-only panel adaptation before apply, plus all acceptance gates.


## 2026-11-09: host apply, reboot recovery and functional VPN acceptance

The approved all-four-host audit/apply completed using `/usr/bin/ssh` and an
explicit private inventory override **only for the owner-authorized direct new
VPS IP**. Owned source/native references were migrated; the reviewed dormant
WireGuard TCP guard remained dormant. Production panel SQL migration was
removed: SQLite is read-only audit/online backup only; native API owns writes.

Before controlled failback, both fenced K3s/native ownership states were checked
under the existing failover lock. Offline etcd/config preimage:
`/var/backups/homelab-vps-ip-migration/recovery-before-failback-20261109/etcd-offline.tar.gz`,
111723007 bytes, SHA256
`589fbc8eb43790a39e329a82ab3bcbd5b899eeb9f3958f68f59f4e63e93ba5e3`.
This is on-VPS preservation, **not off-host DR or restore acceptance**.
The existing failover CLI performed one controlled failback; no raw K3s start,
etcd reset, membership edit, database deletion or blanket Argo sync/prune.
Initially all four nodes/pods became Ready while watchdog health remained false;
that was **not usable-VPN acceptance** and the owner still reported failure.

The owner subsequently rebooted VPS (assistant did not reboot). Fresh checks
confirmed persistent eth0 `109.120.141.60/24`, gateway `109.120.141.1`, K3s active,
all four nodes Ready and VPS workloads Ready. Native fallback stayed inactive;
watchdog then reported `mode=kubernetes, healthy=true, inhibited=false`.

### Seven stale profile addresses corrected through native API

Native preview found seven exact OLD hosts.address rows. Fresh online preimages,
pinned workload/version checks, approval hashes and one-shot uncertain receipts
were used. The first two calls stopped on previously unmodelled **native codec
normalization**, not on lost credentials or missing clients: native updated_at,
nullable false -> 0, and empty SNI pool -> the same explicit single SNI. Each was
read back, semantically verified and separately reconciled; **neither call was
replayed**. Fresh states then targeted only remaining OLD rows. Final five-row
apply succeeded after regression tests were extended for those bounded effects.

Final current hosts: seven NEW, zero OLD. All 16 identities and 85 bindings,
original inbound credentials/settings/quotas and disabled legacy32063 were
preserved. Native admin worker was TTL-limited, cleanup verified no temporary
tokens remain. No panel pod/native VPN restart was required for host metadata.
Private states: `/var/lib/homelab-vpn-hardening/vpn83-ipmove-20261109{a,b,c}`;
original uncertain attempts remain as evidence beside reconciliation receipts.

Generated subscriptions were checked for all 16 enabled identities using both
backend and public TLS ingress **pinned per-process to NEW**: URI 78 entries,
JSON 72 entries; each public/backend pair equal, OLD absent, NEW present.
Evidence: `/var/lib/homelab-vpn-hardening/ipmove-subscriptions-20261109/receipt.json`.
Do not confuse 85 retained bindings with published entry counts/formats.

An owned temporary identity authenticated from HOME fixed WAN, actual source
`109.173.40.247`, to **literal NEW** for both REALITY and Trojan/TLS443, each with
HTTP200 and 65536 bytes. The public route used eno1 via 192.168.0.1, not overlay;
TLS SNI/Host remained the original hostname and certificate validation stayed on.
Main routes/resolv.conf unchanged. Fixture and temporary tokens removed; original
proxy config preserved. This is **not Russian mobile acceptance** or a guarantee
against filtering. Evidence on HOME:
`/var/lib/homelab-vpn-hardening/vpn83-home-ipmove-20261109/receipt.json`;
VPS cleanup: `vpn83-ipmove-home-20261109/home-session-cleanup-receipt.json`.
The owner must refresh the subscription and verify their actual mobile path.

### Telegram restored without duplicate mailing

Fresh getWebhookInfo proved both runtime env and Telegram destination still OLD,
with two pending updates. NEW public webhook GET returned405 with TLS verify0
(expected POST-only route). Existing machine token and webhook secret were
ownership/digest-checked against the running pod. One native setWebhook changed
**only destination IP**: original URL, secret, allowed_updates, max_connections
preserved, `drop_pending_updates=false`. Readback destination NEW, queue0; no
new broadcast command was sent. Queue0 proves Telegram delivery/ack, **not that
all recipients received the original mailing**. Runtime env still needs durable
GitOps reconciliation to avoid reverting on the next bot restart.
Private proof: `/var/lib/homelab-vpn-hardening/bot-webhook-ipmove-20261109/receipt.json`.

### Registrar accepted; parent publication pending at last readback

REG.RU domain109979518 custom NS list was reviewed and submitted once:
ns1.alchemmist.xyz=109.173.40.247 unchanged; ns2.alchemmist.xyz=109.120.141.60.
UI confirmed DNS servers changed, both names preserved; no registrar-DNS move.
Direct x.nic.xyz and y.nic.xyz queries immediately afterwards still returned
OLD ns2 glue. Do not resubmit merely because publication/cache is delayed.
Registrar acceptance is not parent-zone acceptance; recheck both authorities.

Focused regression suite: 160 passed +21 subtests. Original unrelated dashboard
and metrics-template work must remain outside the migration commit. Remaining
acceptance: durable GitOps runtime refs (especially bot/STUN/edge IP), parent glue,
Collector delivery, owner/mobile confirmation and original mailing completion.
Mac WireGuard and corporate Tunnelblick/global routes/DNS were not modified in
this recovery segment. NetBird workstation LoginFailed is not claimed resolved.
