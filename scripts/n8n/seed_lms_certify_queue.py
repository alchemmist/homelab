#!/usr/bin/env python3
"""Emit private SQL queue entries from actual statements and public examples."""
import json
from pathlib import Path
import yaml
root=Path(__file__).resolve().parents[2].parent/"lms/content/courses/programming/blocks/basics/lessons/builtin-functions/tasks"
contracts={
 "add-two-numbers":("sum",[
 ("subtract","a=int(input());b=int(input());print(a-b)"),
 ("concatenate","print(input()+input())"),("ignore second","print(int(input()))"),
 ("absolute sum","print(abs(int(input())+int(input())))")], [{"input":"3\n5\n","output":"8\n"}]),
 "length":("length",[
 ("strip spaces","s=input().strip();print(f'Слово {s} имеет длину {len(s)}')"),
 ("off by one","s=input();print(f'Слово {s} имеет длину {len(s)+1}')"),
 ("ascii bytes","s=input();print(f'Слово {s} имеет длину {len(s.encode())}')")],[]),
 "halve":("parity",[
 ("invert parity","print('нечётное' if int(input())%2==0 else 'чётное')"),
 ("zero not even","n=int(input());print('чётное' if n and n%2==0 else 'нечётное')"),
 ("negative not even","n=int(input());print('чётное' if n>0 and n%2==0 else 'нечётное')")],[{"input":"2\n","output":"чётное\n"}]),
 "plus-minus":("sign",[
 ("zero positive","n=float(input());print('+' if n>=0 else '-')"),
 ("truncate decimals","n=int(float(input()));print('+' if n>0 else '-' if n<0 else '0')"),
 ("ignore negative","n=float(input());print('+' if n!=0 else '0')")],[{"input":"2.5\n","output":"+\n"}]),
}
contracts["leap-year"]=("leap",[
 ("only divisible by four","y=int(input());print('Високосный' if y%4==0 else 'Не високосный')"),
 ("exclude all centuries","y=int(input());print('Високосный' if y%4==0 and y%100!=0 else 'Не високосный')"),
 ("only multiples of 400","y=int(input());print('Високосный' if y%400==0 else 'Не високосный')"),
 ("always leap","input();print('Високосный')")],[])
print("BEGIN;")
for task,(contract,faults,fixtures) in contracts.items():
 path=root/task
 suite=yaml.safe_load((path/"tests.yaml").read_text())
 examples=[{"input":c["input"],"output":c["output"]} for c in suite.get("cases",[]) if c.get("public")]
 data={"statement":(path/"statement.md").read_text(),"contract":contract,"examples":examples or fixtures,"example_origin":"canonical" if examples else "operator_fixture","faults":[["empty program","pass"],*faults],"calls":0,"cases":[]}
 def sql(s):return "'"+s.replace("'","''")+"'"
 print("INSERT INTO lms_certification.pilot(id,phase,data) VALUES ("+sql("basics/builtin-functions/"+task)+",'solve',"+sql(json.dumps(data,ensure_ascii=False))+"::jsonb) ON CONFLICT (id) DO UPDATE SET data=EXCLUDED.data WHERE pilot.phase='solve' AND pilot.data->>'contract'='draft_stdin' AND coalesce((pilot.data->>'calls')::int,0)=0;")
print("COMMIT;")
