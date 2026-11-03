# LMS: live traces, Grafana waterfall and Loki correlation

## Deployed state — 2026-11-03

Dashboard: **[LMS · Performance & distributed traces](https://grafana.socrat.alchemmist.xyz/d/lms-performance)**
(private administrative WireGuard network, like the existing Grafana).

[Verified production trace](https://grafana.socrat.alchemmist.xyz/d/lms-performance?var-trace_id=52f8dc5b93588ed1255bb42e933a772a):
39 spans, browser → Traefik → LMS → content/database operations. The same trace
ID appears in Loki, and both the actual waterfall and correlated log panel were
verified in Chromium. Trace retention and dashboard time range still apply.

Machine-readable evidence:
[`deploy/monitoring/migration-evidence/lms-observability-20261103.json`](../deploy/monitoring/migration-evidence/lms-observability-20261103.json).
No private keys, session cookies or student content are in that file.

## Ownership and delivery

- Application instrumentation belongs to `alchemmist/lms`, image pinned by digest
  in `deploy/lms/values.yaml`. The verified image is based on LMS `cab752e`.
- **All production configuration and the dashboard belong here in Homelab.**
  `charts/lms/files/lms-performance.json` is authoritative for the live dashboard,
  not the earlier example file in the LMS repository.
- Argo CD `lms` renders `charts/lms` with `deploy/lms/values.yaml`. A dashboard
  ConfigMap in namespace `lms` carries `grafana_dashboard=1`; the existing Grafana
  sidecar watches all namespaces and provisions it into the LMS folder.
- LMS exports OTLP HTTP/protobuf to `https://10.250.0.3:44318/v1/traces` through the
  existing private client-mTLS ingress and **single existing global sampler**.
  No second collector/sampler or public telemetry listener was introduced.
- The SDK source rate is 1; the existing downstream policy retains errors/slow
  traces and samples ordinary traffic at 10%. Routine successful requests may
  therefore not appear in Tempo. Browser uploads are bounded and sampled with
  the server's W3C context.

## Dedicated identity and renewal

`otel-app-tls-lms` is a cert-manager client Certificate in
`cattle-monitoring-system`, issued by the existing `otel-ca`. It has its own key,
90-day validity, 30-day renewal window, and `rotationPolicy: Always`.

The existing credential mirror CronJob was extended with LMS:

- central reader: `get` only on the five explicitly named application leaves;
- namespace `lms`: `get/patch` only on Secret `otel-app-tls-lms` and Deployment
  `lms`; no permission to patch PostgreSQL or read the root CA private key;
- target Secret is mounted read-only at `/etc/otel-client`, mode 0440 with pod
  fsGroup 10001, matching the nonroot image;
- changed public certificate fingerprint triggers a normal rolling restart;
  unchanged mirror runs are idempotent;
- Argo ignores only the renewal-owned certificate-hash pod annotation and uses
  `RespectIgnoreDifferences=true`; the renewal checksum does not fight self-heal.

Maintained files are `deploy/monitoring/otel-application-pki.yaml`,
`otel-application-credentials.yaml`, and their source scripts. Reapply through
`ansible/playbooks/otel-application-credentials.yml`. Never export or reuse
another application's key and never disable TLS verification.

## Loki links and the important renewal detail

The existing log agent already ships namespace `lms` to Loki. Its real stream
selector is `{k8s_namespace_name="lms"}`, **not** an assumed
`{service_name="lms-backend"}`. The dashboard defaults to the real label.

Loki now has a `TraceID` derived field matching `trace_id=([0-9a-f]{32})`, linked
to datasource UID `tempo`. Provisioning uses `$${__value.raw}` so Grafana's
configuration expansion preserves the literal `${__value.raw}` link.

The host credential refresher **reconstructs** the datasource provisioning
Secret every minute. Updating the Secret once is not durable. The field is
therefore maintained in **both** `scripts/otel-production-grafana.py` and
`scripts/otel-host-credentials.py`, and the latter was deployed to socrat-0.
The live link was rechecked after subsequent timer runs.

To reapply just the maintained refresher, without touching bootstrap material:

```sh
cd ansible
ansible-playbook playbooks/otel-production-credentials.yml \
  --limit socrat-0 --tags grafana-correlations --ask-become-pass
```

`scripts/lms-grafana-correlations.py` can run on socrat-0 to patch the existing
provisioning document without writing/exporting its TLS key; it preserves all
other datasource and TLS settings. It is not a replacement for updating the
maintained refresher above.

## Using the dashboard

1. Open the dashboard in the administrative network.
2. **Trace ID** is a query-backed selector: the dashboard automatically selects an available retained trace in the chosen time range. Choose another ID from the dropdown, or use the search table/Explore.
3. Expand `browser.page`, `browser.api`, the Traefik `GET`/`ReverseProxy` spans,
   backend HTTP, `content.read_render`, `content.navigation`, `db.connect`, and
   `db.transaction`.
4. The Loki panel filters the same ID; expanded log records also link to Tempo.

The installed Grafana 13 datasource resolves trace IDs through
`queryType: traceql`. The obsolete `traceId` type produced a blank panel despite
valid Tempo data; the live browser check caught this, and the chart now uses the
supported query type.

`browser.resource` measures network-transfer duration; fetch spans measure time
to response headers. This is a span waterfall, **not a CPU sampling flame graph**
or coverage of every Python/JS function. No Pyroscope was deployed.

## Reproduce the real production check

Requirements: administrative Grafana network access, existing SSH/Kubernetes
operator access to socrat-0, Node, and the sibling LMS checkout with
`npm ci --prefix ../lms/tests` and Chromium available.

```sh
python3 scripts/lms-observability-verify.py --create-canary-session \
  --output /tmp/lms-observability-result.json
```

This explicit flag creates a synthetic teacher profile with a session shortened
to 15 minutes. It does not impersonate a real user, alter real grants, submit
solutions or exercise Authentik login. The profile/session is deleted in
`finally`, also on a failing check. Secrets remain in process memory only; no
browser storage-state or session file is saved.

The canary opens the real first Long-Read and reads a deliberately nonexistent
API route (404). The resulting **browser ERROR span** makes the existing global
error policy retain the diagnostic trace without changing sampling. It then
waits for normal 30-second tail-sampling/eventual-ingestion delay, verifies
parent IDs including Traefik intermediates, checks Loki, and opens the live
Grafana dashboard in Chromium to verify the rendered waterfall and logs.

The expected 404 is intentional test traffic, not a production availability
failure. The evidence explicitly records that Authentik login was not tested.

## Tests and operations

```sh
helm lint charts/lms -f deploy/lms/values.yaml
uv run --python 3.13 --with pytest --with pyyaml --with jinja2 --with cryptography \
  python -m pytest -q tests/test_otel_*.py tests/test_lms_observability.py
```

Verified: 259 tests and 15 subtests passed. Argo `lms` was `Synced/Healthy`, LMS
`1/1` ready, the mirror succeeded a second time with **no changed leaves**, and
the host credential timer succeeded with the derived link still present.

To disable tracing, set `tracing.enabled: false` in `deploy/lms/values.yaml` and
push through the normal GitOps path. It removes telemetry environment and the
credential mount; the application defaults to tracing off. Do not delete shared
OTel backends, global PKI, log shipping or other applications' credentials.
To remove the dashboard too, set `tracing.grafanaDashboard: false` and explicitly
review deletion (the existing Argo app does not auto-prune).


## Empty-panel regression fixed

The first dashboard revision required a manually supplied ID. Opening its bare
URL left the waterfall query empty; old diagnostic links could also filter logs
outside the current time range. A successful test of a prefilled link did not
cover that normal entry path.

The production dashboard now uses a native Tempo query variable (label values
`lms.trace_id`, refreshed on time-range changes), with no blank textbox default.
LMS records its current W3C trace ID as this non-sensitive span attribute, so the
selector gets **retained** IDs from Tempo rather than all potentially unsampled
IDs from Loki. The correlated panel uses the fixed, verified namespace selector;
an independent recent-application-logs panel does not depend on any trace ID.

The browser canary checks both the bare dashboard and a supplied full distributed
trace. A genuinely empty historical interval or expired data cannot be filled
with invented spans: choose a recent/wider interval to investigate current
traffic. Dashboard auto-selection is one available trace, not a claim to sort
high-cardinality tag values chronologically.


2026-11-03 regression evidence:
- `deploy/monitoring/migration-evidence/lms-dashboard-default-selection-20261103.json`
  verifies the full 39-span browser/backend trace plus bare-dashboard auto-selection;
- `deploy/monitoring/migration-evidence/lms-dashboard-entry-scenarios-20261103.json`
  verifies the bare URL, an invalid trace URL, and `now-5m`.

Log assertions are scoped to the correlated panel itself: matching lines in the
independent recent-log panel cannot accidentally make this check pass.
