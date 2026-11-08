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
