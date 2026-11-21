"""Tests for the OpenHands pi-monori service configuration and scripts."""
import importlib.util
import os
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[2]

def module(name):
    old=os.getcwd();mask=os.umask(0o077)
    try:
        spec=importlib.util.spec_from_file_location(name,ROOT/"services/pi-monori"/f"{name}.py");m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    finally:os.chdir(old);os.umask(mask)

class PiPilot(unittest.TestCase):
    def test_report_and_admission_are_distinct(self) -> None:
        d=module("dispatcher");rows=module("cards").plan((ROOT/"services/pi-monori/issue509.md").read_text());self.assertEqual(len(rows),405);self.assertEqual(len({x["id"] for x in rows}),405);self.assertEqual(len(d.CARDS),2)

    def test_gate(self) -> None:
        d=module("dispatcher");valid="from "+ 'monori.common.json_values import integer_value\n\ndef test_case() -> None:\n    assert integer_value(3, "fixture") == 3\n';d.inspect_test(valid,"integer_value")
        for bad in [valid.replace('assert integer_value(3, "fixture") == 3',"assert True"),valid+"\nimport os\n",valid.replace("== 3",'== eval("3")')]:
            with self.assertRaises(ValueError):d.inspect_test(bad,"integer_value")
