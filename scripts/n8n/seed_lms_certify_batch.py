#!/usr/bin/env python3
import json
from pathlib import Path
import yaml
from lms_reviewed_batch import SPECS
root=Path(__file__).resolve().parents[2].parent/'lms/content/courses/programming/blocks/basics/lessons'
def sql(s):return "'"+s.replace("'","''")+"'"
print('BEGIN;')
for key,(contract,stdin,stdout,faults) in SPECS.items():
 lesson,task=key.split('/');path=root/lesson/'tasks'/task
 suite=yaml.safe_load((path/'tests.yaml').read_text())
 examples=[{'input':c['input'],'output':c['output']} for c in suite.get('cases',[]) if c.get('public')]
 data=dict(statement=(path/'statement.md').read_text(),contract=contract,calls=0,cases=[],examples=examples or [dict(input=stdin,output=stdout)],example_origin='canonical' if examples else 'operator_fixture',faults=[['empty','pass'],*faults])
 if contract=='heights':data['coverageHints']='Для отличия строковой сортировки от числовой используй 99, 100, 101 в разных порядках; для потери повторов — одинаковые значения.'
 if contract=='temperature':data['coverageHints']='Проверь ровно 15.5, ровно 28, а также 15.4, 15.6 и 28.1.'
 print('INSERT INTO lms_certification.pilot(id,phase,data) VALUES ('+sql('basics/'+key)+",'solve',"+sql(json.dumps(data,ensure_ascii=False))+"::jsonb) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data WHERE pilot.phase='solve' AND pilot.data->>'contract'='draft_stdin' AND coalesce((pilot.data->>'calls')::int,0)=0;")
print('COMMIT;')
