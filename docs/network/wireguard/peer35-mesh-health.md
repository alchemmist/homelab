# Worker 3 to node 5: transport and acceptance

Both endpoints are behind NAT. Do not pin an observed WAN source port as an ingress endpoint. Node 3 had no learned endpoint for node 5; node 5 was repeatedly pinned to a historical mapping for node 3. Before repair only these two directed paths failed. The individual NAT device responsible was not established.

The private UDP relay on node 0 forwards unchanged WireGuard ciphertext between fixed peers. Node 5 sends to `10.250.0.1:51837`; node 3 sends to `10.250.0.1:51838`. Both reach node 0 through their independent WireGuard peers. No public port, private key, route, or AllowedIPs expansion is needed. This transport depends on node 0; it is not independent failover.

Install the relay and per-node measurement with `ansible/playbooks/wg-mesh-health.yml`. Install the relay before applying the endpoint inventory to nodes 3 and 5. If reverting, establish and verify an alternate path before disabling the relay. Local pre-change WG configuration is root-only; do not print it. The existing endpoint pin timers enforce the new persistent settings without restarting WG.

Every minute, each host pings every other inventory mesh IP through `wg-socrat`. The node exporter textfile collector publishes `socrat_wg_mesh_reachable{source,target}` and `socrat_wg_mesh_checked_seconds{source}`. Zero means all three attempts failed. `SocratWireGuardPeerUnreachable` detects a persistent directed failure; `SocratWireGuardMeshProbesIncomplete` detects missing or stale coverage. Adjust the expected topology in the Prometheus rule when admitting or retiring nodes. The probe does not test every application protocol or guarantee WAN availability.

For incident acceptance also test larger DF pings both ways and establish PostgreSQL TLS from a Schoolbot-labelled diagnostic Pod on node 3 through the RW Service. Keep diagnostic Pods outside the application Service selector and delete them afterwards.
