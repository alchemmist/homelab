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
