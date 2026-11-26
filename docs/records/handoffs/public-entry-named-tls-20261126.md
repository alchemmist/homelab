# Private ingress: named TLS source rehearsal, 2026-11-26

**Decision boundary:** a Traefik 3.7.19 process can serve and rotate a TLS
certificate without a Kubernetes API token or collection access to Secrets.
This was a synthetic cross-namespace experiment, not an installation of the
web stage and not a test using a production key. No public traffic was moved.

## What ran

Each run used two disposable namespaces. One held a freshly generated, short-lived
TLS Secret for `tls-proof.invalid` plus an unrelated Secret. The other held a
single non-root, tokenless-by-default Pod on `socrat-1`. There was no Service,
host networking, public port or persistent volume. NetworkPolicy denied ingress
and limited egress to the Kubernetes API. Only the source container mounted a
short-lived projected service account token. The cross-namespace RoleBinding
allowed exactly `get` on the one named fixture Secret. Access reviews returned
no for `get` on the unrelated name, `list` and `watch`. The successful reads
and handshakes also exercised the granted path; the negative access reviews
were not attempts to retrieve any real application data.

The source container used the API's namespaced GET endpoint over verified HTTPS.
It served an in-memory dynamic configuration to Traefik's stock HTTP provider
on loopback, with a single exact host, an inert internal service and inline TLS
material. Traefik listened on another loopback port and polled every two seconds.
No PEM, token or provider response belongs in a log, evidence file or repository.
An exec-capable principal or another container in the Pod could access loopback;
this is a key-bearing trust boundary, not a multi-tenant API.

## Observations on fresh TLS connections

| Operation | Result |
| --- | --- |
| Start with synthetic leaf A | Trusted handshake for the fixture name, exact SHA-256 leaf fingerprint matched. |
| Replace the same Secret with independently generated leaf B | New handshake matched B without restarting the Pod. Old trust anchor and wrong hostname both failed verification. |
| Remove the RoleBinding; try a source implementation that emits an empty HTTP/TLS configuration on 403/404 | The old certificate was still accepted during the bounded observation. Do not treat an empty snapshot, a failed poll or an API error as proof of withdrawal. |
| Repeat with an explicit nonempty withdrawal configuration | On denial the source emitted a snapshot with no certificates, a sentinel router for a different invalid hostname and strict default SNI. A new fixture-name TLS connection no longer verified. |
| Restore the RoleBinding on the same Pod, then delete the fixture Secret | The exact current leaf returned after restoration; after deletion the source again emitted the withdrawal snapshot and the fixture-name TLS check failed. |

The successful withdrawal test confirmed the source actually returned the
withdrawal snapshot before testing the peer. It did not establish which one
of the snapshot differences was sufficient, nor invalidate already-established
connections. All temporary Pods, permissions and synthetic keys were removed
with their namespaces. No production Secret was read for this experiment.

## Gates before any real web deployment

- The existing `kubernetesIngress` informer still needs list/watch. This proof
  used a different stock provider; swapping TLS delivery alone does not make
  the current chart safe to deploy. Keep the DNS-only fleet unchanged.
- Generate the whole router configuration from reviewed app-owned inputs:
  preserve path priorities, explicit auth middleware, backend TLS verification,
  source references and exclusion of private routes. Compare with production
  semantics, not just a successful TLS handshake.
- Exercise two names with distinct keys and a multi-name certificate. Removing
  or revoking one source must stop serving that key **without disabling the
  unaffected host**. Verify invalid/mismatched replacement material, API outage,
  recovery, bounded staleness, listener restarts and incremental renewal load.
- Test with reserved synthetic inputs on each candidate node before granting a
  production name. Do not copy TLS Secrets, add cluster-wide Secret access, or
  treat the observed distinct failure for `inform.sch1357.ru` on NL/Moscow as
  permission to change external DNS. Public DNS and VPN handoff remain separate.
