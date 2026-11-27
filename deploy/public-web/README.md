# One public web replica contract

`entrances.yaml` contains inventory (node placement and public IP only) and a
single namespace/host publication catalog. A replica label never selects sites,
permissions or a DNS policy. The shared chart in `replica/` renders authoritative
CoreDNS plus Traefik. Ingress class, discovery, verified Argo transport and RBAC
are the same across instances. Routes, paths, certificates and authentication
remain app-owned. External zone ownership changes who publishes DNS, not ingress.

Render a candidate, without applying it:

```sh
uv run python -m ci.quality.public_web home --serial 2026112601 | \
  helm template entry deploy/public-web/replica -n public-entry -f -
```

The default private stage renders **DNS only**: one CoreDNS container, ConfigMap,
ClusterIP and an ingress NetworkPolicy. No API token, RBAC bindings or backend
controller identity are needed to check UDP/TCP authoritative answers. This is a
migration stage for the whole replica, not per-location publication policy. The
same self-IP zones are used in both stages. To inspect the full **offline** web
candidate, add `--set stage=web-and-dns` to `helm template`; do not install that
stage pending Secret scope review. In a read-only Pod reference audit, 23 of 25
candidate namespaces had an image pull Secret or environment Secret reference.
Ingress labels do not restrict the controller's namespace-wide Secret reads.
This is a lower bound, not clearance for the remaining namespaces. No Secret
objects or payloads were needed to identify this blocker.

Each authoritative zone contains the same names. Only managed ordinary web A
records contain this replica's public IP. Baseline authority/glue, mail, TXT,
static and other non-catalog records remain unchanged. DNS for school names is
external. VPN and the fixed NetBird relay have distinct transport ownership, not
site-specific web inclusion. Monori is ordinary web in the target; verify the
known regional constraint before promoting a replica, not by hiding its route.

**Migration boundary:** no Application installs the new chart. No host bindings,
Service publication, new live Secret grants, Knot/registrar changes or VPN port
handoff in this change. The older NL release and the blog-only Moscow probe keep
their frozen runtime configurations until replacement; do not extend them to
roll out sites. The HOME VIP is not a Pod address: `socrat-0` is an inventory
placement for rendering, not a change of the HA owner. Inventory, backend reachability,
Secret-read scope (including shared namespaces), dynamic middleware dependencies,
zone serial/content parity and DNS delegation must be reviewed before activation.
Before staging, check `kubectl -n <namespace> get configmap kube-root-ca.crt`
and wait for namespace initialization. Do not make the CA projection optional.
Use distinct release names when staging multiple instances in a cluster; use a
permitted probe Pod for private checks. Only Ingresses explicitly labeled `homelab.alchemmist.xyz/public-web` with the
value `true` or `reviewed` qualify. The latter is the existing app-owned marker on
reviewed browser routes, not a blanket opt-in for their namespaces.
Do not install until every ordinary path owner has opted in, fixed transport
Ingresses remain unlabeled, and referenced middleware is discoverable. This selector
does not restrict Secret reads. The template is a web/DNS candidate, not an implementation of the public VPN cutover.

## Single surviving public IP: acceptance for every service

`uv run python -m ci.quality.public_survivors` prints the offline service matrix.
Each catalog namespace/host gets HOME-only, NL-only and Moscow-only cases, even
when several owners share a name. `unverified` means eligible, not healthy.
Fixed transport and VPN constraints are gaps relative to universal failover;
a reserved hostname is not a live service. The matrix does not grant access.

During an authorized single-entrance exercise, after DNS convergence, run e.g.
`uv run python -m ci.quality.public_survivors --dns blog alchemmist.xyz moscow`
from an ordinary external client without a VPN or resolver overrides. This checks
only that the client's effective addresses contain the surviving IP and no others.
A forced-IP check cannot satisfy this gate. Repeat from independent resolvers.
Then use the normal URL, validate trusted TLS, and exercise each owner's real
route (including authentication, storage or the appropriate TCP/UDP VPN profile).
Record time, survivor, client vantage, operation and outcome without credentials.
Distinguish a public ingress outage from loss of the backend nodes or data stores;
never mark the latter verified based on the former. No command here changes DNS,
creates an outage or marks a service accepted.

For `--dns`, exit 0 means the client's complete address set equals the one
surviving public IP, not merely that its IPv4 subset matches. An additional
IPv6 address fails this particular exercise. Exit 1 means lookup failure or
an address mismatch. Exit 2 means the requested case is unknown or not eligible
(e.g. a reserved hostname); the lookup was not attempted.

Before opting in route owners, run the read-only inventory gate:

```sh
kubectl get ingress -A -o json | uv run python -m ci.quality.public_route_gate
```

Treat missing opt-ins and overlapping host/path/type tuples as review items,
not a batch labeling instruction. Verify backend identity, routing priority,
authentication and middleware with each owner. Matching this inventory alone
is not acceptance of TLS, middleware, dependencies or Secret grants.

### Ownership findings before staging (read-only snapshot)

- Both exact `/change-password` variants on `auth.socrat.alchemmist.xyz` have
  the chart-owned `identity/password-self-service` at explicit priority 160,
  targeting `password-self-service:80`. The Ansible-owned
  `identity/socrat-password-self-service` has priority 150 and targets
  `authentik-server:80` with a redirect middleware in `identity`. Do not add
  a namespace-wide CRD grant merely to reproduce that lower-priority fallback.
  Verify the intended login flow with an authorized test session before opt-in.
- `/public/` on `rustfs.socrat.alchemmist.xyz` has both `rustfs-public-files`
  (priority 160, `rustfs:9000`) and `identity/rustfs-public-reader` (155,
  `rustfs-public-reader:80`). The former also owns the same path on
  `socrat.alchemmist.xyz`. Priority only ranks routers that a given controller
  actually discovers; it does not demonstrate equivalent access controls. Verify
  both public object reads and denial of non-public objects before adopting either.

The gate reports exact duplicates separately from intersecting path patterns.
Nested prefixes are often intentional: review backend/auth ownership rather than
removing a more-specific path or broadly opting in the whole namespace.

Before HTTP-01 acceptance, verify the effective `letsencrypt-http01` issuer
matches the reviewed bootstrap task. Only exact ordinary catalog names select
its labeled solver; the default solver stays unlabeled. Merging the playbook
does not run it. Existing certificates or a locally rendered challenge do not
prove renewal: use a separately approved canary and confirm external HTTP-01
validation before handing over ports or DNS.

### Backend admission for the password route

The legacy HOME controller reaches `password-self-service` on its Service and
Pod addresses; the legacy NL host-network controller was refused on both. Do
not grant a node IP or the whole cluster access. For the Pod-network candidate,
reserve the `public-entry` namespace exclusively for the platform controller: review
who can create or relabel Pods, run workloads or exec there before enabling the
backend chart's `allowPublicEntryPeer`. Keep untrusted probe clients outside that
trust boundary. The opt-in admits only labeled controller Pods in that namespace
on backend TCP/8080. Pod labels are not a security boundary against a namespace
writer. No opt-in, namespace creation or changes to the existing ingress owner
are part of this preparation. Test allowed and denied traffic and the anonymous
login redirect before adopting the route. A real password change is not a probe.

### Rehearse the three private authorities through Argo CD

`private-dns-fleet` consumes only the generated `private-dns-fleet/resources.yaml`
from Git. Regenerate with `uv run python -m ci.quality.private_dns_fleet`; use
`--check` to verify drift. Each inventory node gets one private ClusterIP and a
CoreDNS Pod with no Kubernetes API token. The policies allow inbound traffic
only from labeled probe Pods in `public-dns-rehearsal` and deny all egress.
The earlier policy sync wave is ordering, not proof of enforcement.
This egress denial applies to the DNS-only fleet. The offline `web-and-dns`
render has an ingress-only policy: it does not restrict outbound connections.
Traefik needs the API and approved backends; review that separate egress scope
before considering a web deployment. Do not promote by flipping the stage.

After reconciliation, inspect placement, readiness and Service endpoints. From a
disposable tokenless probe in that namespace with label
`homelab.alchemmist.xyz/public-entry-probe=true`, query each Service's **IP** on
TCP and UDP 53. Verify AA, exact self-IP answers and unchanged infrastructure
records; remove the probe label and repeat to verify denial from the same Pod.
Delete the probe afterward. Do not use these ClusterIPs for cluster DNS or delegate
anything to them. To retire the rehearsal, remove the bounded Argo application
via review; its resource finalizer removes its managed objects. Confirm cleanup
before deleting the dedicated namespace. No public fallback needs switching.

After the private DNS fleet is ready, use a dedicated disposable probe Pod
(with `dig` on PATH, no API token, and the approved probe label) in
`public-dns-rehearsal`. From the operator checkout run:

```sh
uv run python -m ci.quality.private_dns_answers PROBE_POD_NAME
```

This read-only positive check resolves the private Service IPs from Kubernetes,
not public DNS, and submits all managed ordinary names over both UDP and TCP to
each authority. It requires a complete authoritative, non-recursive answer with
exactly the expected IP per question. It does not create, relabel or delete the
probe. An execution error is not evidence of a policy denial. Record separate
same-Pod deny/reallow results and clean up the probe after the exercise.

### Verify the TLS source boundary before web staging

```sh
kubectl get ingress,certificate.cert-manager.io -A -o json | uv run python -m ci.quality.public_tls_sources
```

Use only Ingress and Certificate objects, never Secret dumps. The report maps
ordinary hostnames to owner namespace/name references. All routes must have an
owner; multiple paths on one hostname need not duplicate its TLS Secret. One
Ingress may declare a certificate covering names routed by another Ingress.
Ambiguous sources, missing writers, out-of-catalog DNS SANs and unready writers
prevent emission of candidate rules. The report is not applied: the exact-name
`get` rules show a target boundary, not a working replacement for Traefik's
list/watch informer. Do not bind them and fall back to wildcard access when
discovery fails. Do not copy private keys. Certificate status is not a live TLS
handshake, an authorization check or evidence of a healthy backend.

`services/public_entry/tls_material.py` is an **offline** validation primitive,
not a deployed provider. Given a single source's already-authorized DNS names,
PEM chain, matching key and timezone-aware time, it returns only the leaf
fingerprint. It rejects wrong or extra SANs, additional non-DNS SANs, invalid
time windows, unsupported or mismatched keys and malformed/unrelated chain
entries. It does not authorize a Kubernetes read, look up a trust root, certify
client trust, or apply a snapshot. In particular, an otherwise valid self-signed
fixture can pass this source check and still fail an ordinary browser. Do not
feed live keys to CI or persist the arguments. Run the synthetic regression
with `uv run pytest -q tests/test_public_tls_material.py`.

`tls_selection.select_sources()` validates a completed batch independently by
(namespace, Secret name). An invalid or missing pair withdraws every alias of
that source; overlapping ownership rejects both sources even if only one key
was readable. Its result contains references and fingerprints, not private keys.
A network-isolated local Traefik file-provider rehearsal built the fixture
certificates **and** routers from that same selection. Fresh TLS and HTTP on
three names passed initially; a wrong key withdrew both names of one source
while the independent site's fingerprint and body stayed correct. An empty
selection plus a nonempty strict-SNI sentinel snapshot rejected all three;
restoration recovered all three. Only disposable key material in container
tmpfs was used. This does not admit production routes or address the case
where the consumer cannot receive the snapshot.

### Schoolbot: use the same HTTPS acceptance check before and after staging

`uv run python -m ci.quality.schoolbot_entry_health --public` forces each
catalog IPv4 but preserves the real SNI and Host. `--local-port PORT` instead
uses only `127.0.0.1:PORT` for a pre-established port-forward to the private
**HTTPS controller listener**, not the Schoolbot backend. Neither invocation
reads Secrets, accepts an insecure TLS mode, follows redirects, or prints
headers/body. No network request by default. Success requires trusted frontend
TLS, HTTP 200 and a bounded JSON object with boolean `ok: true`. A TLS failure
prevents sending the HTTP request. The external name remains owner-controlled;
`bot.sch1357.ru` is never probed. A passing health response does not prove DNS,
user login, database operations, or independence from another public entrance.
