# Traffic Light: native Moscow and direct HOME IP checks

> **Correction: original direct-NL inference below is withdrawn.** OUTPUT DNAT
> still sent the original exporter through Moscow. Corrected UID19091 exemption
> and v2 measurements now show NL TCP443 timeout from HOME, HOME/Moscow success.
> See [correction and fallback gates](vpn-home-fallback-20261113.md). Route lookup
> alone was not direct-egress proof. Historical acceptance below predates this fix.


> **Later correction:** socrat-4 has been returned to Kubernetes at owner request.
> Panel926 again uses real Kubernetes readiness; the direct-IP checks below
> remain current. See [worker return](moscow-worker-return-20261113.md).

## Contract corrected on13November2026

- Panel926 (digit4) no longer asks Kubernetes for a removed worker. It reads
  native node-exporter up, memory and root filesystem metrics for socrat-4.
  Green=fresh up1 and >=10% available memory/root space; orange=below10%;
  red=fresh exporter up0; grey=missing/stale required telemetry. CPU contention
  remains a separate, unchanged alert, just as for the other node cubes.
- Panels905/906/928 (Home/VPS/Moscow IP) read ONLY public-ip-probes from
  probe_observer=socrat-0, probe_path=direct-home-wan. Fresh TCP failure turns
  red immediately; stale/failed collection is grey. No VPN/application alert or
  Kubernetes service-probe state may override these cubes.
- Geometry, panel IDs, TV styles/scripts, auth, public-dashboard policy, existing
  service/VPN probes and their alert rules are unchanged.

## Measurement path

A stock blackbox exporter runs hostNetwork on HOME0, source192.168.0.23, with
only literal public IPv4 TCP443 targets. It uses the host network namespace,
not a Flannel source pod. At acceptance the host has only local/main/default
policy rules; `ip route get` for NL/Moscow resolves via192.168.0.1 dev eno1,
not wg-socrat, NetBird or a Moscow proxy. Source LAN binding is explicit.
Route changes require revalidating this assumption; no destructive tunnel-off
experiment was performed.

The exporter HTTP endpoint binds only private LAN192.168.0.23:19116, not a public
address/wildcard. Non-root, all capabilities dropped, read-only filesystem,
no API token, no credentials, no new public forwarding. Recreate strategy avoids
host-port collision. The existing TV OTel metrics sidecar is the sole scraper of
these three new jobs and forwards with its existing client mTLS certificate and
existing metrics pipeline. Its config checksum triggers a bounded rollout.
Only one narrow private LAN /32 TCP egress is added to that sidecar's policy.
No native agent restart, duplicate owner for the old service-probes job, new
monitoring backend, ICMP raw capability or VPN setting is needed.

The old service-probes exporter was already pinned to1 with literal public
TCP targets. There is NO evidence its config explicitly proxied these targets
through Moscow. Its historical failure must not be re-described as proof of
VPN coupling. The new independent measurement and labels make the desired
contract explicit; they do not retrospectively establish why a path failed.

## What green does and does not prove

Green means TCP443 accepts from THIS Russian HOME ISP. It is not a statement
about every Russian ISP, all ports, ICMP, DNS, TLS, authenticated VPN or internet
exit. The Home IP check traverses the router's hairpin path, not an external
internet viewpoint. Service and VPN tiles remain separate.

At05:42–05:44UTC, direct host checks from0 AND1 reached NL TCP443 via their
ordinary HOME router. NL ICMP did not answer, and public TCP2222 timed out.
Therefore a blanket claim that the VPS IP is blocked from Russia is unsupported:
HTTPS-port TCP reachability works from HOME; other protocol/port availability
is different, and filtering location/cause is not established. Using ICMP alone
as a red/green IP verdict would have incorrectly hidden this distinction.

## Validation / rollback

New tests evaluate the actual four panel expressions with promtool, including
native healthy/pressure/down/missing/stale/zero capacity and direct success/
failure/missing/stale/collector-down. Firing old edge/VPN alerts cannot override
a direct green; old in-cluster metrics cannot fabricate direct telemetry.
Helm tests verify host network/source/observer/three literal targets, non-root
security, retained existing jobs and existing authenticated OTLP.

Runtime acceptance must additionally verify the exact Argo revision, Ready
probe/sidecar, three fresh direct series and the provisioned Grafana model.
Physical TV refresh is separate: an already-open page may retain the old model;
a metric refresh is not a dashboard-model reload. Do not claim visual acceptance
without viewing that TV.

Rollback: revert this scoped source change through GitOps. The old service-probes
and native host telemetry remain intact. No PVCs, runtime credentials, native
agent configs or VPN state are modified by this change.

## Accepted runtime at06:01UTC

Published source bb5b1e05; Argo monitoring-k3s Synced/Healthy at that exact revision,
operation Succeeded. The direct exporter is1/1Ready on0, hostIP192.168.0.23;
existing TV activity/metrics pod rolled to2/2Ready. All three direct probe_success
and collection up series are1 with the expected observer/path/target labels.
The provisioned Grafana API model matches all four new expressions and all63
panel geometries are unchanged. Actual panel queries905/906/926/928 all returned0
(green). Direct exporter checks returned1 for all three addresses, including NL.
The original source's alert-based service probes/rules remain intact.

56focused tests passed, plus the existing promtool traffic-light rules suite and
Helm lint. Only monitoring Deployment/ConfigMap/policy source changed; no native
agent, VPN, control-plane or storage operation was performed.

Physical TV not visually accepted: the existing socrat-0 user ADB server listed
no connected devices. Did not reconnect/reset ADB authorization, change TV
preferences, import settings or restart another foreground app. The already-open
TV page needs an ordinary refresh to load the new dashboard model.
