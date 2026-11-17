import copy
import html
import json
import random
import secrets
import shlex

FIXTURES = {
    'median': {
        'source': 'exports.solve = values => { const a=values.sort(); return a[Math.floor(a.length/2)]; };\n',
        'contract': 'Return the numeric median of an array: numerically sort a copy, use the middle value for odd lengths, average both middle values for even lengths, throw RangeError for empty input. Never mutate caller input.',
        'visible': [([1, 2, 3],)],
    },
    'clamp': {
        'source': 'exports.solve = (value, low, high) => Math.max(low || value, Math.min(high || value, value));\n',
        'contract': 'Clamp a finite number value into inclusive finite numeric bounds low and high. Zero bounds are valid. Throw RangeError when low exceeds high. Never mutate caller input.',
        'visible': [(5, 1, 10)],
    },
    'escape_html': {
        'source': '''exports.solve = text => text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/&/g, '&amp;');\n''',
        'contract': 'Escape raw text for HTML: replace & with &amp;, < with &lt;, > with &gt;, double quote with &quot;, and single quote with &#39;. Escape exactly once per input character, including ampersands already part of text such as &lt;. Preserve all other characters and do not mutate input.',
        'visible': [('hello',)],
    },
}


def expected(task, args):
    if task == 'median':
        values = sorted(args[0])
        if not values:
            return {'error': 'RangeError'}
        n = len(values)
        value = values[n//2] if n % 2 else (values[n//2-1] + values[n//2])/2
    elif task == 'clamp':
        value, low, high = args
        if low > high:
            return {'error': 'RangeError'}
        value = max(low, min(high, value))
    else:
        value = html.escape(args[0], quote=True).replace('&#x27;', '&#39;')
    return {'value': value}


def fixture_files(task):
    definition = FIXTURES[task]
    tests = "const a=require('node:assert/strict');const {solve}=require('./lib.cjs');\n"
    for args in definition['visible']:
        tests += 'a.deepEqual(solve(...' + json.dumps(args) + '),' + json.dumps(expected(task, args)['value']) + ');\n'
    tests += "console.log('visible tests passed');\n"
    return {'lib.cjs': definition['source'], 'test.cjs': tests}


def task_prompt(task):
    return ('Find and fix bugs in lib.cjs, exported function solve. Contract: ' + FIXTURES[task]['contract'] +
            ' Work at /workspace. Edit only lib.cjs; never change test.cjs or leave extra files. '
            'Do not add comments. Node and bash are installed. No installations, network, git, credentials, host access or user input. '
            'Inspect actual files, execute a failing reproduction, implement a minimal fix, run actual tests. '
            'Do not invent files or test results. Use inline node -e for extra tests. '
            'When complete use your agent completion mechanism; for mini-SWE-agent execute '
            'echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT as a standalone command.')


def cases_for(task, seed):
    rng = random.Random(seed)
    if task == 'median':
        cases = [[[]], [[1]], [[10, 2, 1]], [[1, 2]], [[-1, -4, -2, -3]]]
        cases += [[[rng.randint(-1000, 1000) for _ in range(rng.randint(1, 16))]] for _ in range(60)]
    elif task == 'clamp':
        cases = [[-1, 0, 3], [5, -3, 0], [1, 2, -2], [0, 0, 0]]
        cases += [[rng.randint(-100, 100), rng.randint(-100, 100), rng.randint(-100, 100)] for _ in range(60)]
    else:
        cases = [[''], ['<a title="x">&\'</a>'], ['&lt;'], ['plain text'], ['<&>']]
        alphabet = 'abc xyz<&>\'"é\n'
        cases += [[''.join(rng.choice(alphabet) for _ in range(rng.randint(1, 60)))] for _ in range(60)]
    return copy.deepcopy(cases)


def verifier_command(task, seed):
    cases = cases_for(task, seed)
    nonce = secrets.token_hex(16)
    script = ('const cases=' + json.dumps(cases) + ';const nonce=' + json.dumps(nonce) + ';'
              'const {solve}=require("./lib.cjs");'
              'const results=cases.map(args=>{const before=JSON.stringify(args);let r;'
              'try{r={value:solve(...args)}}catch(e){r={error:e.name}}'
              'r.mutated=JSON.stringify(args)!==before;return r});'
              'console.log(JSON.stringify({nonce,results}));')
    return 'node -e ' + shlex.quote(script), nonce, cases


def check_verdict(task, nonce, cases, result):
    if result['returncode'] != 0:
        return {'accepted': False, 'reason': 'verifier process failed', 'exit_code': result['returncode']}
    try:
        data = json.loads(result['output'])
    except (ValueError, TypeError):
        return {'accepted': False, 'reason': 'missing or invalid verifier output'}
    if (not isinstance(data, dict) or data.get('nonce') != nonce or
            not isinstance(data.get('results'), list) or len(data['results']) != len(cases)):
        return {'accepted': False, 'reason': 'incomplete verifier output'}
    for index, (args, actual) in enumerate(zip(cases, data['results'])):
        want = expected(task, args) | {'mutated': False}
        if actual != want or (isinstance(actual, dict) and isinstance(actual.get('value'), bool)):
            return {'accepted': False, 'reason': 'contract mismatch', 'case': index,
                    'arguments': args, 'expected': want, 'actual': actual}
    return {'accepted': True, 'cases': len(cases)}
