import copy
import importlib.util
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alert_graphs", ROOT / "scripts/alert_graphs.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def rule(name):
    return {
        "owner": "fixture",
        "resource": "fixture",
        "group": "group",
        "rule": {"alert": name, "expr": "up == 0", "labels": {}},
    }


class StablePanelIds(unittest.TestCase):
    def test_insert_before_existing_does_not_renumber_links(self):
        ids = {}
        _, old, _ = m.build([rule("Bravo"), rule("Zulu")], ids)
        _, new, _ = m.build([rule("Alpha"), rule("Bravo"), rule("Zulu")], ids)
        for name in ["Bravo", "Zulu"]:
            assert old["fixture"][name] == new["fixture"][name]
        next_panel_id = 5
        assert new["fixture"]["Alpha"]["graphs"][0]["panel_id"] == next_panel_id

    def test_removed_rule_id_is_not_reused(self):
        ids = {}
        m.build([rule("Alpha"), rule("Bravo")], ids)
        _, new, _ = m.build([rule("Charlie")], ids)
        next_panel_id = 5
        assert new["fixture"]["Charlie"]["graphs"][0]["panel_id"] == next_panel_id

    def test_duplicate_and_even_ids_fail_closed(self):
        for values in [{"A": 1, "B": 1}, {"A": 2}, {"A": True}]:
            with pytest.raises(
                ValueError, match="Invalid or duplicate persistent panel IDs: fixture"
            ):
                m.build([], {"fixture": values})

    def test_stable_fixed_point(self):
        ids = {}
        a = m.build([rule("Bravo")], ids)
        snapshot = copy.deepcopy(ids)
        b = m.build([rule("Bravo")], ids)
        assert a == b
        assert ids == snapshot


if __name__ == "__main__":
    unittest.main()
