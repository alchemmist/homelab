"""Explicitly reviewed stdin contracts; source strings are fault probes, not solutions."""
SPECS = {
'conditionals/echo-2': ('repeat4', 'Hi\n', 'HiHiHiHi\n', [
 ('three repeats','print(input()*3)'), ('spaces',"s=input();print(s,s,s,s)"),('strip',"print(input().strip()*4)")]),
'conditionals/only-python': ('python_exact','Python\n','ДА\n',[
 ('case insensitive',"print('ДА' if input().lower()=='python' else 'НЕТ')"),
 ('substring',"print('ДА' if 'Python' in input() else 'НЕТ')"),
 ('strip',"print('ДА' if input().strip()=='Python' else 'НЕТ')")]),
'conditionals/zen': ('zen','\n','ДА\n',[
 ('strip',"print('ДА' if input().strip()=='' else 'НЕТ')"),
 ('inverted',"print('НЕТ' if input()=='' else 'ДА')"),('always no',"input();print('НЕТ')")]),
'conditionals/meow': ('meow','кот\n','МЯУ\n',[
 ('whole word',"print('МЯУ' if input()=='кот' else 'ГАВ')"),
 ('case insensitive',"print('МЯУ' if 'кот' in input().lower() else 'ГАВ')"),
 ('always meow',"input();print('МЯУ')")]),
'conditionals/yes-or-no': ('yes_no','да\nнет\n','ВЕРНО\n',[
 ('either valid',"a=input();b=input();print('ВЕРНО' if a in ('да','нет') or b in ('да','нет') else 'НЕВЕРНО')"),
 ('only equal',"a=input();b=input();print('ВЕРНО' if a==b and a in ('да','нет') else 'НЕВЕРНО')"),
 ('ignore case',"a=input().lower();b=input().lower();print('ВЕРНО' if a in ('да','нет') and b in ('да','нет') else 'НЕВЕРНО')")]),
'conditionals/xmas-tree': ('xmas','раз\nдва\nтри\n','ГОРИ\n',[
 ('allow digits',"a=input();b=input();c=input();print('ГОРИ' if [a,b,c] in [['раз','два','три'],['1','2','3']] else 'НЕ ГОРИ')"),
 ('first only',"a=input();input();input();print('ГОРИ' if a=='раз' else 'НЕ ГОРИ')"),
 ('unordered',"a=input();b=input();c=input();print('ГОРИ' if sorted([a,b,c])==sorted(['раз','два','три']) else 'НЕ ГОРИ')")]),
'environment-intro/parrot': ('parrot','a\nb\nc\n','a\nb\nc\n',[
 ('reverse',"a=input();b=input();c=input();print(c,b,a,sep='\\n')"),
 ('strip',"a=input().strip();b=input().strip();c=input().strip();print(a,b,c,sep='\\n')"),
 ('omit third',"a=input();b=input();input();print(a,b,sep='\\n')")]),
'environment-intro/reverse-parrot': ('reverse','a\nb\nc\n','c\nb\na\n',[
 ('forward',"a=input();b=input();c=input();print(a,b,c,sep='\\n')"),
 ('strip',"a=input().strip();b=input().strip();c=input().strip();print(c,b,a,sep='\\n')"),
 ('omit middle',"a=input();input();c=input();print(c,a,sep='\\n')")]),
'while-intro/recall-if': ('temperature','20\n','НОРМАЛЬНО\n',[
 ('lower inclusive',"n=float(input());print('ХОЛОДНО' if n<=15.5 else 'ЖАРКО' if n>28 else 'НОРМАЛЬНО')"),
 ('upper inclusive',"n=float(input());print('ХОЛОДНО' if n<15.5 else 'ЖАРКО' if n>=28 else 'НОРМАЛЬНО')"),
 ('integer truncation',"n=int(float(input()));print('ХОЛОДНО' if n<15.5 else 'ЖАРКО' if n>28 else 'НОРМАЛЬНО')")]),
'builtin-functions/sort-heights': ('heights','150\n170\n160\n','170\n160\n150\n',[
 ('ascending',"a=int(input());b=int(input());c=int(input());print(*sorted([a,b,c]),sep='\\n')"),
 ('deduplicate',"a=int(input());b=int(input());c=int(input());print(*sorted(set([a,b,c]),reverse=True),sep='\\n')"),
 ('lexicographic',"a=input();b=input();c=input();print(*sorted([a,b,c],reverse=True),sep='\\n')")]),
}
ORACLE_JS = r'''
 const single = lines.length===1 && !input.includes('\r');
 if (['repeat4','python_exact','zen','meow'].includes(data.contract)) {
  if (!single) return null;
  const x=lines[0];
  if(data.contract==='repeat4')return x.repeat(4)+'\n';
  if(data.contract==='python_exact')return (x==='Python'?'ДА':'НЕТ')+'\n';
  if(data.contract==='zen')return (x===''?'ДА':'НЕТ')+'\n';
  return (x.includes('кот')?'МЯУ':'ГАВ')+'\n';
 }
 if(data.contract==='yes_no') {
  if(lines.length!==2 || input.includes('\r')) return null;
  return (lines.every(x=>['да','нет'].includes(x))?'ВЕРНО':'НЕВЕРНО')+'\n';
 }
 if(['xmas','parrot','reverse'].includes(data.contract)) {
  if(lines.length!==3 || input.includes('\r'))return null;
  if(data.contract==='xmas')return (JSON.stringify(lines)===JSON.stringify(['раз','два','три'])?'ГОРИ':'НЕ ГОРИ')+'\n';
  return (data.contract==='reverse'?[...lines].reverse():lines).join('\n')+'\n';
 }
 if(data.contract==='temperature') {
  if(!single || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(lines[0]))return null;
  const n=Number(lines[0]); if(!Number.isFinite(n))return null;
  return (n<15.5?'ХОЛОДНО':n>28?'ЖАРКО':'НОРМАЛЬНО')+'\n';
 }
 if(data.contract==='heights') {
  if(lines.length!==3 || !lines.every(x=>/^[1-9]\d{0,3}$/.test(x)))return null;
  return lines.map(Number).sort((a,b)=>b-a).join('\n')+'\n';
 }
'''

# Three reviewed loop contracts. Data after the sentinel must not be printed.
for slug, contract, stop, wrong_stop, alternate in [
 ('numbers-to-zero','until_zero','int(s)==0','int(s)<=0','int(s)==1'),
 ('round-numbers','until_nonmultiple','int(s)%10!=0','int(s)%10!=0 or int(s)==0','int(s)%2!=0'),
 ('strings-to-empty','until_empty',"s==''","s.strip()==''","len(s)<=1"),
]:
 def probe(condition, inclusive=False):
  return 'import sys\nfor line in sys.stdin:\n s=line.rstrip("\\n")\n if '+condition+':\n  '+('print(s); ' if inclusive else '')+'break\n print(s)'
 SPECS['while-intro/'+slug]=(contract,'','',[
  ('include terminator',probe(stop,True)),('wrong stopping condition',probe(wrong_stop)),('alternate terminator',probe(alternate))])
ORACLE_JS += r'''
 if(['until_zero','until_nonmultiple','until_empty'].includes(data.contract)) {
  if(!lines.length || input.includes('\r'))return null;
  const prefix=[];
  for(const s of lines){
   if(data.contract!=='until_empty' && !/^(?:0|-?[1-9]\d{0,8})$/.test(s))return null;
   if(data.contract==='until_empty'?s==='':data.contract==='until_zero'?Number(s)===0:Number(s)%10!==0)
    return prefix.map(x=>x+'\n').join('');
   prefix.push(s);
  }
  return null;
 }
'''

for version in (2,3):
 contract=f'xmas{version}'
 valid=[['раз','два','три'],['1','2','3']]+([['один','два','три']] if version==3 else [])
 def probe(expr):return "a=[input() for _ in range(3)];print('ГОРИ' if "+expr+" else 'НЕ ГОРИ')"
 SPECS[f'conditionals/xmas-tree-{version}']=(contract,'','',[
 ('accept mixed encodings',probe("all(any(x==v[i] for v in "+repr(valid)+") for i,x in enumerate(a))")),
 ('ignore order',probe('any(sorted(a)==sorted(v) for v in '+repr(valid)+')')),
 ('strip significant spaces',probe('[x.strip() for x in a] in '+repr(valid)))])
ORACLE_JS += r'''
 if(data.contract==='xmas2'||data.contract==='xmas3') {
  if(lines.length!==3 || input.includes('\r'))return null;
  const seq=lines.join('\n');
  return (seq==='раз\nдва\nтри'||seq==='1\n2\n3'||(data.contract==='xmas3'&&seq==='один\nдва\nтри')?'ГОРИ':'НЕ ГОРИ')+'\n';
 }
'''
