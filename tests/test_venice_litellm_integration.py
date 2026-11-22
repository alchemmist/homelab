"""Static gates for the secret-backed browser model; no cluster/network calls."""

import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPECTED_MAX_PARALLEL_REQUESTS = 4
EXPECTED_QUEUE_TIMEOUT = 180
REQUEST_TIMEOUT_SECONDS = 900


class VeniceLiteLLMIntegrationTests(unittest.TestCase):
    """Pin the Venice browser bridge and the existing Qwen route."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.values = yaml.safe_load((ROOT / "deploy/platform/litellm/values.yaml").read_text())
        cls.models = {m["model_name"]: m for m in cls.values["proxy_config"]["model_list"]}

    def test_routes_to_internal_browser_bridge(self) -> None:
        """Route Venice through the internal browser bridge."""
        params = self.models["v-deepseek-uc"]["litellm_params"]
        assert "venice-deepseek" not in self.models
        assert params["model"] == "openai/venice-agentic-deepseek-v4.1-flash-uncensored"
        assert params["api_base"] == "http://venice-api.venice-api.svc.cluster.local:8080/v1"
        assert "api.venice.ai" not in params["api_base"]

    def test_credential_is_an_explicit_secret_reference(self) -> None:
        """Read the Venice credential only from the named bridge secret."""
        assert (
            self.models["v-deepseek-uc"]["litellm_params"]["api_key"]
            == "os.environ/VENICE_BRIDGE_API_KEY"
        )
        env = next(x for x in self.values["extraEnvVars"] if x["name"] == "VENICE_BRIDGE_API_KEY")
        assert "value" not in env
        assert env["valueFrom"]["secretKeyRef"] == {
            "name": "venice-bridge-upstream",
            "key": "api-key",
        }

    def test_single_browser_is_not_overloaded_or_replayed(self) -> None:
        """Keep one browser worker and disable request retries."""
        params = self.models["v-deepseek-uc"]["litellm_params"]
        assert params["max_parallel_requests"] == EXPECTED_MAX_PARALLEL_REQUESTS
        browser = yaml.safe_load((ROOT / "charts/venice-api/values.yaml").read_text())[
            "browserCandidate"
        ]
        assert params["max_parallel_requests"] == browser["maxPendingRequests"]
        assert browser["queueTimeout"] == EXPECTED_QUEUE_TIMEOUT
        assert params["num_retries"] == 0
        assert params["timeout"] == REQUEST_TIMEOUT_SECONDS
        assert params["stream_timeout"] == REQUEST_TIMEOUT_SECONDS
        assert self.values["numWorkers"] == 1
        assert self.values["replicaCount"] == 1

    def test_qwen_route_and_existing_credential_are_preserved(self) -> None:
        """Preserve the existing Qwen route and its credential reference."""
        assert self.models["qwen3.8-27b"]["litellm_params"] == {
            "model": "openai/qwen3.8-27b",
            "api_base": "http://vllm.llm.svc.cluster.local:8000/v1",
            "api_key": "os.environ/VLLM_API_KEY",
            "timeout": 7200,
            "stream_timeout": 7200,
        }

    def test_no_database_upgrade_or_synthetic_credit_billing(self) -> None:
        """Keep the image tag and leave migration and synthetic billing off."""
        assert not self.values["migrationJob"]["enabled"]
        assert re.search(
            r"^eb6e7f61e4fa0fa1425461e4e92145c8eab73bef@sha256:[a-f0-9]{64}$",
            self.values["image"]["tag"],
        )
        info = self.models["v-deepseek-uc"]["model_info"]
        assert info["input_cost_per_token"] == 0
        assert info["output_cost_per_token"] == 0


if __name__ == "__main__":
    unittest.main()
