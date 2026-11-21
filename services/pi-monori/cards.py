"""Compile #509 report into durable assignments. Backlog != passed or admitted."""
import json,re,pathlib,sys

def plan(text: str):
    rows=[];section=None
    for line in text.splitlines():
        if line.startswith('### '):section=line[4:].split(' (')[0]
        m=re.fullmatch(r'(\d+) (monori\.[\w.ǁ]+)',line.strip());t=re.fullmatch(r'(monori\.[\w.ǁ]+__mutmut_\d+)',line.strip()) if section=='Timeouts' else None
        if not (m or t):continue
        if m:n,f=int(m[1]),m[2]
        else:n,f=1,t[1]
        rows.append({'id':f'{len(rows)+1:03d}','section':section,'family':f,'reported':n,'prompt':f'#509; {section}: {f} ({n} reported). On a fresh main, inspect existing tests and open PRs. Work on at most one distinguishable behavior/1–5 related mutants. Demonstrate the exact mutant ID and focused old-green/new-red/original-green. For timeouts use resource limits, not live systems. No unrelated edits. Already killed, equivalent, duplicate or insufficient evidence: document and skip; no fake PR. Do not merge.'})
    return rows
if __name__=='__main__':
    root=pathlib.Path(sys.argv[1]);rows=plan((root/'issue509.md').read_text());assert len(rows)>300;(root/'backlog.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False));print('backlog',len(rows))
