import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

BASE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sync", BASE / "scripts/n8n/sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class CalendarTests(unittest.TestCase):
    def setUp(self):
        """Load the rendered calendar workflow fixture."""
        self.template = json.loads((BASE / "docs/n8n/calendar-voice-reminder.json").read_text())
        self.creds = {
            k: {"id": "test-id", "name": "Test"}
            for k in ["googleCalendarOAuth2Api", "yandexStationApi"]
        }

    def render(self):
        """Render the workflow under the validated test inputs."""
        return sync.render_workflow(
            self.template, self.creds, {"calendar_ids": ["primary", "work@example.test"]}
        )

    def test_render_scoped_native_node(self):
        """Verify the workflow renders the scoped native node."""
        w = self.render()
        raw = json.dumps(w)
        self.assertNotIn("REPLACE_WITH_", raw)
        self.assertNotIn("httpCustomAuth", raw)
        self.assertEqual(len(w["nodes"]), 6)
        calls = [n for n in w["nodes"] if n["type"] == "CUSTOM.yandexStation"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["parameters"]["text"], "={{ $json.text }}")
        self.assertFalse(calls[0]["retryOnFail"])
        self.assertNotIn("iot.quasar.yandex.ru", raw)
        self.assertNotIn("xToken", raw)

    def test_raw_internal_http_forbidden(self):
        """Verify raw internal HTTP request nodes are forbidden."""
        for url in [
            "https://iot.quasar.yandex.ru/m/user/scenarios/x/actions",
            "http://api.iot.yandex.net/v1.0/scenarios/x/actions",
            "https://api.iot.yandex.net.evil.test/v1.0/scenarios/x/actions",
        ]:
            w = self.render()
            w["nodes"].append({"type": "n8n-nodes-base.httpRequest", "parameters": {"url": url}})
            with self.assertRaises(RuntimeError):
                sync.require_yandex_policy(w)

    def test_missing_auth_rejected(self):
        """Verify a node without the prepared auth is rejected."""
        with self.assertRaises(RuntimeError):
            sync.render_workflow(self.template, {}, {})

    def test_maintenance_renews_without_speech(self):
        """Verify session maintenance renews silently, not over speech."""
        t = json.loads((BASE / "docs/n8n/yandex-session-maintenance.json").read_text())
        w = sync.render_workflow(t, self.creds, {})
        n = next(n for n in w["nodes"] if n["type"] == "CUSTOM.yandexStation")
        self.assertEqual(n["parameters"]["operation"], "check")
        self.assertFalse(n["parameters"]["forceRefresh"])

    def test_failed_call_does_not_mark(self):
        """Verify a failed voice call does not mark attendance."""
        code = next(n for n in self.render()["nodes"] if n["name"] == "Mark Announced")[
            "parameters"
        ]["jsCode"]
        script = (
            'const s={};const f=new Function("items","$getWorkflowStaticData","$",'
            + json.dumps(code)
            + ');try{f([{json:{status:"error"}}],()=>s,()=>({itemMatching:()=>({json:{dedupKey:"a"}})}));process.exit(1)}catch(e){};if(s.voiced.a)process.exit(2);f([{json:{status:"ok"}}],()=>s,()=>({itemMatching:()=>({json:{dedupKey:"a"}})}));if(!s.voiced.a)process.exit(3);'
        )
        subprocess.check_call(["node", "-e", script])

    def test_due_matching_and_dedup(self):
        """Verify due-event matching and per-episode deduplication."""
        code = next(n for n in self.render()["nodes"] if n["name"] == "Match Due Reminders")[
            "parameters"
        ]["jsCode"]
        event = {
            "id": "event-test",
            "summary": "Meeting",
            "start": {"dateTime": "2026-11-03T14:00:00+03:00"},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]},
        }
        script = (
            'Date.now=()=>Date.parse("2026-11-03T13:50:00+03:00");const s={};const f=new Function("items","$getWorkflowStaticData",'
            + json.dumps(code)
            + ");const a=f([{json:"
            + json.dumps(event)
            + "}],()=>s);if(a.length!==1)process.exit(1);s.voiced[a[0].json.dedupKey]=Date.now();if(f([{json:"
            + json.dumps(event)
            + "}],()=>s).length)process.exit(2);"
        )
        subprocess.check_call(["node", "-e", script])


if __name__ == "__main__":
    unittest.main()
