import importlib.util
import os
import pathlib
import unittest
from types import ModuleType

ROOT = pathlib.Path(__file__).resolve().parents[2]

# issue509.md plans exactly this many cards; only two of them are admitted to CARDS.
PLANNED_CARDS = 405
ADMITTED_CARDS = 2


def module(name: str) -> ModuleType:
    old = os.getcwd()
    mask = os.umask(0o077)
    try:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "services/pi-monori" / f"{name}.py"
        )
        if spec is None or spec.loader is None:
            load_error = f"cannot load pi-monori module {name!r}"
            raise RuntimeError(load_error)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        os.chdir(old)
        os.umask(mask)


class PiPilot(unittest.TestCase):
    def test_report_and_admission_are_distinct(self):
        d = module("dispatcher")
        rows = module("cards").plan((ROOT / "services/pi-monori/issue509.md").read_text())
        assert len(rows) == PLANNED_CARDS
        assert len({x["id"] for x in rows}) == PLANNED_CARDS
        assert len(d.CARDS) == ADMITTED_CARDS

    def test_gate(self):
        d = module("dispatcher")
        valid = (
            "from monori.common.json_values import integer_value\n"
            "\n"
            "def test_case() -> None:\n"
            '    assert integer_value(3, "fixture") == 3\n'
        )
        d.inspect_test(valid, "integer_value")
        for bad in [
            valid.replace('assert integer_value(3, "fixture") == 3', "assert True"),
            valid + "\nimport os\n",
            valid.replace("== 3", '== eval("3")'),
        ]:
            with self.assertRaises(ValueError):
                d.inspect_test(bad, "integer_value")
