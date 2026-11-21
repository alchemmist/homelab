"""Check Wishlist metrics, traces, and dashboard scope from source."""

import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

METRICS_PORT = 8001


class WishlistObservabilityTests(unittest.TestCase):
    """Check Wishlist observability source contracts."""

    def test_private_metrics_and_verified_dedicated_trace_identity(self) -> None:
        """Keep the private metrics port and the dedicated trace identity."""
        values = yaml.safe_load((ROOT / "charts/wishlist/values.yaml").read_text())["observability"]
        assert values["metricsPort"] == METRICS_PORT
        assert values["clientSecret"] == "otel-app-tls-wishlist"
        assert values["tracesEndpoint"] == "https://10.250.0.3:44318/v1/traces"
        deployment = (ROOT / "charts/wishlist/templates/deployment.yaml").read_text()
        for name in [
            "OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE",
            "OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY",
            "OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE",
            "METRICS_PORT",
        ]:
            assert name in deployment
        ingress = (ROOT / "charts/wishlist/templates/ingress.yaml").read_text()
        assert "metricsPort" not in ingress
        assert "8001" not in ingress
        assert "insecure" not in deployment.lower()

    def test_single_existing_collector_job_no_second_prometheus_scraper(self) -> None:
        """Keep one collector job and reject a second Prometheus scraper."""
        pipeline = (ROOT / "charts/monitoring-k3s/templates/_tv-native-metrics.tpl").read_text()
        assert pipeline.count("job_name: wishlist") == 1
        assert pipeline.count("wishlist.wishlist.svc.cluster.local:8001") == 1
        policy = (ROOT / "charts/monitoring-k3s/templates/activity-metrics.yaml").read_text()
        assert "kubernetes.io/metadata.name: wishlist" in policy
        assert "app.kubernetes.io/instance: wishlist" in policy
        assert "port: 8001" in policy
        for path in (ROOT / "charts/wishlist/templates").glob("*"):
            assert "kind: ServiceMonitor" not in path.read_text()

    def test_dashboard_queries_and_mirror_scope(self) -> None:
        """Keep dashboard queries and the credential role's exact scope."""
        dashboard = json.loads(
            (ROOT / "charts/wishlist/files/wishlist-performance.json").read_text()
        )
        assert dashboard["uid"] == "wishlist-performance"
        queries = json.dumps(dashboard)
        for value in [
            "wishlist_inventory_scrape_success",
            "wishlist_operation_duration_seconds_bucket",
            "wishlist_http_request_duration_seconds_bucket",
            "wishlist",
            "tempo",
            "loki",
        ]:
            assert value in queries
        assert "or vector(0)" not in queries
        resources = list(
            yaml.safe_load_all(
                (ROOT / "deploy/monitoring/otel-application-credentials.yaml").read_text()
            )
        )
        role = next(
            value
            for value in resources
            if value["kind"] == "Role" and value["metadata"]["namespace"] == "wishlist"
        )
        assert role["rules"][0]["resourceNames"] == ["otel-app-tls-wishlist"]
        assert role["rules"][1]["resourceNames"] == ["wishlist"]
        assert set(role["rules"][1]["verbs"]) == {"get", "patch"}
