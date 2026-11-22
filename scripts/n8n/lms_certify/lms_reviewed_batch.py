"""Explicitly reviewed stdin contracts; source strings are fault probes, not solutions."""

SPECS = {
    "conditionals/echo-2": (
        "repeat4",
        "Hi\n",
        "HiHiHiHi\n",
        [
            ("three repeats", "print(input()*3)"),
            ("spaces", "s=input();print(s,s,s,s)"),
            ("strip", "print(input().strip()*4)"),
        ],
    ),
    "conditionals/only-python": (
        "python_exact",
        "Python\n",
        "ДА\n",
        [
            ("case insensitive", "print('ДА' if input().lower()=='python' else 'НЕТ')"),
            ("substring", "print('ДА' if 'Python' in input() else 'НЕТ')"),
            ("strip", "print('ДА' if input().strip()=='Python' else 'НЕТ')"),
        ],
    ),
    "conditionals/zen": (
        "zen",
        "\n",
        "ДА\n",
        [
            ("strip", "print('ДА' if input().strip()=='' else 'НЕТ')"),
            ("inverted", "print('НЕТ' if input()=='' else 'ДА')"),
            ("always no", "input();print('НЕТ')"),
        ],
    ),
    "conditionals/meow": (
        "meow",
        "кот\n",
        "МЯУ\n",
        [
            ("whole word", "print('МЯУ' if input()=='кот' else 'ГАВ')"),
            ("case insensitive", "print('МЯУ' if 'кот' in input().lower() else 'ГАВ')"),
            ("always meow", "input();print('МЯУ')"),
        ],
    ),
    "conditionals/yes-or-no": (
        "yes_no",
        "да\nнет\n",
        "ВЕРНО\n",
        [
            (
                "either valid",
                "a=input();b=input();print('ВЕРНО' if a in ('да','нет') or b in ('да','нет') else 'НЕВЕРНО')",
            ),
            (
                "only equal",
                "a=input();b=input();print('ВЕРНО' if a==b and a in ('да','нет') else 'НЕВЕРНО')",
            ),
            (
                "ignore case",
                "a=input().lower();b=input().lower();print('ВЕРНО' if a in ('да','нет') and b in ('да','нет') else 'НЕВЕРНО')",
            ),
        ],
    ),
    "conditionals/xmas-tree": (
        "xmas",
        "раз\nдва\nтри\n",
        "ГОРИ\n",
        [
            (
                "allow digits",
                "a=input();b=input();c=input();print('ГОРИ' if [a,b,c] in [['раз','два','три'],['1','2','3']] else 'НЕ ГОРИ')",
            ),
            (
                "first only",
                "a=input();input();input();print('ГОРИ' if a=='раз' else 'НЕ ГОРИ')",
            ),
            (
                "unordered",
                "a=input();b=input();c=input();print('ГОРИ' if sorted([a,b,c])==sorted(['раз','два','три']) else 'НЕ ГОРИ')",
            ),
        ],
    ),
    "environment-intro/parrot": (
        "parrot",
        "a\nb\nc\n",
        "a\nb\nc\n",
        [
            ("reverse", "a=input();b=input();c=input();print(c,b,a,sep='\\n')"),
            (
                "strip",
                "a=input().strip();b=input().strip();c=input().strip();print(a,b,c,sep='\\n')",
            ),
            ("omit third", "a=input();b=input();input();print(a,b,sep='\\n')"),
        ],
    ),
    "environment-intro/reverse-parrot": (
        "reverse",
        "a\nb\nc\n",
        "c\nb\na\n",
        [
            ("forward", "a=input();b=input();c=input();print(a,b,c,sep='\\n')"),
            (
                "strip",
                "a=input().strip();b=input().strip();c=input().strip();print(c,b,a,sep='\\n')",
            ),
            ("omit middle", "a=input();input();c=input();print(c,a,sep='\\n')"),
        ],
    ),
    "while-intro/recall-if": (
        "temperature",
        "20\n",
        "НОРМАЛЬНО\n",
        [
            (
                "lower inclusive",
                "n=float(input());print('ХОЛОДНО' if n<=15.5 else 'ЖАРКО' if n>28 else 'НОРМАЛЬНО')",
            ),
            (
                "upper inclusive",
                "n=float(input());print('ХОЛОДНО' if n<15.5 else 'ЖАРКО' if n>=28 else 'НОРМАЛЬНО')",
            ),
            (
                "integer truncation",
                "n=int(float(input()));print('ХОЛОДНО' if n<15.5 else 'ЖАРКО' if n>28 else 'НОРМАЛЬНО')",
            ),
        ],
    ),
    "builtin-functions/sort-heights": (
        "heights",
        "150\n170\n160\n",
        "170\n160\n150\n",
        [
            (
                "ascending",
                "a=int(input());b=int(input());c=int(input());print(*sorted([a,b,c]),sep='\\n')",
            ),
            (
                "deduplicate",
                "a=int(input());b=int(input());c=int(input());print(*sorted(set([a,b,c]),reverse=True),sep='\\n')",
            ),
            (
                "lexicographic",
                "a=input();b=input();c=input();print(*sorted([a,b,c],reverse=True),sep='\\n')",
            ),
        ],
    ),
}
ORACLE_JS = r"""
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
"""

# Three reviewed loop contracts. Data after the sentinel must not be printed.
for slug, contract, stop, wrong_stop, alternate in [
    ("numbers-to-zero", "until_zero", "int(s)==0", "int(s)<=0", "int(s)==1"),
    (
        "round-numbers",
        "until_nonmultiple",
        "int(s)%10!=0",
        "int(s)%10!=0 or int(s)==0",
        "int(s)%2!=0",
    ),
    ("strings-to-empty", "until_empty", "s==''", "s.strip()==''", "len(s)<=1"),
]:

    def probe(condition: str, *, inclusive: bool = False) -> str:
        return (
            'import sys\nfor line in sys.stdin:\n s=line.rstrip("\\n")\n if '
            + condition
            + ":\n  "
            + ("print(s); " if inclusive else "")
            + "break\n print(s)"
        )

    SPECS["while-intro/" + slug] = (
        contract,
        "",
        "",
        [
            ("include terminator", probe(stop, inclusive=True)),
            ("wrong stopping condition", probe(wrong_stop)),
            ("alternate terminator", probe(alternate)),
        ],
    )
ORACLE_JS += r"""
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
"""

for version in (2, 3):
    contract = f"xmas{version}"
    valid = [["раз", "два", "три"], ["1", "2", "3"]] + (
        [["один", "два", "три"]] if version == 3 else []
    )

    def probe_expr(expr: str) -> str:
        return "a=[input() for _ in range(3)];print('ГОРИ' if " + expr + " else 'НЕ ГОРИ')"

    SPECS[f"conditionals/xmas-tree-{version}"] = (
        contract,
        "",
        "",
        [
            (
                "accept mixed encodings",
                probe_expr(
                    "all(any(x==v[i] for v in " + repr(valid) + ") for i,x in enumerate(a))"
                ),
            ),
            (
                "ignore order",
                probe_expr("any(sorted(a)==sorted(v) for v in " + repr(valid) + ")"),
            ),
            (
                "strip significant spaces",
                probe_expr("[x.strip() for x in a] in " + repr(valid)),
            ),
        ],
    )
ORACLE_JS += r"""
 if(data.contract==='xmas2'||data.contract==='xmas3') {
  if(lines.length!==3 || input.includes('\r'))return null;
  const seq=lines.join('\n');
  return (seq==='раз\nдва\nтри'||seq==='1\n2\n3'||(data.contract==='xmas3'&&seq==='один\nдва\nтри')?'ГОРИ':'НЕ ГОРИ')+'\n';
 }
"""

_fb_value = "'FizzBuzz' if i%15==0 else 'Fizz' if i%3==0 else 'Buzz' if i%5==0 else i"


def _fb_loop(bounds: str, value: str) -> str:
    program: str = (
        "a=int(input()); b=int(input())\nfor i in range(" + bounds + "):\n print(" + value + ")"
    )
    return program


SPECS["break-continue/fizzbuzz"] = (
    "fizzbuzz",
    "",
    "",
    [
        ("skip right endpoint", _fb_loop("a,b", _fb_value)),
        (
            "miss common multiple",
            _fb_loop("a,b+1", "'Fizz' if i%3==0 else 'Buzz' if i%5==0 else i"),
        ),
        (
            "omit plain numbers",
            _fb_loop("a,b+1", _fb_value).replace(" print(", " if i%3==0 or i%5==0: print("),
        ),
    ],
)
ORACLE_JS += r"""
 if(data.contract==='fizzbuzz') {
  if(lines.length!==2 || !lines.every(x=>/^[1-9]\d{0,5}$/.test(x)))return null;
  const [a,b]=lines.map(Number); if(a>=b || b-a>50)return null;
  const result=[]; for(let i=a;i<=b;i++)result.push((i%3===0?'Fizz':'')+(i%5===0?'Buzz':'')||String(i));
  return result.join('\n')+'\n';
 }
"""


def count_probe(initial, condition) -> str:
    return f"n={initial}\nwhile True:\n s=input(); n+=1\n if {condition}: break\nprint(n)"


SPECS["while-intro/count-lines"] = (
    "thank_count",
    "",
    "",
    [
        ("exclude final line", count_probe(-1, "s=='Спасибо.'")),
        ("ignore case", count_probe(0, "s.lower()=='спасибо.'")),
        ("ignore spaces", count_probe(0, "s.strip()=='Спасибо.'")),
    ],
)


def table_probe(i, j, value) -> str:
    return f'n=int(input())\nfor i in {i}:\n for j in {j}:\n  print(f"{{i}} * {{j}} = {{{value}}}")'


SPECS["nested-loops/table-as-list"] = (
    "mult_table",
    "",
    "",
    [
        ("omit last row", table_probe("range(1,n)", "range(1,n+1)", "i*j")),
        ("upper triangle only", table_probe("range(1,n+1)", "range(i,n+1)", "i*j")),
        ("add instead of multiply", table_probe("range(1,n+1)", "range(1,n+1)", "i+j")),
    ],
)
ORACLE_JS += r"""
 if(data.contract==='thank_count') {
  if(!input.endsWith('\n') || input.includes('\r'))return null;
  const idx=lines.indexOf('Спасибо.'); return idx<0?null:String(idx+1)+'\n';
 }
 if(data.contract==='mult_table') {
  if(lines.length!==1 || !/^[1-6]$/.test(lines[0]))return null;
  const n=Number(lines[0]), rows=[];
  for(let i=1;i<=n;i++)for(let j=1;j<=n;j++)rows.push(`${i} * ${j} = ${i*j}`);
  return rows.join('\n')+'\n';
 }
"""

_digits = "a,b,c=map(int,input()); "
_yes = "'Вы ввели красивое число'"
_no = "'Жаль, вы ввели обычное число'"
SPECS["builtin-functions/beautiful-number"] = (
    "beautiful_digits",
    "",
    "",
    [
        (
            "assume middle digit is median",
            _digits + f"print({_yes} if a+c==2*b else {_no})",
        ),
        (
            "round the mean down",
            _digits + f"x,y,z=sorted((a,b,c)); print({_yes} if (x+z)//2==y else {_no})",
        ),
        (
            "exclude equal digits",
            _digits + f"x,y,z=sorted((a,b,c)); print({_yes} if x<z and x+z==2*y else {_no})",
        ),
    ],
)
SPECS["builtin-functions/assemble-number"] = (
    "adjacent_sums",
    "",
    "",
    [
        ("keep input order", _digits + "print(str(a+b)+str(b+c))"),
        (
            "sort sums as text",
            _digits + "print(''.join(sorted([str(a+b),str(b+c)],reverse=True)))",
        ),
        ("add instead of concatenating", _digits + "print(a+b+b+c)"),
    ],
)
ORACLE_JS += r"""
 if(data.contract==='beautiful_digits'||data.contract==='adjacent_sums') {
  if(lines.length!==1||!/^[1-9][0-9]{2}$/.test(lines[0]))return null;
  const [a,b,c]=Array.from(lines[0],Number);
  if(data.contract==='adjacent_sums')return [a+b,b+c].sort((x,y)=>y-x).join('')+'\n';
  const lo=Math.min(a,b,c),hi=Math.max(a,b,c),mid=a+b+c-lo-hi;
  return (2*mid===hi+lo?'Вы ввели красивое число':'Жаль, вы ввели обычное число')+'\n';
 }
"""

# A no-input exercise has a singleton input domain. Three invented stdin
# cases cannot add coverage; compare the entire output, then run fault probes.
NOINPUT = {
    "environment-intro/hello-world": (
        "Привет, Мир!",
        ["Привет Мир!", "Привет, мир!", "Привет, Мир"],
    ),
    "environment-intro/nice-to-meet": (
        "Привет, Мир!\nПриятно познакомиться.",
        [
            "Привет, Мир!",
            "Привет, Мир! Приятно познакомиться.",
            "Приятно познакомиться.\nПривет, Мир!",
        ],
    ),
    "environment-intro/greeting-report": (
        'Моя первая программа напечатала "Привет, Яндекс!" :)',
        [
            "Привет, Яндекс!",
            "Моя первая программа напечатала Привет, Яндекс! :)",
            'Моя первая программа напечатала "Привет, Яндекс!"',
        ],
    ),
    "builtin-functions/factorial-intro": (
        str(1 * 2 * 3 * 4 * 5 * 6 * 7 * 8 * 9),
        ["40320", "3628800", "45"],
    ),
    "builtin-functions/diggers": (
        str((1400 + 2 * 3 - 1) // (2 * 3)),
        ["233", "467", "700"],
    ),
}
for key, (answer, wrong) in NOINPUT.items():
    SPECS[key] = (
        "noinput_reviewed",
        "",
        answer + "\n",
        [(f"wrong answer {i}", f"print({text!r})") for i, text in enumerate(wrong, 1)],
    )
ORACLE_JS += (
    "\n if(data.contract==='noinput_reviewed')return input===''?data.reviewedOutput:null;\n"
)
