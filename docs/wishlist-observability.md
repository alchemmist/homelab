# Wishlist · Performance and distributed traces

Wishlist owns content-free browser/backend instrumentation. Homelab owns production
configuration, the existing Collector job and dashboard. This change adds no
second scraper, sampler, public OTLP listener or credentials in Git.

- Private metrics: `wishlist.wishlist.svc.cluster.local:8001/metrics`, never an
  ingress backend. Existing native Collector scrapes every 15s, exports through
  its existing OTLP pipeline to Prometheus/Thanos. No ServiceMonitor duplicate.
- Dedicated `otel-app-tls-wishlist` cert-manager leaf, existing `otel-ca`, verified
  HTTPS/mTLS `https://10.250.0.3:44318/v1/traces`. Named cross-namespace mirror and
  exact Wishlist Deployment renewal annotation rights; no CA private key access.
- Maintain the native leaf/mirror manifests with the existing
  `ansible/playbooks/otel-application-credentials.yml`. Target Secret must exist
  before enabling SDK chart configuration. The mirror creates no accounts.
- English Grafana dashboard UID `wishlist-performance`, sidecar ConfigMap in
  Wishlist namespace. Uses existing datasource UIDs `prometheus`, `tempo`, `loki`.
- Inventory gauges are current persisted counts, not active sessions, unique
  visitors or historical deleted gifts. Missing inventory exposes success=0 and
  omits counts; it must not be displayed as a healthy zero.
- HTTP/DB/validation/storage histograms are process-local since restart. SQL text,
  parameters, cookies, usernames, gift titles, URLs and filenames are not labels
  or span attributes. Request logs include only method, route template, status,
  duration and trace_id; Loki namespace selector is `k8s_namespace_name="wishlist"`.
- Each Save creates a new trace (not one trace for an indefinitely open browser
  tab). Fetch/XHR send W3C traceparent. Native img resources cannot send that
  header: browser resource spans link to the backend context advertised in
  Server-Timing where the browser supports it. Fetch spans measure headers/TTFB;
  resource spans measure full transfer, including cached resources.
- Anonymous same-origin browser relay accepts a bounded allowlisted schema, 32
  spans/batch, bounded queue and a global token budget; it is not a raw OTLP proxy.
  Telemetry failure never blocks Save. IDs/log contents are not authentication.
- Existing global policy: 30s tail decision, errors/5xx and >=2s traces retained,
  ordinary traces 10%. Late spans for very long uploads can miss that decision;
  this application rollout does not change the global sampling policy. Browser
  and SDK queues are bounded/non-durable; this is tracing, not an audit log.

Acceptance status and live evidence are recorded separately after rollout. Do not
interpret configured exporters or a healthy Argo app as proof of Tempo delivery.
