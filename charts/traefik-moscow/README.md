# Private Moscow ingress rehearsal

The Argo Application is registered, but its default chart emits no resources.
The root Application may create the namespace; merging this chart does not
start a controller, grant discovery or enable the companion VPN relay.
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
