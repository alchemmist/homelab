#!/usr/bin/env python3
"""Build the importable pilot workflow. Does not activate or deploy anything."""
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2] / 'docs/n8n/lms-certify'
PROM = 'http://kube-prometheus-stack-prometheus.cattle-monitoring-system.svc.cluster.local:9090/api/v1/query'
MODEL = 'qwen3.8-27b'
RUNNER = 'http://REPLACE_RUNNER:9000/certification/check-suite'
LLM = 'http://litellm.llm.svc.cluster.local:4000/v1/chat/completions'
nodes, edges = [], {}


def node(name, kind, version, params, x, y, credential=None):
    out = dict(id=str(uuid5(NAMESPACE_URL, 'lms-certification/' + name)), name=name,
               type='n8n-nodes-base.' + kind, typeVersion=version, position=[x, y], parameters=params)
    if credential:
        typ, role = credential
        out['credentials'] = {typ: {'id': 'REPLACE_' + role, 'name': role}}
    nodes.append(out)
    return name


def link(a, b, port=0):
    branches = edges.setdefault(a, {'main': []})['main']
    while len(branches) <= port:
        branches.append([])
    branches[port].append(dict(node=b, type='main', index=0))


def chain(*names):
    for a, b in zip(names, names[1:]):
        link(a, b)


def code(name, js, x, y):
    return node(name, 'code', 2, {'jsCode': js}, x, y)


def check(name, expr, x, y):
    return node(name, 'if', 2.2, {'conditions': {'options': {'version': 2, 'typeValidation': 'strict'},
                'conditions': [{'id': 'yes', 'leftValue': '={{ ' + expr + ' }}', 'rightValue': '',
                                'operator': {'type': 'boolean', 'operation': 'true', 'singleValue': True}}],
                'combinator': 'and'}}, x, y)


def http(name, url, x, y, *, body=None, role=None, query=None):
    params = {'url': url, 'options': {'timeout': 90000 if body else 8000,
              'response': {'response': {'fullResponse': True, 'neverError': True, 'responseFormat': 'json'}}}}
    credential = None
    if body:
        params.update(method='POST', sendBody=True, specifyBody='json', jsonBody='={{ JSON.stringify(' + body + ') }}',
                      authentication='genericCredentialType', genericAuthType='httpHeaderAuth')
        credential = ('httpHeaderAuth', role)
    if query:
        params.update(sendQuery=True, queryParameters={'parameters': [{'name': 'query', 'value': query}]})
    return node(name, 'httpRequest', 4.2, params, x, y, credential)


def pg(name, sql, args, x, y):
    return node(name, 'postgres', 2.6, {'operation': 'executeQuery', 'query': sql,
                'options': {'queryReplacement': '={{ ' + args + ' }}'}}, x, y, ('postgres', 'CERTIFICATION_DB'))


def idle(prefix, x, y):
    # Timestamp the original samples, not the Prometheus query evaluation.
    selector = '{__name__=~"vllm:num_requests_(running|waiting)",model_name="' + MODEL + '"}'
    values = http(prefix + ' queue depth', PROM, x, y, query=selector)
    stamps = http(prefix + ' sample freshness', PROM, x + 220, y,
                  query=' or '.join('label_replace(timestamp(vllm:num_requests_' + metric +
                      '{model_name="' + MODEL + '"}), "queue_metric", "' + metric + '", "model_name", ".*")'
                      for metric in ('running', 'waiting')))
    valid = code(prefix + ' verify both metrics', f'''const values = $({json.dumps(values)}).item.json;
const stamps = $json;
function rows(r) {{ return r.statusCode === 200 && r.body?.status === 'success' &&
  Array.isArray(r.body?.data?.result) ? r.body.data.result : []; }}
const expected = ['vllm:num_requests_running','vllm:num_requests_waiting'];
const v = rows(values), t = rows(stamps), now = Date.now()/1000;
const key = (r, metric) => JSON.stringify([metric, Object.entries(r.metric || {{}})
  .filter(([k]) => !['__name__','queue_metric'].includes(k)).sort(([a],[b]) => a.localeCompare(b))]);
const fresh = new Set(t.filter(r => {{const age = now - Number(r.value?.[1]); return age >= -5 && age <= 45;}})
  .map(r => key(r, r.metric.queue_metric)));
return {{json: {{idle: expected.every(n => v.some(r => r.metric.__name__ === n)) &&
  t.length === v.length && v.every(r => r.value?.[1] === '0' &&
    fresh.has(key(r, r.metric.__name__.split('_').at(-1))))}}}};''', x+440, y)
    gate = check(prefix + ' model idle?', '$json.idle === true', x+660, y)
    chain(values, stamps, valid, gate)
    return values, gate


start = node('Every minute', 'scheduleTrigger', 1.2, {'rule': {'interval': [{'field': 'minutes', 'minutesInterval': 1}]}}, 0, 0)
entry, gate = idle('Admission:', 220, 0)
claim = pg('Claim pilot and load checkpoint', '''UPDATE lms_certification.pilot
SET owner = $1, lease_until = clock_timestamp() + interval '15 minutes'
WHERE id = 'echo-0-v1' AND phase NOT IN ('certified','needs_review')
AND (lease_until IS NULL OR lease_until < clock_timestamp())
RETURNING phase, data''', '[$execution.id]', 1100, 0)
chain(start, entry)
link(gate, claim)
checkpoint = pg('Checkpoint and dispatch next phase', '''UPDATE lms_certification.pilot
SET phase = $2, data = $3::jsonb, updated_at = clock_timestamp(),
lease_until = CASE WHEN $2 IN ('certified','needs_review') THEN NULL ELSE clock_timestamp() + interval '15 minutes' END
WHERE id = 'echo-0-v1' AND owner = $1 AND lease_until > clock_timestamp()
RETURNING phase, data''', '[$execution.id, $json.phase, JSON.stringify($json.data)]', 1480, -380)
release = pg('Pause and release lease', '''UPDATE lms_certification.pilot SET lease_until = NULL
WHERE id = 'echo-0-v1' AND owner = $1 RETURNING phase''', '[$execution.id]', 1140, -580)
terminal = code('Private outcome recorded', 'return {json: {status: $json.phase}};', 4900, -380)

statement = 'Напишите программу, которая считывает слово (или фразу, неважно) и тут же выводит её, и больше ничего не делает. Особое условие: одна строка, не более 14 символов.'
examples = [{'input': 'Привет, мир!\n', 'output': 'Привет, мир!\n'}]
faults = [
    ('empty program', 'pass'), ('strip whitespace', 'print(input().strip())'),
    ('truncate at first word', 'print(input().split(" ")[0])'),
    ('lowercase', 'print(input().lower())'), ('lose leading characters', 'print(input()[1:])'),
]


def ref(name):
    return '$(' + json.dumps(name) + ').item.json'


def reducer(name, route, js, x, y):
    n = code(name, f'''const {{phase,data}} = {ref(route)};
const status = $json.statusCode;
if (status === 429 || status >= 500) return {{json: {{pause:true}}}};
if (status !== 200) throw new Error('Unexpected service HTTP status: ' + status);
{js}''', x, y)
    ok = check(name + ' checkpoint?', '$json.pause !== true', x+220, y)
    chain(n, ok, checkpoint)
    link(ok, release, 1)
    return n


phase_specs = [('solve','Generate solution'), ('tests','Author blind tests'), ('public','Run public examples'),
               ('repair','Repair solution'), ('suite','Run verified private tests'), ('mutate','Run one fault variant'),
               ('expand','Add missing corner cases')]
previous = None
for i, (phase, title) in enumerate(phase_specs):
    y = i * 300 + 120
    route = check('Phase: ' + phase, '$json.phase === ' + json.dumps(phase), 1490+i*240, y)
    if previous:
        link(previous, route, 1)
    else:
        link(claim, route)
        link(checkpoint, route)
    previous = route
    r = ref(route)
    x = 1770+i*240
    if phase in {'solve','tests','repair','expand'}:
        first, free = idle(title + ':', x, y)
        link(route, first)
        link(free, release, 1)
        test_prompt = ('Придумай корректные закрытые тесты по условию. JSON {"cases":[{"input":"строка\\n","output":"строка\\n"}]}. '
                       'Добавь случаи с пробелами по краям, несколько слов, смешанный регистр и пустую строку. Условие: ' + statement)
        if phase in {'tests','expand'}:
            prompt = json.dumps(test_prompt, ensure_ascii=False)
            if phase == 'expand':
                prompt += f''' + '\\nУже проверенные входы: ' + JSON.stringify({r}.data.cases.map(c => c.input)) + '\\nЧто не поймано: ' + JSON.stringify({r}.data.survivors)'''
        else:
            prompt = json.dumps('Верни решение на Python 3 в формате JSON {"source":"..."}. Условие: ' + statement, ensure_ascii=False)
            if phase == 'repair':
                prompt += f''' + '\\nПредыдущее решение: ' + JSON.stringify({r}.data.source) + '\\nПроваленный проверенный тест: ' + JSON.stringify({r}.data.failure)'''
        req = http('LLM: ' + title, LLM, x+880, y, role='LITELLM', body=
                   f'''{{model:{json.dumps(MODEL)}, temperature:0, max_tokens:1000, response_format:{{type:'json_object'}}, messages:[{{role:'user', content: {prompt}}}]}}''')
        parse = '''let payload;
try { payload = JSON.parse($json.body.choices[0].message.content); } catch { payload = {}; }
 data.calls = (data.calls || 0) + 1;
 const out = next => ({json:{phase:data.calls >= 12 && ['solve','repair','tests','expand'].includes(next) ? 'needs_review' : next,data}});
'''
        if phase in {'solve','repair'}:
            logic = '''const source = typeof payload?.source === 'string' ? payload.source.trim() : '';
if (!source || /[\\r\\n]/.test(source) || [...source].length > 14) return out(phase);
data.source = source;
return out(phase === 'solve' ? 'tests' : 'public');'''
            label = 'Validate solution format' if phase == 'solve' else 'Validate repaired solution format'
        else:
            logic = '''// Independently verify the echo task's expected output; never consult the candidate.
const cases = data.cases || [];
const seen = new Set(cases.map(c => c.input));
for (const c of (Array.isArray(payload?.cases) ? payload.cases.slice(0, 16) : [])) {
  if (typeof c?.input !== 'string' || c.input.length > 256 || !/^[^\\r\\n]*\\n$/.test(c.input) ||
      c.output !== c.input || seen.has(c.input) || c.input === 'Привет, мир!\\n' || cases.length >= 12) continue;
  cases.push({input:c.input,output:c.output}); seen.add(c.input);
}
data.cases = cases;
return out(cases.length < 3 ? phase : 'public');'''
            label = 'Verify new tests against echo specification' if phase == 'tests' else 'Verify added cases and preserve existing tests'
        chain(free, req, reducer(label, route, parse+logic, x+1100, y))
    else:
        cases = json.dumps(examples, ensure_ascii=False) if phase == 'public' else r + '.data.cases'
        source = r + '.data.source' if phase != 'mutate' else json.dumps(faults) + '[' + r + '.data.variant][1]'
        req = http('Sandbox: ' + title, RUNNER, x, y, role='SANDBOX', body=f'{{source:{source}, cases:{cases}}}')
        logic = '''const verdict = $json.body?.verdict;
if (!['accepted','wrong_answer','runtime_error','time_limit','output_limit','memory_limit'].includes(verdict))
  throw new Error('Invalid sandbox verdict');
'''
        if phase == 'mutate':
            logic += f'''const variants = {json.dumps(faults)};
if (verdict !== 'wrong_answer') data.survivors.push(variants[data.variant][0]);
data.variant++;
const next = data.variant < variants.length ? 'mutate' :
  !data.survivors.length ? 'certified' : data.calls < 12 ? 'expand' : 'needs_review';
data.faultsKilled = data.variant - data.survivors.length;
return {{json: {{phase:next,data}}}};'''
            label = 'Count killed variants or request more coverage'
        else:
            logic += f'''let next = {json.dumps('suite' if phase == 'public' else 'mutate')};
if (verdict !== 'accepted') {{
  data.failure = {{case: ({cases})[$json.body.test_index-1], verdict}};
  next = data.calls < 12 ? 'repair' : 'needs_review';
}} else if (next === 'mutate') {{ data.variant = 0; data.survivors = []; }}
return {{json: {{phase:next,data}}}};'''
            label = 'Route public example verdict' if phase == 'public' else 'Route private test verdict'
        chain(route, req, reducer(label, route, logic, x+220, y))
link(previous, terminal, 1)

workflow = dict(name='LMS certification — echo pilot', nodes=nodes, connections=edges,
                settings=dict(errorWorkflow='iZn7biFh6321a1w8', executionOrder='v1', timezone='Europe/Moscow',
                              executionTimeout=720, saveDataSuccessExecution='none', saveDataErrorExecution='none',
                              saveExecutionProgress=False, saveManualExecutions=False))
if __name__ == '__main__':
    (ROOT / 'workflow.json').write_text(json.dumps(workflow, ensure_ascii=False, indent=2)+'\n')
