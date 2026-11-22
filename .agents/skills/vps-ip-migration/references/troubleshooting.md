# Troubleshooting: verify a hypothesis before changing anything

Use existing private access. Start read-only, identify the owner and make the smallest justified change. Do not publish raw connection logs, request bodies, usernames, credentials or user IPs. Prefer short observation windows and aggregate counts over a full `kubectl logs` dump.

## 1. NEW is unreachable externally

- Verify actual address assignment, source route, listener (`ss`) and the owner of persistent network configuration. An unassigned address is a provider issue, not an application failure. Do not guess the gateway or netmask.
- Compare TCP connectivity from home, mobile, an independent network and the VPS itself. A hairpin tests the process, not external ingress; ping tests a different protocol.
- Use a short, bounded capture on the external interface. Count inbound SYN and outbound SYN-ACK packets without collecting payloads or printing client addresses. No inbound SYN suggests an upstream/path issue; SYN without a reply warrants checking the local firewall, listener and routes. SYN-ACK without ACK can indicate a return-path problem; it does not prove provider filtering.
- Check counters on the specific nftables/iptables rules, kube-proxy and policy owners. `ufw inactive` does not mean no firewall rules exist. Do not flush rules or allow all traffic.
- If results vary by network, record the regional or path-specific failure. Changing ports is a separate, approved test; the server must also listen on the test port.

## 2. TLS connects but HTTPS stalls

- TCP reached the address. Check the ingress route, Service, EndpointSlice, backend readiness and a direct internal request. Is the backend reachable over the mesh?
- Compare persistent and runtime WireGuard endpoints, handshake ages and counters on both sides. One node may still have a working channel while the application worker uses OLD.
- Check the VPS TCP transport bind, the client destination, guard counters and the relevant backend route. Do not restart Kubernetes to diagnose a mesh problem.
- If only large responses stall, investigate MTU/MSS and retransmissions. Do not change MTU across all nodes based on one timeout.

## 3. DNS points to the wrong address or resolvers disagree

- Compare `/etc/hosts` and `getent`, the configured resolver, both child authorities, parent glue and Google/Cloudflare DoH separately. `getent` may use a local override.
- A home-network `dig @8.8.8.8` can be intercepted. An unexpected `aa` flag or TTL and disagreement with DoH warrant another observation point, not an assumption of propagation delay.
- During a partition, independent health-based renderers may publish different A records. Identify which probe failed and why. Do not pin every name to the home IP, especially for non-HTTP transports.
- Child A = NEW and parent glue = OLD means the registrar stage is incomplete. Parent = NEW and recursive = OLD indicates caching; record the TTL. Do not disable the second nameserver on a guess.

## 4. The VPN client says connected but passes no traffic

- Check the selected profile, literal destination after refresh, protocol, port, SNI, WebSocket path and the specific client's expiry and quota. Do not include identifiers or credentials in the report.
- Compare another site, Wi-Fi versus mobile and Global versus rules mode. These are diagnostic tests, not permission to change the user's policy permanently.
- Test VPS egress and an authenticated external tunnel separately. Working egress does not prove tunnel delivery. One working Trojan profile does not verify VLESS or WireGuard.
- If subscriptions still advertise OLD, inspect all tables in the active database, `hosts.address`, share-address and host-mapping sources, and the actual mounted database path. Looking only at settings and inbounds misses hosts. Do not restart the panel a second time on a guess.
- After the address migration, verify exact database invariants, determine whether the specific panel needs a reload, then check all plain and JSON subscriptions. If the file has NEW but the client still uses OLD, refresh the subscription or correct the manual endpoint; do not reissue everyone's credentials.

## 5. The site opens but sign-in, the bot or object storage fails

- HTTP 200 may be only a login page. Verify the expected authentication redirect host and path, then check the application's access to Authentik, the token endpoint and policy egress.
- RustFS storage and the identity gateway have separate NetworkPolicies. A stale `/32` in either can break callbacks while the public page remains reachable.
- A Telegram webhook URL and its pinned IP are separate. Check `getWebhookInfo` from the VPS, pending count and age of the last error. The home network may block the API request itself. Do not repeat publication or a side-effecting operation as a health probe.
- The NetBird listener may use NEW while the Secret still advertises OLD. Inspect effective configuration and reload state; do not change node identities or ACLs.

## 6. The dashboard stays red although NEW works

- Check the instance on a fresh `probe_success` sample, the job owner and sample age. Changing a ServiceMonitor alone does not update a target in the saved Collector bundle.
- If NEW reports 1 but OLD is still firing, check the last sample, rule evaluation and lookback expiry. Do not delete a series to turn the panel green or treat stale data as a current pass.
- Collector failures or growing queues are stop conditions. Compare deltas per exporter and pipeline, not just the aggregate queue: its unit may be bytes or requests. Distinguish resource exhaustion from a transform syntax error. Do not increase memory without evidence. Inspect sanitized error classes, not raw bodies.

## 7. The playbook fails or the schema has drifted

- Keep stdout counts and the private receipt. **Do not retry apply automatically.** Determine which sources, files and databases changed and which native units have not reloaded.
- Do not repair an unknown schema with SQL replacement across all TEXT columns. Identify the supported owner or API, or separately review changes to the allowlist and invariants.
- Never restore an old database wholesale over new live data. A preimage supports comparison or targeted recovery, not loss of later writes.
- After manual recovery, retain evidence and the original receipt, explicitly record the reconciled state and only then audit again.

## 8. An SSH alias fails after migration

Normal `socrat-N` aliases must use private mesh IPs, without `ProxyJump` or public SSH. Redirecting an alias to the home IP or public VPS does not repair the internal network. A recovery alias is only a temporary management path during diagnosis.

Check `ssh -G`, Mac host routes, the active **imported** WireGuard profile, the VPS endpoint and coverage of worker `10.250.0.5/32`. Verify the reverse peer route and narrowly scoped forwarding ACL. Fix the VPN at its source of truth; do not create another SSH bastion. See `docs/network/netbird-tunnelblick-coexistence.md` for primary NetBird access and `docs/auth/host-access/mac-private-ssh.md` for standalone WireGuard recovery. Verify the interface of the selected transport; a different VPN working is not a pass. NetBird uses the existing masquerading routing peer. Source `.4` applies only to standalone WireGuard, not NetBird acceptance. Keep Tunnelblick running: NetBird does not manage DNS and accepts only the four selected `/32` routes.
