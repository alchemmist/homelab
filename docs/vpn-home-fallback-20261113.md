# HOME VPN fallback: inspection, probe correction and remaining gates

> **Abandoned by owner:** no HOME/direct-NL/node5 user fallback. The current
> target is fixed Moscow→NL with K3S/systemd runtime recovery only. See
> [current readiness and monitoring](vpn-runtime-readiness-20261113.md).


## Owner's target, not deployed failover

Primary client→Moscow4→NL; backup client→HOME0→NL, automatic return after stable
Moscow recovery. Kubernetes/systemd execution is a separate axis. Keep4 a worker.
Direct client→NL is NOT an automatic fallback. Composite mode must distinguish
K3S normal vs K3S HOME reserve, OS, positively proven OFF and missing NO DATA.
No client/profile/DNS failover or new production tunnel was enabled in this step.

## Important correction: earlier direct NL claim is withdrawn

The earlier assertion that HOME0/1 TCP443 proved direct NL reachability was wrong.
Host route lookup and literal destination do NOT account for OUTPUT DNAT.
The existing `homelab_msk_home_egress` table rewrites literal NL TCP443 to Moscow,
in OUTPUT and PREROUTING. Existing user traffic intentionally retains that rule.
Therefore the previous public-IP exporter, despite hostNetwork and LAN binding,
was also measuring the Moscow detour. The defect was in measurement design, not
proof that filtering happened or that NL rebooted. Authenticated tests through
literal Moscow remain valid; their destination and purpose were different.

### Applied correction

Source f1163873/45841353:

- Reserved locked nologin account/UID19091 on HOME0 for stock public-IP exporter.
- CAS-migrated ONLY HOME0's owned OUTPUT chain: literal NL TCP443, UID19091,
  counter+return before the existing DNAT. No PREROUTING exemption, broad prefix,
  ordinary-client exception, mark collision or table/ruleset flush.
- Checked complete old counter-independent projection against private receipt,
  exact old source+SHA, exact inserted expression and equality of all other rules.
  Saved root-private before-state; updated source/projection/acceptance for boot.
  Canonical helper installed only after accepted migration. Other HOME hosts and
  ordinary VPN/management traffic unchanged. Never blindly replay upgrade.
- Stock exporter runs UID19091; scraper and cubes require new provenance label
  `probe_path=direct-home-wan-v2`, so old detoured samples cannot masquerade as
  corrected direct measurements. Existing sole OTel scraper/mTLS retained.
- Direct bypass counter0→1 during dedicated UID TCP test; later81 with periodic
  exporter. Source-level route remains HOME router/eno1. Source f116 migration
  receipt accepted, egress service remains active; no WG/control-plane restart.

Corrected live results: HOME TCP443=1; Moscow TCP443=1; NL TCP443=0.
A dedicated UID socket to NL timed out. This establishes failure from THIS HOME
vantage at that time, not all-Russia/global blocking or proof of TSPU attribution.
Provider/external filtering localization is still open.

## Independent transport investigation

A source-restricted, fixed-shape UDP diagnostic was staged on NL public51843 for
at most40s and sent from HOME LAN. No matching response, no valid HOME datagram
reported. The responder exited and both temporary files were removed. No VPN
ports/services/firewall/default routes were changed by this test. This is a
negative diagnostic, not an authenticated WireGuard/VPN result; no broad firewall
allow was added to force success. NL INPUT/OUTPUT policy ACCEPT is not proof every
subchain/provider permits the packet.

Existing HOME0→node5→NL SSH path was verified with strictly pinned aliases and
WITHOUT Moscow in ProxyCommand. Node5's NL route is wg-socrat; its public NAT exit
was observed separately. This is an independently reachable candidate transport,
not a deployed user relay. A node5 socket to NL private443 was refused; existing
private-web/ingress ACLs must be reviewed, not disabled, before any VPN use.
Adding5 as a user-data transport dependency is a topology decision, not silently
represented as direct0→NL. No new provider or VPS was purchased.

External check from5: HOME TCP443/2222 connected;32053/32083/32084 timed out.
HOME0 had no listeners on the proposed VPN ports at inspection. These observations
alone do NOT distinguish missing port forwarding from absent listeners/filtering;
router mapping must be verified before advertising a backup to clients. Shared
HOME443 already serves infrastructure and must not be stolen by a new relay.

## Monitoring partial fix, not composite completion

Source db1263e6 changes missing/stale mode metric to -2/NO DATA rather than OFF;
positive native latch is labeled OS. Tests cover fresh0, fresh1, missing and stale.
The current latch still describes the NL backend, not all components or ingress
selection. The panel description explicitly states this limitation. OFF remains
reserved for proven total data-path failure, not fabricated from telemetry loss.
Do not claim the two-axis mode or HOME fallback is complete.

## Next gates

1. Decide whether an additional native transport via5 is acceptable, or require a
   different demonstrably independent0↔NL channel. Do not ship the failing public
   TCP/UDP test path as reserve, or use a Moscow-dependent route as fallback.
2. Verify narrow HOME router mappings and preserved shared443 behavior.
3. Prepare K3S/native relay with owned port fences and private exact-peer ACLs in
   both NL Kubernetes and native configurations. No blanket private ranges.
4. Establish authenticated HOME ingress tests, then client-compatible selection
   (existing literal-IP profiles cannot fail over by server-side DNS alone).
5. Add independently fresh runtime/route/data-path component telemetry, then
   automatic route hysteresis and stable-primary return. Only after that perform
   separately bounded failure tests, keeping etcd/PVC/management custody intact.

All6nodes and Moscow VPN1/1 remained Ready after inspection. Private escalation
file removed. Evidence retained privately; no credentials/user profiles/raw logs
published in this document.
