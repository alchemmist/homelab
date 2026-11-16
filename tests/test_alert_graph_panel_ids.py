import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('alert_graphs',ROOT/'scripts/alert_graphs.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def rule(name):
    return {'owner':'fixture','resource':'fixture','group':'group',
            'rule':{'alert':name,'expr':'up == 0','labels':{}}}

class StablePanelIds(unittest.TestCase):
    def test_insert_before_existing_does_not_renumber_links(self):
        ids={}
        _,old,_=m.build([rule('Bravo'),rule('Zulu')],ids)
        _,new,_=m.build([rule('Alpha'),rule('Bravo'),rule('Zulu')],ids)
        for name in ['Bravo','Zulu']:
            self.assertEqual(old['fixture'][name],new['fixture'][name])
        self.assertEqual(new['fixture']['Alpha']['graphs'][0]['panel_id'],5)
    def test_removed_rule_id_is_not_reused(self):
        ids={};m.build([rule('Alpha'),rule('Bravo')],ids)
        _,new,_=m.build([rule('Charlie')],ids)
        self.assertEqual(new['fixture']['Charlie']['graphs'][0]['panel_id'],5)
    def test_duplicate_and_even_ids_fail_closed(self):
        for values in [{'A':1,'B':1},{'A':2},{'A':True}]:
            with self.assertRaises(ValueError):m.build([],{'fixture':values})
    def test_stable_fixed_point(self):
        ids={};a=m.build([rule('Bravo')],ids);snapshot=copy.deepcopy(ids)
        b=m.build([rule('Bravo')],ids)
        self.assertEqual(a,b);self.assertEqual(ids,snapshot)

if __name__=='__main__':unittest.main()
