# Closed TLS refresh boundary

`tls_refresh.refresh()` takes an independently approved map of `(namespace,
Secret name)` to exact DNS SANs, a named-read callback and a timezone-aware
clock value. It performs no Kubernetes transport or listener configuration on
its own. Never build its input from unreviewed Ingress requests. There is no
list/watch, retry loop, last-good key fallback, RBAC manifest or deployment.

- An ambiguous source is not fetched. Each remaining reviewed reference is
  passed to the callback once. A successful reply must be a matching v1 TLS
  Secret, not terminating, with bounded base64-encoded certificate and key.
  Only those two fields are decoded. The transport must independently cap
  total response bytes, deadlines, request destinations and redirects.
- A completed scan omits denied, missing, transiently unavailable, or invalid
  sources. Use the **same result** for material and host eligibility; do not
  re-fetch a key after checking it. Keep the result in memory; it contains key
  bytes and is not a report to serialize, log, or publish outside the local
  trusted consumer. Omission withdraws all associated aliases and may sacrifice
  availability during transient failures. Fixed reason strings do not contain
  server response content.
- An interrupted scan, a stopped publisher or a broken connection to Traefik
  does not constitute consumer withdrawal. The caller still needs atomic
  application, a nonempty strict-SNI withdrawal config, bounded staleness and
  listener-side acceptance. This is not proof of public certificate trust,
  application authorization, route parity or isolated survivor availability.

A local rehearsal used the pinned Traefik in an isolated network namespace
with a loopback marker and only disposable fixture material in tmpfs. Three
sources covered four names. Fresh connections checked leaf fingerprints and
HTTP markers on admitted names and strict SNI rejection on withdrawn names:
initial 4/4 serving; synthetic 403 plus 503 left only the unrelated source;
clearing only the 503 restored that source, not the denied source or its alias;
all missing withdrew all four; restoring the fixture restored all four. No
cluster credentials, public listener or real Schoolbot key were involved.
