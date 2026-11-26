# Public web entrances

`entrances.yaml` maps each application namespace and exact Ingress hostname to
its permitted public entrances. It is an inventory and a PR check, not a DNS
writer, admission webhook or independent authorization layer. Paths, backend
Services, authentication, TLS Secrets and certificates remain with their owners.
HOME still serves internal routes; this catalog does not filter the HOME controller.

`dns: managed` refers to the existing zone health policy, `static` to a fixed
record, and `external` to a separately administered zone. An empty entrance
list never authorizes an ordinary web entrance. Monori reaches NL only behind
Moscow transit; the VPN host has its own legacy routes, not a new web grant.
Schoolbot currently routes `inform.sch1357.ru`; the plan's `bot.sch1357.ru` is
reserved, not an alias. Neither entry adds schoolbot to the NL Secret watch.

For a change, edit the catalog, regenerate the chart projection with
`uv run python -m ci.quality.public_web`, and run
`uv run pytest -q tests/test_public_web_entrances.py`. Review the resulting
namespace diff: a new NL namespace grants discovery of **all** its Secrets
and Ingresses. Do not add mixed private namespaces to publish a single route.
The generated list feeds both the existing controller arguments and its RBAC.
Its order is retained to avoid an unnecessary rollout. CRD discovery and
Ingress status ownership are separate and unchanged. DNS publication and
real-client acceptance require the subsequent rollout gates in the plan.

## Eligibility is not readiness

Ordinary hosts inherit `defaultEntrances: [home, nl, moscow]`. After acceptance,
Moscow alone may serve the blog if HOME and NL are down and a healthy blog
backend is reachable. A per-host `entrances` override is an explicit exception,
not a snapshot of which controllers exist today. External DNS ownership does
not restrict the eligible entrances.

`nlWatchNamespaces` records today's separately approved discovery grants. Adding
an ordinary hostname does not grant a new controller access to Secrets or publish
an IP. Expand controller discovery only after review; publish an eligible IP only
after its route is verified. This stage neither declares Moscow ready nor changes
the production DNS health algorithm.

A hostname may have distinct path owners. In particular `socrat-home` owns
`/` on `socrat.alchemmist.xyz`, while the existing `rustfs-public-files` Ingress
in `rustfs` owns `/public/` there. DNS selects the entrance, not the path owner.
Listing both namespace/host pairs does not add `rustfs` to the NL watch.

## Single surviving public IP: acceptance for every service

`uv run python -m ci.quality.public_survivors` prints the offline service matrix.
Each catalog namespace/host gets HOME-only, NL-only and Moscow-only cases, even
when several owners share a name. `unverified` means eligible, not healthy.
Policy exclusions and VPN constraints are gaps relative to universal failover;
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
