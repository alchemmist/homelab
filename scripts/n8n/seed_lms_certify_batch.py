#!/usr/bin/env python3
import json
from pathlib import Path
import yaml
from lms_reviewed_batch import SPECS
root=Path(__file__).resolve().parents[2].parent/"lms/content/courses/programming/blocks/basics/lessons"
def sql(s):return "'"+s.replace("'","''")+"'"
print("BEGIN;")
for key,(contract,stdin,stdout,faults) in SPECS.items():
 lesson,task=key.split("/");path=root/lesson/"tasks"/task
 suite=yaml.safe_load((path/"tests.yaml").read_text())
 examples=[{"input":c["input"],"output":c["output"]} for c in suite.get("cases",[]) if c.get("public")]
 data=dict(statement=(path/"statement.md").read_text(),contract=contract,calls=0,cases=[],examples=examples or [dict(input=stdin,output=stdout)],example_origin="canonical" if examples else "operator_fixture",faults=[["empty","pass"],*faults])
 if contract=="noinput_reviewed":
  data.update(examples=examples,example_origin="canonical" if examples else "none",reviewedOutput=stdout)
 if contract=="beautiful_digits":
  data["targetedCases"]=[dict(input="513\n",output="Вы ввели красивое число\n"),dict(input="777\n",output="Вы ввели красивое число\n"),dict(input="124\n",output="Жаль, вы ввели обычное число\n")]
 if contract=="adjacent_sums":
  data["targetedCases"]=[dict(input="258\n",output="137\n")]
 if contract=="thank_count":
  data["targetedCases"]=[dict(input="спасибо.\n Спасибо. \nСпасибо.\n",output="3\n")]
 if contract in ("xmas2","xmas3"):
  prereqs=["xmas-tree"]+(["xmas-tree-2"] if contract=="xmas3" else [])
  data["statement"]="\n\n".join([(path.parent / name / "statement.md").read_text() for name in prereqs]+[data["statement"]])
  data["targetedCases"]=[dict(input=x,output="НЕ ГОРИ\n") for x in ("раз\n2\nтри\n","3\n2\n1\n","1 \n2\n3\n")]
 if contract.startswith("until_"):
  assert examples, "Loop contract requires canonical examples"
  cases={"until_zero":("-2\n1\n0\n9\n","-2\n1\n"),"until_nonmultiple":("0\n-20\n4\n10\n","0\n-20\n"),"until_empty":(" \na\n\nлишнее\n"," \na\n")}
  x,y=cases[contract];data["targetedCases"]=[dict(input=x,output=y)]
 if contract=="xmas":
  data["coverageHints"]="Допустимы только слова раз, два, три в этом порядке. Цифры 1,2,3 не подходят."
  data["targetedCases"]=[dict(input="1\n2\n3\n",output="НЕ ГОРИ\n")]
 if contract=="yes_no":data["repairGuidance"]="Только точные слова да и нет: пробелы и регистр значимы. Нельзя strip() или lower()."
 if contract in ("parrot","reverse"):
  values=[" left "," mid "," right "]
  data["targetedCases"]=[dict(input="\n".join(values)+"\n",output="\n".join(values if contract=="parrot" else values[::-1])+"\n")]
  data["coverageHints"]="Проверь сохранение ведущих и завершающих пробелов каждой строки."
 if contract=="heights":data["coverageHints"]="Для отличия строковой сортировки от числовой используй 99, 100, 101 в разных порядках; для потери повторов — одинаковые значения."
 if contract=="temperature":data["coverageHints"]="Проверь ровно 15.5, ровно 28, а также 15.4, 15.6 и 28.1."
 print("INSERT INTO lms_certification.pilot(id,phase,data) VALUES ("+sql("basics/"+key)+",'solve',"+sql(json.dumps(data,ensure_ascii=False))+"::jsonb) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data WHERE pilot.phase='solve' AND pilot.data->>'contract'='draft_stdin' AND coalesce((pilot.data->>'calls')::int,0)=0;")
print("COMMIT;")
