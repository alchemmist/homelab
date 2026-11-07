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
        self.assertIn("CONFIG__AI_TIMEOUT", rendered)
        self.assertIn('value: "7200"', rendered)
        self.assertIn("--timeout", rendered)
        self.assertIn('"0"', rendered)
        self.assertIn("CONFIG__MAX_MODEL_TOKENS", rendered)
        self.assertIn('value: "12288"', rendered)
        self.assertIn('value: "100"', rendered)
        self.assertIn("PR_REVIEWER__ENABLE_LARGE_PR_CHUNKING", rendered)
        self.assertIn("PR_REVIEWER__INLINE_KEY_ISSUES", rendered)
        self.assertIn("PR_CODE_SUGGESTIONS__COMMITTABLE_CODE_SUGGESTIONS", rendered)
        self.assertIn("GITHUB_APP__HANDLE_PUSH_TRIGGER", rendered)
        self.assertIn("GITHUB_APP__PUSH_COMMANDS", rendered)
        self.assertIn("GITHUB__PUBLISH_AS_CHECK_RUN", rendered)
        check_at = next(i for i, line in enumerate(rendered.splitlines()) if "GITHUB__PUBLISH_AS_CHECK_RUN" in line)
        self.assertIn('"true"', rendered.splitlines()[check_at + 1])
        lines = rendered.splitlines()
        push_at = next(i for i, line in enumerate(lines) if "GITHUB_APP__PUSH_COMMANDS" in line)
        push_value = lines[push_at + 1]
        self.assertIn("/review", push_value)
        self.assertNotIn("/improve", push_value)
