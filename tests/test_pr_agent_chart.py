"""Check the offline Helm render contract for the PR Agent chart."""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "pr-agent"
EXPECTED_FALLBACK_MODEL_COUNT = 9


class PrAgentChartTest(unittest.TestCase):
    """Require the reviewed webhook, model, and push-command pins."""

    def test_template_renders_webhook_and_local_model(self) -> None:
        """Pin the image, local model, host, resources, and push commands."""
        rendered = subprocess.check_output(
            ["helm", "template", "pr-agent", str(CHART), "--namespace", "pr-agent"],
            text=True,
        )
        assert "pragent/pr-agent:0.49.0-github_app" in rendered
        assert "openai/qwen3.8-27b" in rendered
        assert "http://litellm.llm.svc.cluster.local:4000/v1" in rendered
        assert "pr-agent.socrat.alchemmist.xyz" in rendered
        assert "github-webhook-secret" in rendered
        assert "readOnlyRootFilesystem: true" in rendered
        assert 'kubernetes.io/hostname: "socrat-5"' in rendered
        assert "CONFIG__LOG_LEVEL" in rendered
        assert 'value: "INFO"' in rendered
        assert "GUNICORN_WORKERS" in rendered
        assert 'value: "6"' in rendered
        assert "pr-agent-webhook-redelivery" in rendered
        assert "redeliver_webhooks.py" in rendered
        assert "CONFIG__AI_TIMEOUT" in rendered
        assert 'value: "7200"' in rendered
        assert "--timeout" in rendered
        assert '"0"' in rendered
        assert "CONFIG__FALLBACK_MODELS" in rendered
        fallback_at = next(
            i for i, line in enumerate(rendered.splitlines()) if "CONFIG__FALLBACK_MODELS" in line
        )
        fallback_value = rendered.splitlines()[fallback_at + 1]
        assert fallback_value.count("openai/qwen3.8-27b") == EXPECTED_FALLBACK_MODEL_COUNT
        assert "CONFIG__MAX_MODEL_TOKENS" in rendered
        assert 'value: "12288"' in rendered
        assert 'value: "100"' in rendered
        assert "PR_REVIEWER__ENABLE_LARGE_PR_CHUNKING" in rendered
        assert "PR_REVIEWER__INLINE_KEY_ISSUES" in rendered
        assert "PR_CODE_SUGGESTIONS__COMMITTABLE_CODE_SUGGESTIONS" in rendered
        assert "GITHUB_APP__HANDLE_PUSH_TRIGGER" in rendered
        assert "GITHUB_APP__PUSH_COMMANDS" in rendered
        assert "GITHUB__PUBLISH_AS_CHECK_RUN" in rendered
        check_at = next(
            i
            for i, line in enumerate(rendered.splitlines())
            if "GITHUB__PUBLISH_AS_CHECK_RUN" in line
        )
        assert '"true"' in rendered.splitlines()[check_at + 1]
        lines = rendered.splitlines()
        push_at = next(i for i, line in enumerate(lines) if "GITHUB_APP__PUSH_COMMANDS" in line)
        push_value = lines[push_at + 1]
        assert "/review" in push_value
        assert "/improve" not in push_value
