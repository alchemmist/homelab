"""Exercise the production dispatch state machine with persisted test state, no live calls."""

import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

CODE = pathlib.Path(__file__).resolve().parents[2] / "charts/openhands/files/pilot"


def load():
    m = types.ModuleType("pilot")
    with patch.object(pathlib.Path, "read_text", return_value=(CODE / "mutants.json").read_text()):
        exec(compile((CODE / "loop.py").read_bytes(), "loop.py", "exec"), m.__dict__)
    return m


class Pilot(unittest.TestCase):
    def test_restart_moves_to_second_card_once(self):
        with tempfile.TemporaryDirectory() as d:
            # The pilot publishes each card once: two distinct PRs across the run.
            unique_pr_count = 2
            db = str(pathlib.Path(d) / "cards.db")
            published = []
            prompts = []
            chats = {}

            def api(path, body=None):
                if path.startswith("agent-profiles"):
                    return {"profile": {"id": "p", "llm_profile_ref": "v-deepseek-uc"}}
                if path == "conversations":
                    chats[body["conversation_id"]] = "idle"
                    return {}
                cid = path.split("/")[1]
                if cid not in chats:
                    raise m.HTTPError("", 404, "missing", {}, None)
                if path.endswith("/events"):
                    prompts.append(cid)
                    chats[cid] = "finished"
                    return {}
                if "/events/search?" in path:
                    return {
                        "items": []
                        if chats[cid] == "idle"
                        else [
                            {
                                "kind": "MessageEvent",
                                "source": "agent",
                                "llm_message": {
                                    "content": [
                                        {
                                            "text": '{"input":"2020-01-01","expected":3,"why":"test fixture"}'
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                return {
                    "execution_status": chats[cid],
                    "agent": {"llm": {"model": "openai/v-deepseek-uc"}},
                }

            for step in range(10):
                m = load()
                m.DB = db
                m.init()

                def screen(c):
                    mid = next(iter(m.CAT[c["name"]]))
                    m.sql("insert into scans values(?,?,?)", (c["name"], mid, "survived"))
                    m.save(c, "queued", mid)

                with (
                    patch.object(m, "screen", side_effect=screen),
                    patch.object(
                        pathlib.Path,
                        "read_text",
                        return_value=json.dumps({"day_number": "facts", "_amount": "facts"}),
                    ),
                    patch.object(m, "api", side_effect=api),
                    patch.object(m, "verify", return_value=("test.py", "test", "receipt")),
                    patch.object(
                        m,
                        "http",
                        side_effect=lambda *a: published.append(1) or {"pr": len(published)},
                    ),
                    patch.object(pathlib.Path, "read_bytes", return_value=b"test"),
                    patch.object(m.time, "time", return_value=100 * step),
                ):
                    m.step(m.decision())
            assert [r["state"] for r in m.state()] == ["published", "published"]
            assert len(set(prompts)) == unique_pr_count
            assert len(published) == unique_pr_count

    def test_case_is_data_not_python(self):
        m = load()
        self.assertRaises(
            AssertionError,
            m.render,
            "day_number",
            {"input": {}, "expected": 1, "why": "candidate input"},
        )
        self.assertRaises(
            ValueError,
            m.render,
            "_amount",
            {"input": 2, "expected": 2, "why": "candidate input", "code": "assert True"},
        )

    def test_proleptic_gregorian_and_rejection_identity(self):
        m = load()
        case = {"input": "0000-02-29", "expected": 2, "why": "calendar fixture"}
        assert "0000-02-29" in m.render("day_number", case)
        for date in ("0000-02-30", "0001-02-29", "2025-13-01", "0000/01/01"):
            with self.assertRaises((ValueError, AssertionError)):
                m.render("day_number", {**case, "input": date})
        with tempfile.TemporaryDirectory() as d:
            m.DB = str(pathlib.Path(d) / "cards.db")
            m.init()
            m.sql(
                "insert into rejections values(?,?,?,?)",
                ("_amount", "m", m.pair(case), "measured null"),
            )
            assert m.rejected("_amount", "m", {**case, "why": "different explanation"})
            assert not m.rejected("_amount", "other", case)
            assert not m.rejected("_amount", "m", {**case, "expected": None})
