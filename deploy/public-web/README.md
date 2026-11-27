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

### Inventory backend dependencies separately from TLS source ownership

```sh
kubectl get ingress,service,endpointslice.discovery.k8s.io,middleware.traefik.io,serverstransport.traefik.io -A -o json | uv run python -m ci.quality.public_backend_contract
```

This read-only report keeps every ordinary owner/path row, named or numbered
Service port, upstream scheme, explicit priority, ordered middleware references
and ServersTransport reference. It checks for a ready non-terminating address
on an EndpointSlice advertising that Service port. It does not fetch Secrets,
create routes, or assume a `Ready` endpoint is reachable from an ingress Pod.
All catalog owners are included, even ones not yet opted in. Missing or ambiguous
references are blockers; never replace a missing auth middleware with a bare
route or downgrade an HTTPS or h2c backend to HTTP. The report is not a full
Traefik config compiler: it does not certify application auth, middleware bodies,
traffic, port reachability or the winner of overlapping routes.

A closed rehearsal used the same pinned Traefik and identical **fixture** file
provider config on `socrat-0`, `socrat-2`, and `socrat-4`. Each tokenless Pod
bound only loopback; no public Service, host port, real frontend key or API
RBAC. A temporary namespace egress policy admitted only the Argo and NetBird
Service/endpoint TCP destinations. Fresh trusted frontend connections on **each**
node produced:

| Real upstream through fixture Traefik | Result |
| --- | --- |
| Argo HTTPS, verified production `serverName`, `/api/version` | 200 and nonempty version field |
| Same transport, `/api/v1/applications`, no credentials | 401 and application error code 16; no list retrieved |
| Same destination and path as version check but deliberately wrong backend TLS name | 500, no version response; frontend trust still valid |
| NetBird Management over h2c, unary `GetServerKey` | Native gRPC OK with nonempty reply; no key bytes logged |
| NetBird Signal path over h2c, nonexistent diagnostic RPC | Native gRPC UNIMPLEMENTED with unknown method/service detail; not a Signal stream test |

The file provider used a supported YAML filename; the preliminary `.json`
fixture did not establish trusted frontend TLS and was not counted. All temporary
namespaces were deleted. This rehearsal covers backend transports and native
anonymous Argo denial, not application login, VPN traffic, external browser
middleware, all catalog paths or a public survivor. In particular the live
RustFS forward-auth address is **itself a public hostname**; its resolution and
return path still need independent survivor testing. Do not infer the result
from finding the Middleware CRD or reaching Argo.

A subsequent three-node RustFS rehearsal isolated the **server-side** forward-auth
hop. Each tokenless, loopback-only Traefik mapped just the live RustFS hostname
to `127.0.0.1` inside its own Pod. Egress allowed only Authentik's private
HTTP Service/endpoint ports, not DNS or any public entrance. The file fixture
kept the real middleware HTTPS address, `trustForwardHeader: false`, host and
outpost-prefix priority, with a disposable TLS trust anchor. A local marker
replaced the console, so even a failed test could not grant console access.

| Request on each of HOME, NL and Moscow | Result |
| --- | --- |
| Fixture-only unprotected control | 200 with exact marker body |
| `/outpost.goauthentik.io/ping` | 204 from real outpost route |
| Anonymous `/` through forward-auth | 302 to `auth.socrat.alchemmist.xyz/application/o/authorize/`, never marker |
| Same middleware address without trust in the disposable certificate | 500, never marker |

No redirect was followed, nor were cookies, redirect parameters or credentials
recorded. Temporary namespace deleted. This demonstrates a way to keep the
middleware self-call on the surviving web process without weakening TLS. It is
not evidence the current public controllers use that resolution, the browser
can finish login through the surviving entrance, or RustFS enforces object ACLs.
Do not append fixture routes or trust anchors to a production listener.

For the anonymous client-side continuation, the same private listener also
served the Authentik hostname. A bounded GET client connected exclusively to
that Pod's local port-forward for **both** hosts, preserving SNI, trust and Host
on every hop. It followed only HTTPS redirects to those two exact authorities;
no cookies were replayed and no form was submitted. HOME, NL and Moscow each
returned `302 /` (RustFS), `302 /application/o/authorize/` (Authentik), then
`200 /if/flow/default-authentication-flow/` with the Authentik flow executor
in the HTML. No query strings or response headers were recorded. This adds
same-entry reachability of the login document, not browser asset loading,
credential validation, callback completion, object access or public failover.

RustFS object baseline: the published wiki image
`/public/wiki/rancher-secrets/type-fbebfdb07632.png` returned 200 via each
public IP with verified SNI, 121274 bytes, PNG signature and the SHA-256 prefix
from the wiki filename. Anonymous `Range: bytes=0-7` returned 206, the exact
PNG signature and `Content-Range: bytes 0-7/121274` on all three. No signed
URL, cookies or bucket enumeration. This is current-path evidence only.

The analogous closed, tokenless per-node rehearsal **did not pass**. With
fixture egress scoped to the direct RustFS and public-reader Service/endpoint
ports, both full and range GETs returned 502 on every node. Fixture-only
response markers identified the direct priority-160 router when both owners
were present, and the reader when selected alone on a control hostname. Thus
selection is observable independently of successful backend admission. Do not
claim the closed web replica serves objects or enable either peer on this basis;
first verify intended identity, pod-to-endpoint admission and return traffic.
No private-object ACL result or authenticated operation was inferred.

`ci/quality/public_path_rule.py` generates one **closed-fixture matcher**, not
a deployable router. Prefix `/public/` matches `/public`, `/public/` and a
child segment, not `/publicity` or `/public-file`. Exact paths keep their
trailing slash and case. Unknown path types and unsupported literals fail
rather than silently broadening discovery. In a loopback-only, network-isolated
Traefik rehearsal, ten fresh requests selected the expected distinct backend
markers or the unknown-host 404, including both exact password paths and their
unmatched child. Fixture priorities were explicit. Generated rule **length**
must not silently change implicit priorities relative to another owner; route
selection, auth and middleware parity remain separate deployment gates.

A follow-up rehearsal showed **why copying implicit priority is not optional**.
The [pinned Ingress implementation](https://github.com/traefik/traefik/blob/v3.7.19/pkg/provider/kubernetes/ingress/kubernetes.go)
uses a character prefix unless `strictPrefixMatching` is enabled. For a fixture
host and `/public/`, the unannotated original matcher had length/priority 46;
the segment-aware rewrite measured 67. An overlapping exact-route marker at
explicit priority 47 won initially, lost to the naive rewrite, then won again
when the generated rule explicitly retained priority 46. Full requests to the
running isolated binary verified each winner. The slashless `/public` still
changed from the fallback to the prefix owner: **preserving priority is not
preserving match scope**. Do not assume either setting on a live controller
from this fixture. Establish the existing mode, compare both boundary paths
and precedence, and require owner review of differences. Unreviewed ties
between overlapping owners must not depend on router names or load order.

Run `uv run python -m ci.quality.public_path_diff --source-prefix character`
(or `segment`) on the JSON from `public_backend_contract`. Use the route set
of the controller being compared; the full catalog does not describe each
legacy controller's discovery scope. The mode is mandatory: this tool samples
boundary paths, freezes original priorities and reports all highest-priority
rows rather than choosing a winner on a tie. Exit 1 means changed winners or
ties, not necessarily differing backends; exit 2 on incomplete inventory. An
empty result is not exhaustive, does not model middleware or application auth,
and is not permission to install a generated configuration.

Applied to the two offline rendered n8n Ingresses: assuming a character-prefix
source produced 12 flagged witnesses, six changing winning Ingress owner and
eight with original equal-priority ties (categories overlap). Assuming a
segment-prefix source produced none. The machine and UI Ingress can point to
the same Service: comparing only service names would miss the difference. These
are conditional comparisons, not claims about live n8n reachability or an
actual authentication bypass. No synthetic webhook or callback was sent.

`unchanged_host_matchers()` is an all-or-error gate for a **complete supplied
host path set**. Unknown mode is not eligible. In character mode a non-root
prefix ending in `/` gains the slashless base on rewrite; a non-root prefix
without `/` loses same-segment extensions. Both require scope review even if
no sampled winner changes or an explicit priority exists. Do not silently drop
the blocked rule and install the remaining catch-all. Root prefixes and exact
paths do not have this particular difference. Middleware, backend, TLS owner,
conflicting owners and tied priorities are independent gates.

Repository-only evidence: the legacy NL `traefik-edge` default Helm render at
this revision uses the pinned image and does not pass the strict-prefix flag.
HOME's Ansible role preserves unrelated live HelmChartConfig values, so its
inputs alone cannot certify the live arguments. Moscow's old restricted
private rehearsal is not a third independent public web policy. None of these
observations substitutes for the running controllers' effective config.

The backend inventory also fingerprints the **ordered referenced CRD bodies**,
not just their names. A middleware or transport can change under the same
name: compare the captured source body digest with the reviewed body used in
the candidate. The report does not include URL, regex or replacement contents.
The recognized shapes are deliberately narrow: explicit HTTPS forward-auth
without trusting forwarded headers, a single redirect-regex middleware, and an
HTTPS transport with a verification name and no verification bypass. Other
options, including chained middleware and CA Secret references, require their
own dependency and authorization review; the report blocks rather than losing
them in translation. Recognition is not approval of the address, regex, or TLS
name and is not proof of equivalent runtime behavior. The offline unified-origin
RustFS chart's `rustfs-browser-auth` was recognized as `forwardAuth`; no live
CRD was fetched or changed for this check.

For a named `targetPort` the EndpointSlice supplies the resolved port number;
its port *name* identifies the Service port, not the named container port.
Different Pods can resolve the same named target to different numbers. The
audit does not independently inspect Pod specs or probe those sockets. A
numeric target (including the implicit Service port default) must match exactly.

### Pin source names independently of observed objects

`uv run python -m ci.quality.public_tls_pins` accepts the same Ingress and
Certificate JSON list as the TLS inventory. A consistent pair of live objects
is not independent approval to fetch a newly referenced key. `tlsSourceName`
may appear on exactly one ordinary namespace/host owner per DNS name and
identifies a Secret **only in that namespace**. Other path owners need no key
pin. The comparison emits no reader plan if any ordinary host has a missing,
ambiguous, malformed or mismatched pin or if the inventory has errors. It does
not render or apply RBAC, read Secrets, or change DNS ownership.

Offline review covers all 37 ordinary names, with exactly one namespace-local
pin each and 35 distinct sources (blog apex/www and the two RustFS aliases
share pairs). Local Helm renders check both referencing routes and the unique
issuance request: an issuer-annotated Ingress or an explicit Certificate, not
every Ingress that uses the key. In particular `llm/litellm` requests issuance;
`llm/litellm-branding` only reuses `litellm-public-tls`. Private Certificates
in `syncthing` covering public alias names do not authorize that namespace as
their public key source. The fixed NetBird VPS relay remains excluded.

For Argo CD, repeat the independently verified external chart render with
`helm pull argo/argo-cd --version 10.11.6` (official Argo Helm repository),
then `uv run python -m ci.quality.public_argocd_tls argo-cd-10.11.6.tgz`.
The checker verifies the reviewed archive digest **before** invoking Helm;
CI checks the declared version, inputs and pin without downloading a chart.
Rancher uses the Kubernetes version from the repository k3s defaults, not
Helm's possibly newer synthetic default. None of these offline checks establishes
live writer readiness, route admission, served TLS or permission to grant a
reader. The actual inventory must still match the reviewed plan exactly. Never bootstrap the pins by copying audit output into
Git wholesale. A name pin is not proof of the key bytes, the authority of a
namespace writer or successful TLS delivery; validate leaf material and test
the listener independently. The private DNS stage needs neither pins nor keys.
