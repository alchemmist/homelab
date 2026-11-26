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
permitted probe Pod for private checks. Only Ingresses explicitly labeled `homelab.alchemmist.xyz/public-web=true` qualify.
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
