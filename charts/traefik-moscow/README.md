# Private Moscow ingress rehearsal

The chart is inert by default. The production Argo Applications explicitly opt
into the **private rehearsal only**: merging those values starts two Pod-network
workloads and their discovery grants. Their NetworkPolicies have an earlier sync
wave than the Pods; ordering alone does not demonstrate data-plane enforcement.
There is deliberately no public mode or DNS cutover switch.

The opt-in render schedules a non-root Traefik in the Pod network on socrat-4.
Only the approved blog namespace is watched for normal Ingress, including its
existing TLS Secret. This is a first test backend, not a restriction on which
public sites can eventually use Moscow. Only labeled Moscow-class CRDs in
`vpn-transit` supply VPN routes; the relay ClusterIP is used for both transports.
Raw TCP/80 is not forwarded. On shared TCP/443 only the exact VPN SNI goes to
the old backend; other HTTPS uses ordinary Ingress. UDP/443 is VPN, not HTTP/3.
No status writes, published IP, NodePort, host socket or external LB.

## Acceptance before activation or public handoff

1. Render the Application with the catalog values file and `rehearsal=true`;
   render `vpn-transit` with `podRehearsal=true`. Check actual memory headroom,
   scheduling, image availability, private connectivity and CNI policy enforcement.
   If either workload is unsafe for the available capacity, do not enable it.
2. Enable both private renders only in a reviewed Git change. From an authorized
   probe Pod in `traefik-moscow` labeled `homelab.alchemmist.xyz/moscow-probe=true`,
   target the private Service IP with the real hostname/SNI. Check blog content
   and trusted TLS; prove unauthorized Pods cannot use the Service. Keep production
   DNS, the legacy relay and watchdog untouched. Port-forward alone cannot test UDP.
3. Verify real TCP and UDP profile traffic and the observed source identity at NL;
   do not relax ACLs for unexpected Pod egress. No-SNI or ambiguous clients on
   shared ports must move to a dedicated port before the separately fenced handoff.
   A Ready Pod or TLS handshake alone is not acceptance. Record only non-sensitive
   results. Do not run cert issuance against a production hostname for this rehearsal.
4. To retire the rehearsal, explicitly remove only its resources after disabling
   the opt-ins: both child Applications have prune disabled. Verify private
   Roles, bindings, routes, Pods and Services are gone and the legacy owner remains.

See the [dated pre-resize capacity preflight and private client procedure](../../docs/records/handoffs/moscow-private-rehearsal-20261126.md) before enabling the pair.

After the 26 November resize, socrat-4 reported 4015936 Ki RAM, 3360576 Ki
allocatable and two CPUs. Existing requests/limits were 96/288 Mi; projected
overlap is 208/672 Mi. The old capacity hold is superseded, not the required
client, image-pull and policy checks. Before merging the opt-ins, confirm the
original authenticated TCP/UDP path after reboot and CNI enforcement on Moscow.
After sync verify both private Pods and the unchanged public relay, then run
positive and negative checks from same-node and cross-node clients. Stop on a
policy failure; do not publish DNS or hand over public sockets.
