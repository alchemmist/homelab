"""Offline ownership boundaries, not permission to execute production playbooks."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DeploymentOwnership(unittest.TestCase):
    """Retired installers refuse before effects while Git-owned protections remain intact."""

    def test_retired_entrypoints_have_no_side_effect_or_followup_play(self) -> None:
        """Verify retired entrypoints have no side effect or followup play."""
        for name in [
            "rancher",
            "litellm",
            "llm-vision",
            "monitoring-llm",
            "open-terminal",
            "searxng",
            "search",
            "open-webui",
            "open-webui-upgrade",
            "open-webui-https",
            "open-webui-tool-guard",
            "open-terminal-browser-cleanup",
        ]:
            with self.subTest(name=name):
                plays = yaml.safe_load((ROOT / f"ansible/playbooks/{name}.yml").read_text())
                assert len(plays) == 1  # No imports after a failed play.
                play = plays[0]
                assert not play["gather_facts"]
                assert not play["become"]
                assert play["any_errors_fatal"]
                assert set(play) == {
                    "name",
                    "hosts",
                    "gather_facts",
                    "become",
                    "any_errors_fatal",
                    "tasks",
                }
                assert len(play["tasks"]) == 1
                task = play["tasks"][0]
                assert set(task) == {"name", "ansible.builtin.fail", "tags"}
                assert "always" in task["tags"]
                paths = {
                    **{
                        name: [
                            "deploy/argocd/apps/open-webui.yaml",
                            "charts/open-webui",
                        ]
                        for name in [
                            "open-webui",
                            "open-webui-upgrade",
                            "open-webui-https",
                            "open-webui-tool-guard",
                        ]
                    },
                    "open-terminal-browser-cleanup": [
                        "deploy/argocd/apps/open-terminal.yaml",
                        "charts/open-terminal",
                    ],
                    "open-terminal": [
                        "deploy/argocd/apps/open-terminal.yaml",
                        "charts/open-terminal",
                    ],
                    "searxng": ["deploy/argocd/apps/searxng.yaml", "charts/searxng"],
                    "search": [
                        "deploy/argocd/apps/searxng.yaml",
                        "charts/searxng",
                        "deploy/argocd/apps/open-webui.yaml",
                    ],
                    "llm-vision": [
                        "deploy/argocd/apps/vllm.yaml",
                        "deploy/argocd/apps/litellm.yaml",
                    ],
                    "monitoring-llm": [
                        "deploy/argocd/apps/monitoring-llm.yaml",
                        "charts/monitoring-llm",
                    ],
                }.get(
                    name,
                    [
                        f"deploy/argocd/apps/{name}.yaml",
                        f"charts/{name}",
                        f"deploy/platform/{name}/values.yaml",
                    ],
                )
                for path in paths:
                    assert path in task["ansible.builtin.fail"]["msg"]
                    assert (ROOT / path).exists()

    def test_retirement_preserves_chart_owned_protection_intent(self) -> None:
        """Verify retirement preserves chart owned protection intent."""
        webui = yaml.safe_load((ROOT / "charts/open-webui/values.yaml").read_text())
        terminal = yaml.safe_load((ROOT / "charts/open-terminal/values.yaml").read_text())
        assert webui["toolGuard"]["enabled"]
        assert webui["gateway"]["redirectHttps"]
        assert terminal["browserCleanup"]["enabled"]
        max_age_seconds = 900
        assert terminal["browserCleanup"]["maxAgeSeconds"] == max_age_seconds
        for name in ["open-webui", "open-terminal"]:
            app = yaml.safe_load((ROOT / f"deploy/argocd/apps/{name}.yaml").read_text())
            assert app["spec"]["source"]["path"] == "charts/" + name
            assert app["spec"]["source"]["helm"]["releaseName"] == name
            assert app["spec"]["destination"]["namespace"] == "llm"

    def test_monitoring_entrypoint_only_imports_fail_closed_guard(self) -> None:
        """Verify monitoring entrypoint only imports fail closed guard."""
        tasks = yaml.safe_load((ROOT / "ansible/roles/monitoring_stack/tasks/main.yml").read_text())
        assert len(tasks) == 1
        assert tasks[0]["ansible.builtin.import_tasks"] == "gitops-guard.yml"
        guard = yaml.safe_load(
            (ROOT / "ansible/roles/monitoring_stack/tasks/gitops-guard.yml").read_text()
        )
        assert len(guard) == 1
        assert set(guard[0]) == {"name", "ansible.builtin.fail", "tags"}
        assert "always" in guard[0]["tags"]

    def test_argocd_bootstrap_version_and_values_match_git_owner(self) -> None:
        """Verify argocd bootstrap version and values match git owner."""
        bootstrap = yaml.safe_load((ROOT / "ansible/playbooks/argocd.yml").read_text())[0]
        app = yaml.safe_load((ROOT / "deploy/argocd/apps/argo-cd.yaml").read_text())
        source = next(s for s in app["spec"]["sources"] if s.get("chart") == "argo-cd")
        assert str(bootstrap["vars"]["argocd_chart_version"]) == str(source["targetRevision"])
        values = source["helm"]["valueFiles"][0].removeprefix("$values/")
        assert bootstrap["vars"]["argocd_values_local"] == "{{ playbook_dir }}/../../" + values


if __name__ == "__main__":
    unittest.main()
