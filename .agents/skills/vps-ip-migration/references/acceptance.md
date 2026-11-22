# Acceptance ledger: complete for every migration

For each row, record **passed / failed / unknown / not applicable (reason)**, the UTC time window and the observation point. Configuration alone is not a pass. If a required result is unknown, report the migration as incomplete or explicitly limit the claim to server-side work. Keep evidence private; commit only a sanitized summary.

| Check | Required result or evidence |
|---|---|
| Provider assignment and persistence | NEW is assigned to the VPS; source routing works; the owner of persistent network configuration is known. |
| Management | Private access remains available; direct SSH to NEW was verified using the existing pinned host key. |
| Repository | Allowlisted diff reviewed, targeted tests run, normal commit and push completed, remote revision verified. |
| Host phase | All four nodes audited; apply reviewed; private preimages and receipt retained; no partial failure. |
| Native services | Knot, TCP transport and guard in their expected active states; new binding; expected restarts only. |
| Mesh | Persistent and runtime endpoints point to NEW; required peers have fresh handshakes; no interface or key replacement. |
| Control plane and storage | Nodes Ready; identities and volumes preserved; neither etcd nor databases recreated. |
| Primary 3x-ui | Only intended `hosts.address` changes; consistent private backup; `quick_check` passes; credentials and IDs unchanged. |
| Retained legacy | Record whether the address was updated and database verified; dormant runtime **not started**. Do not automatically rewrite a historical database. |
| Panel lifecycle | Only the identified x-ui pod affected; Ready; subscriptions and tunnel retested after the last reload. |
| Plain subscriptions | All enabled subscriptions decoded, including base64/vmess; OLD count zero; NEW and other destinations classified; no errors. |
| JSON subscriptions | All enabled subscriptions return valid JSON; OLD count zero; no user identifiers or response bodies in evidence. |
| VPN from HOME | Authenticated tunnel to literal NEW, not a hostname or VPS hairpin; neutral HTTPS, Telegram and ChatGPT tested. |
| VPN from PHONE | Selected user profile refreshed; user verified Wi-Fi and mobile or explicitly recorded as pending. |
| Other VPN protocols | Each in-use Reality/VLESS/WG/Amnezia protocol actually tested or individually marked unknown. |
| Public HTTPS | Both entry points; correct TLS/SNI, expected health or login behavior, and backend reachability. |
| Both child authorities | NEW listens on UDP/TCP 53; NS, SOA and A records, serial and TTL checked; OLD no longer published. |
| Registrar | NS names and ns1 IP preserved; only ns2 changed to NEW; registrar confirmation observed. |
| Parent glue | Direct replies from at least two authoritative `.xyz` servers return NEW, not merely a child A record. |
| Recursive DNS | Record Google/Cloudflare DoH observations and TTL; distinguish cache lag from registrar publication. |
| Live Kubernetes audit | Functional specs and address fields in ConfigMaps and Secrets reviewed; no unexplained OLD reference. |
| Native Collector target | One owned blackbox target uses NEW; all other jobs and `collector.yaml` preserved. |
| Collector activation | Fresh UID, container ID, image, config and binary receipts; same pod; adjacent container IDs and restart counts unchanged. |
| Telemetry | Duration, log/metric sent deltas, refused/failed/enqueue deltas, queue samples and drain, data freshness. |
| Availability alert | Fresh NEW instance has `probe_success=1`; old alert resolved naturally without silencing or deleting series. |
| Loki/Tempo | Owners, routes, mTLS and data preserved; network change did not break ingestion or readiness. |
| NetBird | STUN bind and advertised URI use NEW; targeted Secret change; server reload and Ready; external UDP test. |
| Relay privacy | Source address behavior verified without printing raw client IPs; no open unauthenticated TURN relay. |
| Bot webhook | Telegram API reports NEW; pending count and error times understood; fresh delivery tested or explicitly unknown. |
| NetworkPolicies | RustFS auth/gateway and NetBird policy addresses updated in the correct namespaces without broadening access. |
| Local clients | Distinguish generated and **imported** Mac profiles; SSH aliases pinned; phone action explained. |
| GitOps state | Required revisions applied; unrelated OutOfSync documented; no blanket prune. |
| Cleanup | Bounded probe processes stopped; temporary pods, Secrets and bundles absent; permanent backups kept. |

## Stop conditions

- The last access path is lost, NEW is not assigned, or an identity differs.
- An unexpected source, schema, owner or affected inactive unit is found.
- A SQLite invariant or `quick_check` fails, or no protected, consistent preimage exists.
- A container, image, config or binary pin differs, or a neighboring Collector container restarts.
- Receiver/exporter failures grow, queues do not drain, or metrics or logs are stale.
- A secret reaches stdout or Git. Stop publication, notify the operator and obtain a separate remediation or rotation decision. Editing the log is not remediation.
- Parent glue still returns OLD after saving: registration is pending, not complete or merely a recursive cache issue.
- Apply fails: inspect receipts and preimages and establish actual state. Do not rerun the importer/deployer or roll back an entire live database.
