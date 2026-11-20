"""Static gates for the secret-backed browser model; no cluster/network calls."""

import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class VeniceLiteLLMIntegrationTests(unittest.TestCase):
    """Pin the Venice browser bridge and the existing Qwen route."""

    @classmethod
    def setUpClass(cls):
        cls.values = yaml.safe_load((ROOT / "deploy/platform/litellm/values.yaml").read_text())
        cls.models = {m["model_name"]: m for m in cls.values["proxy_config"]["model_list"]}

    def test_routes_to_internal_browser_bridge(self) -> None:
        """Route Venice through the internal browser bridge."""
        params = self.models["v-deepseek-uc"]["litellm_params"]
        self.assertNotIn("venice-deepseek", self.models)
        self.assertEqual(params["model"], "openai/venice-agentic-deepseek-v4.1-flash-uncensored")
        self.assertEqual(
            params["api_base"], "http://venice-api.venice-api.svc.cluster.local:8080/v1"
        )
        self.assertNotIn("api.venice.ai", params["api_base"])

    def test_credential_is_an_explicit_secret_reference(self) -> None:
        """Read the Venice credential only from the named bridge secret."""
        self.assertEqual(
            self.models["v-deepseek-uc"]["litellm_params"]["api_key"],
            "os.environ/VENICE_BRIDGE_API_KEY",
        )
        env = next(x for x in self.values["extraEnvVars"] if x["name"] == "VENICE_BRIDGE_API_KEY")
        self.assertNotIn("value", env)
        self.assertEqual(
            env["valueFrom"]["secretKeyRef"], {"name": "venice-bridge-upstream", "key": "api-key"}
        )

    def test_single_browser_is_not_overloaded_or_replayed(self) -> None:
        """Keep one browser worker and disable request retries."""
        params = self.models["v-deepseek-uc"]["litellm_params"]
        self.assertEqual(params["max_parallel_requests"], 4)
        browser = yaml.safe_load((ROOT / "charts/venice-api/values.yaml").read_text())[
            "browserCandidate"
        ]
        self.assertEqual(params["max_parallel_requests"], browser["maxPendingRequests"])
        self.assertEqual(browser["queueTimeout"], 180)
        self.assertEqual(params["num_retries"], 0)
        self.assertEqual(params["timeout"], 900)
        self.assertEqual(params["stream_timeout"], 900)
        self.assertEqual(self.values["numWorkers"], 1)
        self.assertEqual(self.values["replicaCount"], 1)

    def test_qwen_route_and_existing_credential_are_preserved(self) -> None:
        """Preserve the existing Qwen route and its credential reference."""
        self.assertEqual(
            self.models["qwen3.8-27b"]["litellm_params"],
            {
                "model": "openai/qwen3.8-27b",
                "api_base": "http://vllm.llm.svc.cluster.local:8000/v1",
                "api_key": "os.environ/VLLM_API_KEY",
                "timeout": 7200,
                "stream_timeout": 7200,
            },
        )

    def test_no_database_upgrade_or_synthetic_credit_billing(self) -> None:
        """Keep the image tag and leave migration and synthetic billing off."""
        self.assertFalse(self.values["migrationJob"]["enabled"])
        self.assertRegex(self.values["image"]["tag"], r"^a691e23abfac6dd0f2b69f9f5b4f714241f39ac4@sha256:[a-f0-9]{64}$")
        info = self.models["v-deepseek-uc"]["model_info"]
        self.assertEqual(info["input_cost_per_token"], 0)
        self.assertEqual(info["output_cost_per_token"], 0)


if __name__ == "__main__":
    unittest.main()
