import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "pr-agent"


class PrAgentChartTest(unittest.TestCase):
    def test_template_renders_webhook_and_local_model(self):
        rendered = subprocess.check_output(
            ["helm", "template", "pr-agent", str(CHART), "--namespace", "pr-agent"],
            text=True,
        )
        self.assertIn("pragent/pr-agent:0.49.0-github_app", rendered)
        self.assertIn("openai/qwen3.8-27b", rendered)
        self.assertIn("http://litellm.llm.svc.cluster.local:4000/v1", rendered)
        self.assertIn("pr-agent.socrat.alchemmist.xyz", rendered)
        self.assertIn("github-webhook-secret", rendered)
        self.assertIn("readOnlyRootFilesystem: true", rendered)
        self.assertIn('kubernetes.io/hostname: "socrat-1"', rendered)
