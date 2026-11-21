"""Read the generated mutmut 3.8.1 sources, not self-reported historic exit codes."""
import ast, collections, gzip, hashlib, json, pathlib, re, sys

def extract(root: pathlib.Path):
    families={}
    for meta in sorted(root.rglob('*.py.meta')):
        f=meta.with_suffix(''); src=f.read_text();lines=src.splitlines(keepends=True);module=str(f.relative_to(root)).removesuffix('.py').replace('/','.');gen=collections.defaultdict(dict)
        for n in ast.walk(ast.parse(src)):
            if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
            m=re.fullmatch(r'(x(?:_|ǁ).+)__mutmut_(orig|\d+)',n.name)
            if not m:continue
            fam,num=m.groups();name=fam.split('ǁ')[-1] if 'ǁ' in fam else fam[2:];body=lines[n.lineno-1:n.end_lineno].copy();body[0]=body[0].replace('def '+n.name+'(', 'def '+name+'(',1);gen[fam][num]=body
        for fam,g in gen.items():
            if 'orig' not in g:continue
            old=g.pop('orig');d={}
            for num,body in g.items():
                left=0;right=0
                while left<min(len(body),len(old)) and body[left]==old[left]:left+=1
                while right<min(len(body),len(old))-left and body[-1-right]==old[-1-right]:right+=1
                if left==len(body)==len(old):continue
                d[num]=[left,len(old)-right,body[left:len(body)-right]]
            families['monori.'+module+'.'+fam]={'file':str(f.relative_to(root)),'old':old,'diffs':d}
    return families
if __name__=='__main__':
    root=next(pathlib.Path.home().glob('.openhands/agent-canvas/workspaces/75ad*/repo/mutants'));b=json.dumps(extract(root),separators=(',',':')).encode();sys.stdout.buffer.write(gzip.compress(b,mtime=0))
