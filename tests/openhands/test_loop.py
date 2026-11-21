import importlib.util
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("demo_validation", ROOT/"scripts/validate-openhands-demo.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class LoopSetup(unittest.TestCase):
    def test_official_mcp_is_version_and_integrity_pinned(self):
        p = json.loads((ROOT/"tools/openhands-mcp/package-lock.json").read_text())
        fs = p["packages"]["node_modules/@modelcontextprotocol/server-filesystem"]
        self.assertEqual(fs["version"],"2.4.0")
        self.assertEqual(fs["integrity"],"sha512-BoT8Gws5MsetfAey4vDyuzy8WYQES6mGYLSShuqSNGAC0X0NBV4p78/R78KfW4RkxtWz+zxhS9jwhzJrQUTt2Q==")

    def test_local_scheduler_callbacks_do_not_cross_browser_oidc(self):
        values = yaml.safe_load((ROOT/"deploy/openhands/values.yaml").read_text())
        env = {x["name"]:x.get("value") for x in values["config"]["extraEnv"]}
        self.assertEqual(env["AUTOMATION_BASE_URL"],"http://127.0.0.1:8000")
        self.assertTrue(values["oidc"]["enabled"])
        self.assertFalse(values["ingress"]["enabled"])

    def test_schedule_is_paused_bounded_and_uses_pinned_image_sdk(self):
        c=json.loads((ROOT/"services/openhands/the-loop-demo/schedule.json").read_text())
        self.assertFalse(c["enabled"])
        self.assertFalse(c["keep_alive"])
        self.assertEqual(c["timeout"],300)
        self.assertEqual(c["trigger"]["timezone"],"Europe/Moscow")
        self.assertEqual(c["runtime"],{"setup_script_path":None,"entrypoint":"python main.py"})

    def test_overlapping_network_policies_fail_closed(self):
        labels={"app":"fixture","homelab-app":"openhands-demo-validation"}
        self.assertTrue(m.selector_matches({},labels))
        self.assertFalse(m.selector_matches({"matchLabels":{"app":"authentik-postgres"}},labels))
        self.assertTrue(m.selector_matches({"matchExpressions":[{"key":"app","operator":"In","values":["fixture"]}]},labels))
        self.assertTrue(m.selector_matches({"matchExpressions":[{"key":"missing","operator":"NotIn","values":["x"]}]},labels))
        self.assertFalse(m.selector_matches({"matchExpressions":[{"key":"app","operator":"DoesNotExist"}]},labels))
        with self.assertRaises(ValueError):m.selector_matches({"matchExpressions":[{"key":"app","operator":"Unknown"}]},labels)

    def test_independent_review_has_no_network_or_credentials(self):
        cm,np,job = m.resources("fixture-name","candidate-code","original-tests")
        self.assertEqual(cm["data"]["test_intervals.py"],"original-tests")
        self.assertEqual(np["spec"]["egress"],[])
        pod=job["spec"]["template"]["spec"];c=pod["containers"][0]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertNotIn("serviceAccountName",pod)
        self.assertNotIn("hostNetwork",pod)
        self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
        self.assertTrue(c["volumeMounts"][0]["readOnly"])
        self.assertEqual(pod["volumes"],[{"name":"snapshot","configMap":{"name":"fixture-name"}}])
        self.assertEqual(job["spec"]["backoffLimit"],0)
        self.assertEqual(job["spec"]["activeDeadlineSeconds"],45)


if __name__=="__main__":unittest.main()
