import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

BASE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sync", BASE / "scripts/n8n/sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

# The rendered workflow keeps six nodes: trigger, calendar read, two voice nodes,
# and the receipt/update pair.
WORKFLOW_NODE_COUNT = 6


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.template = json.loads((BASE / "docs/n8n/calendar-voice-reminder.json").read_text())
        self.creds = {
            k: {"id": "test-id", "name": "Test"}
            for k in ["googleCalendarOAuth2Api", "yandexStationApi"]
        }

    def render(self):
        return sync.render_workflow(
            self.template, self.creds, {"calendar_ids": ["primary", "work@example.test"]}
        )

    def test_render_scoped_native_node(self):
        w = self.render()
        raw = json.dumps(w)
        assert "REPLACE_WITH_" not in raw
        assert "httpCustomAuth" not in raw
        assert len(w["nodes"]) == WORKFLOW_NODE_COUNT
        calls = [n for n in w["nodes"] if n["type"] == "CUSTOM.yandexStation"]
        assert len(calls) == 1
        assert calls[0]["parameters"]["text"] == "={{ $json.text }}"
        assert not calls[0]["retryOnFail"]
        assert "iot.quasar.yandex.ru" not in raw
        assert "xToken" not in raw

    def test_raw_internal_http_forbidden(self):
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
        with self.assertRaises(RuntimeError):
            sync.render_workflow(self.template, {}, {})

    def test_maintenance_renews_without_speech(self):
        t = json.loads((BASE / "docs/n8n/yandex-session-maintenance.json").read_text())
        w = sync.render_workflow(t, self.creds, {})
        n = next(n for n in w["nodes"] if n["type"] == "CUSTOM.yandexStation")
        assert n["parameters"]["operation"] == "check"
        assert not n["parameters"]["forceRefresh"]

    def test_failed_call_does_not_mark(self):
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
