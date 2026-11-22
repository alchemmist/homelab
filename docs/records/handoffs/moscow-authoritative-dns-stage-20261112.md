> **Source preservation update:** source changes are now committed locally as
> 08c4534 (transport), c60b16d (NS3) and40ddc42 (watchdog); no push.
> [Current network audit](network-dependency-audit-20261112.md) supersedes dated
> pending/NotReady/uncommitted observations retained below as history.

> **Live update, 12 November 2026 11:28 UTC:** staged Knot is installed and enabled.
> Exact additive ns3 NS/A publication was applied on0/1/2/4 with per-host
> preimages and common approved plan23877b32aeda112b0a0eb9c25d593045a2428e8704c95390ed529ab34902ceaf.
> REG.RU explicitly confirmed “DNS-серверы изменены” on the second attempt,
> after the first request failed and fresh readback proved the old desired set.
> Parent delegation propagation is separately pending verification below.
> Historical prepared-only/sudo-blocked status below is superseded.
> Current renderer includes ns3; the stage play does not update other authorities.

# Moscow authoritative DNS — staged source, not deployed (12 November 2026)

## Status

Owner authorized work on an independent third authority and NL recovery access.
The new authority is **not installed, not delegated and not publicly accepted**.
REG.RU still delegates only ns1 HOME109.173.40.247 and ns2 NL109.120.141.60;
the .xyz parent independently returned those two NS/glue pairs, TTL3600.

Read-only live preflight of the new play passed:8ok,0changed. Four new offline
safety tests plus existing renderer/SPI tests:22passed,10subtests passed.
Ansible syntax-check passed. The controller's usual Python and old temporary
pytest environment lacked pytest; final successful run used isolated uv packages.

## Existing dependencies and access

- Moscow91.189.82.238 has no Knot package and no public53 listener. Existing
  TCP/UDP10.250.0.40:53 is the fixed NL DNS relay and must remain untouched.
- New Knot must bind **only91.189.82.238:53**, serve a local zone from disk,
  and run as host systemd, not a Kubernetes pod or query-time NL forwarder.
- Existing renderer periodically probes HOME/NL443 and independently chooses
  addresses. Its known partition/freshness limitations remain; staging does not
  add Moscow to web A records, publish ns3 or solve DNS/web failover.
- Public SSH to0/1/4 works. Native NetBird100.100 IP SSH to0/1/3/5 works.
  Ordinary mesh aliases3/5 time out from Mac. NL public22/2222 and native NB IP
  did not connect; authenticated NL SSH through Moscow to10.250.0.2 works.
  NetBird host agents run in Kubernetes, management on0: not an independent DR
  control plane. Provider NL console has historical acceptance but no current
  verified session; provider portal URL/session is still needed.
- Fresh snapshot:6Ready, pressure conditions false, APIreadyz passes. Fresh etcd
  leader metrics1 on all3 voters (age1–4s). This is not same-revision hashKV or
  restored-snapshot integrity proof. n8n/LMS CronJobs have today's successful
  runs; backups were not downloaded/restored in this phase.
- Forced-IP verified-TLS wiki/LMS requests: HOME200/303, Moscow200/303, NLtimeout
  from Mac. This is not independent mobile/global reachability or failure testing.

## Prepared code and safety boundaries

`ansible/playbooks/moscow-authoritative-dns-stage.yml` is a **one-time fresh-host
stage**, not an existing-authority reconciliation command. Default read-only;
explicit apply flag plus exact current local renderer SHA256 are required.
Preflight refuses existing Knot, public/wildcard53 collision, missing internal
relay, wrong host/OS/public IP. Shared role adds optional package-autostart
suppression, configuration validation and backup; defaults preserve old behavior.
Debian `policy_rc_d=101` prevents package post-install starting an unconfigured
wildcard listener. Config is validated before installation; only Knot is started
or restarted. Existing internal relay, WG, Kubernetes, DNS delegation, original
zone renderer records and web-address selection are not changed.

The play does not change firewall rules. If an existing host/provider firewall
blocks public53, investigate and prepare a narrow separately reviewed rule;
do not flush rules or broadly replay firewall roles. A failed/partial install is
**not** safe to blindly replay: inspect package, service, listener and candidate
state first, because the fresh-host guard intentionally refuses existing Knot.

## Reproduce read-only preflight

Use the existing trusted SSH alias, not stale inventory HostKeyAlias overrides:

```sh
cd ansible
ansible-playbook playbooks/moscow-authoritative-dns-stage.yml --check \
  -e ansible_host=socrat-4 \
  -e 'ansible_ssh_common_args="-o ProxyJump=none -o StrictHostKeyChecking=yes"'
```

The inventory's IP target plus HostKeyAlias=socrat-4 did not match the pinned
alias key store; attempts correctly failed host verification before mutation.
Using the normal alias loaded its existing strict pins; no keys were accepted,
trust checking disabled, SSH config changed, or known-host files modified.

## Apply gate: interactive sudo required

`sudo -n true` on Moscow fails. Do not put passwords in chat, tracked vars,
argv or logs; do not enable broad NOPASSWD. The operator can perform the apply
from their local interactive terminal using normal `--ask-become-pass`:

```sh
cd ansible
sha=$(shasum -a 256 scripts/public_dns_zone.py | awk '{print $1}')
# Review the diff and matching preflight digest before this command.
ansible-playbook playbooks/moscow-authoritative-dns-stage.yml \
  --ask-become-pass \
  -e ansible_host=socrat-4 \
  -e 'ansible_ssh_common_args="-o ProxyJump=none -o StrictHostKeyChecking=yes"' \
  -e moscow_dns_apply=true \
  -e "moscow_dns_approved_renderer_sha256=$sha"
```

## Acceptance BEFORE registrar mutation

1. Knot config/zone status, active internal relay, explicit public listener only;
   review boot enablement/dependencies and service resource use.
2. Authoritative SOA/NS/A and NXDOMAIN over UDP **and TCP53** from HOME and a
   genuinely external vantage; no recursion/open-resolver behavior. Test after
   scoped Knot restart only once independently managed access is available.
3. Verify answers are served locally, not forwarded to NL; existing relay unchanged.
4. Separately prepare exact additive ns3 NS and A changes for all authorities,
   preserving every other record for all four existing health states, with fresh
   private preimages/hash approval and serial refresh. Do not rerun the full
   public-authoritative-dns play on existing0/1/2 for this addition.
5. Only after zone consistency and reachable Moscow authority, add
   ns3.alchemmist.xyz /91.189.82.238 to REG.RU NS/glue and verify parent and
   independent resolvers. Rollback delegation first; allow caches to expire before
   removing any delegated authority. DNS caching still prevents instant web failover.
6. Third web-IP publication/health selection is separate work, not part of stage.

Existing uncommitted incident recovery edits in the WG/GOST template and Moscow
management relay config were not changed by this work. No commit/push/apply or
REG.RU write has occurred.

## Live acceptance and remaining problems

- Package/install play:24ok,9changed,0failed. Existing DNS relay stayed active.
- Both TCP/UDP authoritative SOA passed from Mac and HOME. NXDOMAIN is
  authoritative; example.net recursion is REFUSED/noRA on both transports.
- NL-to-Moscow TCP53 passed; NL-to-Moscow UDP53 timed out. This partial path
  problem is unresolved, not a claimed global DNS acceptance. No firewall policy
  was weakened. Native nft executable absent; iptables INPUT policy inspected.
- Knot/public-dns-refresh.timer enabled; Knot memory approximately5.7MB. Explicit
  public IP listener and local zone: no WG/Kubernetes startup dependency added.
- Guarded fleet addition used ansible/scripts/ns3-public-dns.py and
  ansible/playbooks/ns3-public-dns.yml. Only the two exact records may differ
  across all four existing health combinations. Fresh approved hash validated on
  every host before serial apply;0/1/2/4 receipts confirm NS and A in Knot.
- Google and Cloudflare DoH both returned three in-zone NS names; this does NOT
  prove parent glue is updated. Parent was still two names at11:24UTC.
- Source tests:24passed+10subtests. Ansible syntax passed. No web-A addition.
- A later health check found4/5NotReady.4 last heartbeat07:28:29UTC,
  ReadyUnknown07:32:43UTC, k3s-agent clean stop07:31:54UTC, well before DNS install
  ~11:19UTC. Pre-stop logs show API192.168.0.23:6443 timeouts.5 last heartbeat
  11:17:54UTC, ReadyUnknown11:21:26UTC. No causal attribution for5 is established.
  No agent, WG or cluster restart was performed. Current health is NOT6Ready.
- NL provider console still requires operator portal URL/session. No forced
  reconnect, outage injection or provider setting mutation was done.

REG.RU readback at11:29UTC confirmed all three exact NS/glue pairs. Parent
readback at11:28:39UTC still showed two; propagation remains pending. The
local mode0600 credential file in a0700 directory was removed after Ansible.
No credentials were added to Git, command-line extra-vars, or documentation.
