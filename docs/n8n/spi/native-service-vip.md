# Native SPI DNS failure correction

18606 returned EAI_AGAIN before connecting to spi-triage.automation.svc.
Read-only probes from the n8n Pod confirmed intermittent CoreDNS timeouts and
5–10s libc lookups. Broader DNS/network recovery is NOT claimed.

The five SPI native POST URLs use the existing Service VIP10.43.194.185:8080.
serviceClusterIP pins the already allocated Service address in the owning chart;
no Pod IP/public edge, DNS monkeypatch, TLS/auth bypass or generic POST retry.
The canonical alchemmist/spi-triage integration worker-service.json records the
Service UID/namespace/selector/port and service_endpoint.py validates identity
before enrollment. Recreated/drifted Service identity needs operator review.

Before/after Helm rendering proves the sole rendered difference is the existing
Service.spec.clusterIP declaration. Every Deployment/Pod template stays identical;
no occupied worker/n8n Pod replacement is required. Native enrollment changes only
five URL parameters through the authenticated API, retaining credentials, graph,
settings, static/pin data and immutable execution snapshots. No historical replay
or paid probe. Later worker image rollout still requires NEW natural drain proof.
