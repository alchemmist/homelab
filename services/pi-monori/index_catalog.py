"""Read the generated mutmut 3.8.1 sources, not self-reported historic exit codes."""
import ast, collections, gzip, hashlib, json, pathlib, re, sys

def _mutant_bodies(
    f: pathlib.Path, lines: list[str]
) -> dict[str, dict[str, list[str]]]:
    """Map each mutmut family to the source lines of its generated variants."""
    src=f.read_text();gen: dict[str, dict[str, list[str]]]=collections.defaultdict(dict)
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
        m=re.fullmatch(r'(x(?:_|ǁ).+)__mutmut_(orig|\d+)',n.name)
        if not m:continue
        fam,num=m.groups();name=fam.split('ǁ')[-1] if 'ǁ' in fam else fam[2:];body=lines[n.lineno-1:n.end_lineno].copy();body[0]=body[0].replace('def '+n.name+'(', 'def '+name+'(',1);gen[fam][num]=body
    return gen

def _diff_catalog(
    g: dict[str, list[str]], old: list[str]
) -> dict[str, list[object]]:
    """Derive the minimal line hunk distinguishing each variant from orig."""
    d: dict[str, list[object]]={}
    for num,body in g.items():
        if num=="orig":
            continue
        left=0;right=0
        while left<min(len(body),len(old)) and body[left]==old[left]:left+=1
        while right<min(len(body),len(old))-left and body[-1-right]==old[-1-right]:right+=1
        if left==len(body)==len(old):continue
        d[num]=[left,len(old)-right,body[left:len(body)-right]]
    return d

def extract(root):
    families={}
    for meta in sorted(root.rglob('*.py.meta')):
        f=meta.with_suffix('');src=f.read_text();module=str(f.relative_to(root)).removesuffix('.py').replace('/','.')
        lines=src.splitlines(keepends=True);gen=_mutant_bodies(f,lines)
        for fam,g in gen.items():
            if 'orig' not in g:continue
            old=g['orig'];families['monori.'+module+'.'+fam]={
                'file':str(f.relative_to(root)),'old':old,'diffs':_diff_catalog(g,old)}
    return families
if __name__=='__main__':
    root=next(pathlib.Path.home().glob('.openhands/agent-canvas/workspaces/75ad*/repo/mutants'));b=json.dumps(extract(root),separators=(',',':')).encode();sys.stdout.buffer.write(gzip.compress(b,mtime=0))
