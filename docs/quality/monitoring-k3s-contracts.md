# Monitoring-k3s cross-namespace / host-boundary contracts

The monitoring-k3s release (`charts/monitoring-k3s`, namespace
cattle-monitoring-system) scrapes metrics from several out-of-band or
cross-namespace targets. These are the genuine provider contracts, registered
with the peer objects that the offline render cannot produce.

## Out-of-band Service backends (dangling-service)

The monitoring-k3s chart exposes scraper Services whose backends are not
rendered by this release:
- `socrat-argocd-metrics`: selects the Argo CD application-controller
  (`app.kubernetes.io/instance: argo-cd, name: argocd-application-controller`)
  in namespace argocd. The argo-cd upstream chart is rendered by Argo CD from
  its Helm repository, not an offline local chart, so the backend pod is an
  out-of-band provider.
- `socrat-tv-otlp-receiver`: selects the kube-prometheus-stack prometheus pod
  via `operator.prometheus.io/name` - a runtime operator-created pod (the
  Prometheus CR is rendered, the StatefulSet pod is not).
- `monitoring-etcd-metrics`: an Endpoints-only Service (no selector) that
  scrapes the per-node etcd metrics endpoints by explicit IP; it intentionally
  has no pod selector.
- `monitoring-traefik-metrics`: selects the kube-system traefik ingress
  (`app.kubernetes.io/instance: traefik-kube-system, name: traefik`) - the
  node edge ingress in kube-system, distinct from the traefik-edge release.

These backends exist in the cluster; only the offline lint render cannot show
them. The Service selectors are correct in the live cluster.

## Host-network probes (host-network)

- `monitoring-etcd-metrics` (DaemonSet): an nginx forward proxy bound to the
  node etcd address on the host network, forwarding /metrics to etcd
  127.0.0.1:2381. Host-network is required to reach the host-bound etcd
  listener. Hardened: runAsNonRoot 101, RO rootfs, tmp nginx pid, and this pass
  added an unauthenticated /healthz endpoint + liveness/readiness probes.
- `socrat-public-ip-probes` (Deployment): a blackbox-exporter bound to a
  specific node public source address to probe direct public IPv4:443 targets.
  Host-network is required to originate probes from the node's public address.

Both are host-boundary probes; the node firewall owns their boundary.
