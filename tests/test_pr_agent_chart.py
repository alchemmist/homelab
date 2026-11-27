"""Check the offline Helm render contract for the PR Agent chart."""

import json
import subprocess
import unittest
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "pr-agent"
EXPECTED_FALLBACK_MODEL_COUNT = 9
EXPECTED_REVIEW_MODEL = "openai/v-deepseek-uc"


class PrAgentChartTest(unittest.TestCase):
    """Require the reviewed webhook, model, and push-command pins."""

    def test_template_renders_webhook_and_local_model(self) -> None:
        """Pin the image, owner-selected model, local gateway and push boundaries."""
        rendered = subprocess.check_output(
            ["helm", "template", "pr-agent", str(CHART), "--namespace", "pr-agent"],
            text=True,
        )
        assert "pragent/pr-agent:0.50.0-github_app" in rendered
        assert EXPECTED_REVIEW_MODEL in rendered
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
        assert fallback_value.count(EXPECTED_REVIEW_MODEL) == EXPECTED_FALLBACK_MODEL_COUNT
        assert "CONFIG__MAX_MODEL_TOKENS" in rendered
        assert 'value: "24576"' in rendered
        assert 'value: "100"' in rendered
        assert 'value: "15"' in rendered
        assert "PR_REVIEWER__PUBLISH_OUTPUT_NO_SUGGESTIONS" in rendered
        assert "PR_REVIEWER__MAX_PREVIOUS_FINDINGS_CHARS" in rendered
        assert "CONFIG__SYSTEM_INSTRUCTIONS" in rendered
        assert "CONFIG__PATCH_EXTRA_LINES_BEFORE" in rendered
        assert 'value: "40"' in rendered
        assert "CONFIG__MAX_EXTRA_LINES_BEFORE_DYNAMIC_CONTEXT" in rendered
        assert 'value: "80"' in rendered
        assert "PR_REVIEWER__MINIMAL_MINUTES_FOR_INCREMENTAL_REVIEW" in rendered
        assert 'value: "10"' in rendered
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
        assert '"false"' in rendered.splitlines()[check_at + 1]
        lines = rendered.splitlines()
        push_at = next(i for i, line in enumerate(lines) if "GITHUB_APP__PUSH_COMMANDS" in line)
        push_value = lines[push_at + 1]
        assert "/review" in push_value
        assert "/improve" not in push_value
        _review_model_contract(rendered)


EXPECTED_MODEL_SETTINGS = {
    "CONFIG__MODEL": EXPECTED_REVIEW_MODEL,
    "GITHUB_APP__HANDLE_PUSH_TRIGGER": "true",
    "GITHUB_APP__PUSH_COMMANDS": '["/review -i"]',
    "CONFIG__CUSTOM_MODEL_MAX_TOKENS": "32768",
    "CONFIG__MAX_MODEL_TOKENS": "24576",
    "OPENAI__API_BASE": "http://litellm.llm.svc.cluster.local:4000/v1",
}


def _review_model_contract(rendered: str) -> None:
    """Check exact deployment env values and nine same-model fallbacks, without a client."""
    deployments = [
        d
        for d in yaml.safe_load_all(rendered)
        if isinstance(d, dict)
        and d.get("kind") == "Deployment"
        and d.get("metadata", {}).get("name") == "pr-agent"
    ]
    assert len(deployments) == 1
    containers = deployments[0]["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    assert containers[0]["name"] == "pr-agent"
    settings: dict[str, str] = {}
    for name in [*EXPECTED_MODEL_SETTINGS, "CONFIG__FALLBACK_MODELS"]:
        matches = [entry for entry in containers[0]["env"] if entry["name"] == name]
        assert len(matches) == 1
        value: object = matches[0]["value"]
        assert isinstance(value, str)
        settings[name] = value
    for name, expected in EXPECTED_MODEL_SETTINGS.items():
        assert settings[name] == expected
    assert json.loads(settings["CONFIG__FALLBACK_MODELS"]) == (
        [EXPECTED_REVIEW_MODEL] * EXPECTED_FALLBACK_MODEL_COUNT
    )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("GITHUB_APP__HANDLE_PUSH_TRIGGER", "false"),
        ("GITHUB_APP__PUSH_COMMANDS", "[]"),
        ("CONFIG__MODEL", "openai/qwen3.8-27b"),
        ("CONFIG__CUSTOM_MODEL_MAX_TOKENS", "131072"),
        ("CONFIG__MAX_MODEL_TOKENS", "131072"),
        ("OPENAI__API_BASE", "https://public.example/v1"),
        ("CONFIG__FALLBACK_MODELS", "[]"),
        (
            "CONFIG__FALLBACK_MODELS",
            json.dumps(
                [EXPECTED_REVIEW_MODEL] * EXPECTED_FALLBACK_MODEL_COUNT + ["openai/qwen3.8-27b"]
            ),
        ),
    ],
)
def test_review_model_contract_rejects_drift(field: str, bad_value: str) -> None:
    """Reject context, gateway, model and mixed/empty fallback drift on synthetic YAML."""
    settings = {
        **EXPECTED_MODEL_SETTINGS,
        "CONFIG__FALLBACK_MODELS": json.dumps(
            [EXPECTED_REVIEW_MODEL] * EXPECTED_FALLBACK_MODEL_COUNT
        ),
    }
    settings[field] = bad_value
    rendered = yaml.safe_dump(
        {
            "kind": "Deployment",
            "metadata": {"name": "pr-agent"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "pr-agent",
                                "env": [
                                    {"name": name, "value": value}
                                    for name, value in settings.items()
                                ],
                            }
                        ]
                    }
                }
            },
        }
    )
    with pytest.raises(AssertionError):
        _review_model_contract(rendered)


def test_release_selects_only_existing_webhook_owner() -> None:
    """Preserve signature verification, image and redelivery; never trigger a webhook."""
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/pr-agent.yaml").read_text())
    helm = app["spec"]["source"]["helm"]

    def render(*settings: str) -> list[dict]:
        args = [
            "helm",
            "template",
            helm["releaseName"],
            str(CHART),
            "-n",
            app["spec"]["destination"]["namespace"],
        ]
        for setting in settings:
            args.extend(["--set-string", setting])
        return list(yaml.safe_load_all(subprocess.check_output(args, text=True)))

    settings = [p["name"] + "=" + p["value"] for p in helm["parameters"]]
    baseline = render(*[s for s in settings if not s.startswith("publicWebHost=")])
    active = render(*settings)

    def ingress(docs):
        return next(d for d in docs if d and d["kind"] == "Ingress")

    owner = ingress(active)
    (rule,) = owner["spec"]["rules"]
    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())
    assert catalog["hosts"]["pr-agent"][rule["host"]].get("route", "web") == "web"
    labels = ingress(baseline)["metadata"].setdefault("labels", {})
    assert "homelab.alchemmist.xyz/public-web" not in labels
    labels["homelab.alchemmist.xyz/public-web"] = "true"
    assert active == baseline
    assert "homelab.alchemmist.xyz/public-web" not in ingress(
        render(*settings, "host=unreviewed.invalid")
    )["metadata"].get("labels", {})
