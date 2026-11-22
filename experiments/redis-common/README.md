# LiteLLM coordination Redis: transport gate

Run `bash experiments/redis-common/check.sh` with Docker (linux/amd64 emulation if needed), OpenSSL 3 and read access to the pinned Harbor image. Allow several minutes under emulation. Uses an internal container network, synthetic credentials and a disposable Redis; it does not use Kubernetes. Redis 7.4 here is a test fixture, not a platform distribution selection.

Observed with the proxy digest pinned in `deploy/platform/litellm/values.yaml`: two independent client processes initialized through `ProxyConfig._init_coordination_redis` incremented the same key to 1 then 2. The async client rejected an unrelated CA, a DNS alias absent from SAN, and an invalid ACL password. The explicit rediss URL takes `ssl_ca_certs`, `ssl_cert_reqs=required` and `ssl_check_hostname=true`. The bundled Python rejected a test leaf lacking Authority Key Identifier; use full X.509 extensions. Expected failures may produce Redis diagnostic logs; the probe uses no real secrets.

## Full proxy and outage check

Run `bash experiments/redis-common/check.sh proxy`. This adds disposable PostgreSQL and two separately addressed, single-worker proxies from the production digest. Both load the same mock completion and use one database, but do not share process memory. `/key/generate` creates fresh synthetic virtual keys. Neither Redis nor the proxies publish a host port. Cleanup removes fixture containers and their anonymous volumes. Never use the fixture password or ACL in production.

| RPM=1 on one virtual key | First completion (A) | Second completion (B) |
|---|---|---|
| Shared TLS Redis reachable | 200, expected mock response | 429 |
| Fresh key, Redis stopped between calls | 200, expected mock response | **200, expected mock response** |

The second result is an observed **fail-open window** on this pinned build. Do not market this configuration as a hard rate or spend ceiling. The script requires the healthy pair to be 200/429; the outage portion reports observed behavior rather than treating fail-open as an acceptance pass. A readiness check or a vanished banner cannot demonstrate this property. No response caching was enabled.

**Before rollout:** test budgets separately (RPM is not spend), router state, key invalidation, cold start without Redis, and recovery after reconnect. Define the acceptable behavior during loss of coordination: alerting only if overshoot is explicitly acceptable; otherwise gate admissions and verify that mechanism before scaling. Verify TLS and ACL for the final topology, including a primary promotion. No production configuration changes are needed to run either fixture.

## Automatic promotion with the platform configs

`bash experiments/redis-common/check.sh failover` additionally requires Helm and Python with PyYAML (`PYTHON` can override `../../.venv/bin/python`). It renders chart 4.39.0 with the platform values, runs three Redis+Sentinel pairs and HAProxy, then stops the container hosting the primary and its voter. It uses Docker IPs in place of Kubernetes announce Services. No manual promotion or changes to client config are performed. `REDIS_HA_CHART` may point to a local copy of the pinned chart.

Observed once: workers returned **200/429 before and after promotion** on fresh one-RPM keys, without restarting either proxy. A pre-failure witness key survived. The writer accepted a new SET 14 s after the old container stopped (not a production RTO). This checks server configs, quorum routing and client reconnect, **not** Kubernetes scheduling, loss of a physical node, every in-flight counter, or a spend guarantee.
