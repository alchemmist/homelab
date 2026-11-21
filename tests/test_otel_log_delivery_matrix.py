"""Offline checks for bounded native log-count selection; no network client."""

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location(
        "log_matrix", ROOT / "scripts/otel-log-delivery-matrix.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class LogDeliveryMatrixTests(unittest.TestCase):
    """Selector checks for metadata-only Loki count documents."""

    def test_only_bounded_native_count_queries_and_metadata(self) -> None:
        """Accept only one-hour count queries and return their vector rows."""
        helper = module()
        assert all(
            "count_over_time" in query and "[1h]" in query for query in helper.QUERIES.values()
        )
        document = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {
                            "k8s_namespace_name": "llm",
                            "audit_pod": "open-webui-123",
                            "audit_container": "open-webui",
                        },
                        "value": [1, "36"],
                    }
                ],
            },
        }
        assert helper.select_counts(document) == document["data"]["result"]

    def test_partial_results_and_non_finite_counts_rejected(self) -> None:
        """Reject partial responses and non-finite or negative counts."""
        helper = module()
        for value in ["NaN", "inf", "-1"]:
            with self.assertRaises(ValueError):
                helper.select_counts(
                    {
                        "status": "success",
                        "data": {
                            "resultType": "vector",
                            "result": [{"metric": {}, "value": [1, value]}],
                        },
                    }
                )
        with self.assertRaises(ValueError):
            helper.select_counts(
                {"status": "success", "warnings": ["partial"], "data": {"resultType": "vector"}}
            )

    def test_unexpected_body_or_attribute_label_rejected(self) -> None:
        """Reject log bodies and labels outside the metadata allowlist."""
        for labels in [
            {"body": "private"},
            {"service_name": "https://user:password@example.invalid"},
        ]:
            with self.assertRaises(ValueError):
                module().select_counts(
                    {
                        "status": "success",
                        "data": {
                            "resultType": "vector",
                            "result": [{"metric": labels, "value": [1, "1"]}],
                        },
                    }
                )
