> **Source preservation update:** source changes are now committed locally as
> 08c4534 (transport), c60b16d (NS3) and40ddc42 (watchdog); no push.
> [Current network audit](network-dependency-audit-20261112.md) supersedes dated
> pending/NotReady/uncommitted observations retained below as history.

# Moscow relay/watchdog recovery — 12 November 2026

## Accepted result

At13:13–13:14UTC all six nodes Ready; Moscow agent active, single
vpn-transit-655857b776-w76zq relay Pod1/1Running. Controller reports
mode=kubernetes, healthy=true, failures=0, agent_active=true,
native_active=false, fallback_marker=false, data_path_healthy=true.
Fresh Thanos kube_node_status_condition Ready/true for4 returned1, age4.68s.
Authoritative Moscow DNS still responds via public UDP/TCP53. Private DNS and
management relays remain active. No node, WG or control-plane restart.

## Evidence and cause

At07:31:54UTC (10:31MSK) four consecutive real data-path probe failures caused
vpn-transit-failover.py to write fallback.active and fence k3s-agent. Native relay
started07:31:55UTC but was not healthy within activate()'s bounded probe loop;
the controller raised AssertionError07:32:55UTC before persisting mode=native.
The native relay later recovered. Its state remained transition-to-native while
regular ticks updated only healthy=true. The marker intentionally kept the agent
fenced; explicit failback required mode=native and therefore could not proceed.
This is a controller state-reconciliation defect, not DNS installation failure.
The initial reason for the VPN data-path failures is not yet established.

Pre-stop agent logs independently show API192.168.0.23:6443 timeouts; the LAN
address routes out public eth0. API10.250.0.1/3:6443 were reachable before
recovery. The agent's existing LB file already contains both mesh addresses.
No endpoint/route/AllowedIPs changes were made. Recovered agent connected to
both mesh endpoints. LAN advertisement remains separate technical debt; it is
not proven to have caused the VPN probe failures.

Node5's earlier ReadyUnknown was separate: k3s-agent remained running
NRestarts=0, same process since10November; bounded journals show API/LB request
failures and reconnection to mesh endpoints at11:26:36–40UTC. It recovered Ready
without intervention by this session. Underlying transport failure not determined.

## Repair

Source ansible/scripts/vpn-transit-failover.py now reconciles ONLY a fenced
transition-to-native after native is active, actual data-path probe passes,
agent is inactive, and existing binary/management/route prerequisites pass.
It writes a native-reconciled receipt and persists native/healthy/failures0.
No activation replay, listener change, fence removal or agent start occurs during
reconciliation. Unhealthy/unknown states remain fenced; active-agent conflict
and prerequisite drift refuse reconciliation. Explicit failback remains required.

Live source matched expected old SHA256
8496ffbfd85a910136b4cce0682a0349adf36f38b8f567323f520b8d69ae5b10.
Fresh exclusive root0700 snapshot directory:
/var/lib/homelab-recovery/20261112-vpn-transition-repair
contains old script, state and marker. Candidate compiled and old source hash
was rechecked before atomic Ansible copy. Installed source SHA256:
3f130631c493cf60feed9cc5dd1ee970b233c278fb9cf685a00f32e915f03d19.
A tick reconciled to healthy native without restarting its process. Then the
existing explicit failback action stopped native before releasing the fence and
starting the agent. Existing bounded rollback remained in place. Failback rc0;
new Pod healthy; accepted Kubernetes mode, old terminating Pod removed normally.
There may have been a short VPN interruption during handoff; zero downtime and
all authenticated client transports were not measured or claimed.

Tests:51passed+2subtests across transit and VPN failover suites; new cases cover
late health/idempotent reconciliation, unhealthy states, agent conflict and
prerequisite refusal. No production failure injected. Credential file removed.
Source/docs changes remain local uncommitted; no push/blanket Ansible replay.

## DNS closeout

At13:03UTC x.nic.xyz returned all3NS plus exact parent glue for
ns3.alchemmist.xyz=91.189.82.238, TTL3600. This supersedes earlier parent-propagation
pending notes. No third general web A publication was performed.
