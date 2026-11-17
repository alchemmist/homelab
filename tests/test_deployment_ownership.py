"""Offline ownership boundaries, not permission to execute production playbooks."""

from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class DeploymentOwnership(unittest.TestCase):
    def test_retired_entrypoints_have_no_side_effect_or_followup_play(self):
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
                self.assertEqual(len(plays), 1)  # No imports after a failed play.
                play = plays[0]
                self.assertFalse(play["gather_facts"])
                self.assertFalse(play["become"])
                self.assertTrue(play["any_errors_fatal"])
                self.assertEqual(
                    set(play),
                    {"name", "hosts", "gather_facts", "become", "any_errors_fatal", "tasks"},
                )
                self.assertEqual(len(play["tasks"]), 1)
                task = play["tasks"][0]
                self.assertEqual(set(task), {"name", "ansible.builtin.fail", "tags"})
                self.assertIn("always", task["tags"])
                paths = {
                    **{
                        name: ["deploy/argocd/apps/open-webui.yaml", "charts/open-webui"]
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
                    self.assertIn(path, task["ansible.builtin.fail"]["msg"])
                    self.assertTrue((ROOT / path).exists())

    def test_retirement_preserves_chart_owned_protection_intent(self):
        webui = yaml.safe_load((ROOT / "charts/open-webui/values.yaml").read_text())
        terminal = yaml.safe_load((ROOT / "charts/open-terminal/values.yaml").read_text())
        self.assertTrue(webui["toolGuard"]["enabled"])
        self.assertTrue(webui["gateway"]["redirectHttps"])
        self.assertTrue(terminal["browserCleanup"]["enabled"])
        self.assertEqual(terminal["browserCleanup"]["maxAgeSeconds"], 900)
        for name in ["open-webui", "open-terminal"]:
            app = yaml.safe_load((ROOT / f"deploy/argocd/apps/{name}.yaml").read_text())
            self.assertEqual(app["spec"]["source"]["path"], "charts/" + name)
            self.assertEqual(app["spec"]["source"]["helm"]["releaseName"], name)
            self.assertEqual(app["spec"]["destination"]["namespace"], "llm")

    def test_monitoring_entrypoint_only_imports_fail_closed_guard(self):
        tasks = yaml.safe_load((ROOT / "ansible/roles/monitoring_stack/tasks/main.yml").read_text())
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["ansible.builtin.import_tasks"], "gitops-guard.yml")
        guard = yaml.safe_load(
            (ROOT / "ansible/roles/monitoring_stack/tasks/gitops-guard.yml").read_text()
        )
        self.assertEqual(len(guard), 1)
        self.assertEqual(set(guard[0]), {"name", "ansible.builtin.fail", "tags"})
        self.assertIn("always", guard[0]["tags"])

    def test_argocd_bootstrap_version_and_values_match_git_owner(self):
        bootstrap = yaml.safe_load((ROOT / "ansible/playbooks/argocd.yml").read_text())[0]
        app = yaml.safe_load((ROOT / "deploy/argocd/apps/argo-cd.yaml").read_text())
        source = next(s for s in app["spec"]["sources"] if s.get("chart") == "argo-cd")
        self.assertEqual(
            str(bootstrap["vars"]["argocd_chart_version"]), str(source["targetRevision"])
        )
        values = source["helm"]["valueFiles"][0].removeprefix("$values/")
        self.assertEqual(
            bootstrap["vars"]["argocd_values_local"], "{{ playbook_dir }}/../../" + values
        )


if __name__ == "__main__":
    unittest.main()
