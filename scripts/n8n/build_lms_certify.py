#!/usr/bin/env python3
"""Build the importable pilot workflow. Does not activate or deploy anything."""
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from lms_reviewed_batch import SPECS, ORACLE_JS

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
    result = node(name, 'httpRequest', 4.2, params, x, y, credential)
    nodes[-1]['onError'] = 'continueRegularOutput'
    return result


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
claim = pg('Claim next queued task and load checkpoint', '''WITH candidate AS (
 SELECT id FROM lms_certification.pilot
 WHERE phase NOT IN ('certified','needs_review')
 AND data->>'contract' IN ('echo','sum','length','parity','sign','leap','repeat4','python_exact','zen','meow','yes_no','xmas','parrot','reverse','temperature','heights','until_zero','until_nonmultiple','until_empty','xmas2','xmas3')
 AND (lease_until IS NULL OR lease_until < clock_timestamp())
 AND NOT EXISTS (SELECT 1 FROM lms_certification.pilot WHERE lease_until > clock_timestamp())
 ORDER BY CASE WHEN owner IS NOT NULL THEN 0 ELSE 1 END, updated_at, id FOR UPDATE SKIP LOCKED LIMIT 1
)
UPDATE lms_certification.pilot p SET owner=$1, lease_until=clock_timestamp()+interval '15 minutes'
FROM candidate c WHERE p.id=c.id RETURNING p.phase,p.data''', '[$execution.id]', 1100, 0)
chain(start, entry)
link(gate, claim)
checkpoint = pg('Checkpoint and dispatch next phase', '''UPDATE lms_certification.pilot
SET phase = $2, data = $3::jsonb, updated_at = clock_timestamp(),
lease_until = CASE WHEN $2 IN ('certified','needs_review') THEN NULL ELSE clock_timestamp() + interval '15 minutes' END
WHERE owner = $1 AND lease_until > clock_timestamp()
RETURNING phase, data''', '[$execution.id, $json.phase, JSON.stringify($json.data)]', 1480, -380)
release = pg('Pause and release lease', '''UPDATE lms_certification.pilot SET lease_until = NULL
WHERE owner = $1 RETURNING phase''', '[$execution.id]', 1140, -580)
terminal = pg('Private outcome recorded', '''SELECT phase, count(*)::int AS tasks,
 max(updated_at) AS latest_update FROM lms_certification.pilot GROUP BY phase ORDER BY phase''', '[]', 4900, -380)



def ref(name):
    return '$(' + json.dumps(name) + ').item.json'


def reducer(name, route, js, x, y):
    n = code(name, f'''const {{phase,data}} = {ref(route)};
const status = $json.statusCode;
if ($json.error || status === 429 || status >= 500) return {{json: {{pause:true}}}};
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
                       'Добавь допустимые граничные случаи: нули, отрицательные числа или особенности строк, если они разрешены условием. ' + 'Не придумывай недопустимые входы. Верни не менее 6 различных случаев. ')
        if phase in {'tests','expand'}:
            prompt = json.dumps(test_prompt, ensure_ascii=False) + f" + '\\nУсловие: ' + {r}.data.statement"
            if phase == 'expand':
                prompt += f''' + '\\nУже проверенные входы: ' + JSON.stringify({r}.data.cases.map(c => c.input)) + '\\nЧто не поймано: ' + JSON.stringify({r}.data.survivors) + '\\nЦелевые условия для покрытия: ' + JSON.stringify({r}.data.coverageHints || '')'''
        else:
            prompt = json.dumps('Верни решение на Python 3 в формате JSON {"source":"..."}. Только учебный Python, без файлов и сети. Условие: ', ensure_ascii=False) + f' + {r}.data.statement'
            if phase == 'repair':
                prompt += f''' + '\\nПредыдущее решение: ' + JSON.stringify({r}.data.source) + '\\nПроваленный проверенный тест: ' + JSON.stringify({r}.data.failure)'''
                prompt += f" + '\\nДиагностика: ' + JSON.stringify({r}.data.repairGuidance || '') + '\\nНе нормализуй пробелы и регистр, если условие этого явно не требует. Исправь причину ошибки, не меняй проверенный тест. Верни JSON с diagnosis и source. Не повторяй прежнюю программу.'"
        req = http('LLM: ' + title, LLM, x+880, y, role='LITELLM', body=
                   f'''{{model:{json.dumps(MODEL)}, temperature:0, max_tokens:1000, response_format:{{type:'json_object'}}, messages:[{{role:'user', content: {prompt}}}]}}''')
        parse = '''let payload;
try { payload = JSON.parse($json.body.choices[0].message.content); } catch { payload = {}; }
 data.calls = (data.calls || 0) + 1;
 const out = next => ({json:{phase:data.calls >= (data.callLimit || 12) && ['solve','repair','tests','expand'].includes(next) ? 'needs_review' : next,data}});
'''
        if phase in {'solve','repair'}:
            logic = '''const source = typeof payload?.source === 'string' ? payload.source.trim() : '';
if (!source || source.length > 6000 || (data.contract === 'echo' && (/[\\r\\n]/.test(source) || [...source].length > 14))) return out(phase);
data.repeatedSource = phase === 'repair' && source === data.source;
data.source = source;
return out(phase === 'solve' ? 'tests' : 'public');'''
            label = 'Validate solution format' if phase == 'solve' else 'Validate repaired solution format'
        else:
            logic = r'''// Reviewed deterministic oracle: no candidate source is read here.
function expected(input) {
 const lines = input.endsWith('\n') ? input.slice(0,-1).split('\n') : [];
__BATCH_ORACLE__
 if (data.contract === 'echo' || data.contract === 'length') {
  if (lines.length !== 1 || input.includes('\r')) return null;
  return data.contract === 'echo' ? input : `Слово ${lines[0]} имеет длину ${[...lines[0]].length}\n`;
 }
 if (data.contract === 'leap') {
  if (lines.length!==1 || !/^[1-9]\d{0,5}$/.test(lines[0])) return null;
  const year=Number(lines[0]);
  return (year%400===0 || (year%4===0 && year%100!==0) ? 'Високосный' : 'Не високосный')+'\n';
 }
 if (data.contract === 'sum') {
  if (lines.length !== 2 || !lines.every(x => /^[+-]?\d{1,30}$/.test(x))) return null;
  return String(BigInt(lines[0])+BigInt(lines[1]))+'\n';
 }
 if (data.contract === 'parity') {
  if (lines.length !== 1 || !/^[+-]?\d{1,30}$/.test(lines[0])) return null;
  return BigInt(lines[0])%2n === 0n ? 'чётное\n' : 'нечётное\n';
 }
 if (data.contract === 'sign') {
  if (lines.length !== 1 || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(lines[0])) return null;
  const n=Number(lines[0]); if (!Number.isFinite(n) || Math.abs(n)>1e100) return null;
  return (n>0?'+':n<0?'-':'0')+'\n';
 }
 throw new Error('Unsupported reviewed contract');
}
const cases=data.cases || [], seen=new Set(cases.map(c=>c.input));
const proposals = [...(phase === 'expand' ? data.targetedCases || [] : []), ...(Array.isArray(payload?.cases)?payload.cases.slice(0,16):[])];
for (const c of proposals) {
 if (typeof c?.input !== 'string' || c.input.length>256 || typeof c.output !== 'string' ||
     expected(c.input) !== c.output || seen.has(c.input) ||
     data.examples.some(e=>e.input===c.input) || cases.length>=16) continue;
 cases.push({input:c.input,output:c.output});seen.add(c.input);
}
data.cases=cases;
return out(cases.length<3?phase:'public');'''
            logic = logic.replace('__BATCH_ORACLE__', ORACLE_JS)
            label = 'Verify new tests against reviewed specification' if phase == 'tests' else 'Verify added cases and preserve existing tests'
        chain(free, req, reducer(label, route, parse+logic, x+1100, y))
    else:
        cases = r + '.data.examples' if phase == 'public' else r + '.data.cases'
        source = r + '.data.source' if phase != 'mutate' else r + '.data.faults[' + r + '.data.variant][1]'
        req = http('Sandbox: ' + title, RUNNER, x, y, role='SANDBOX', body=f'{{source:{source}, cases:{cases}}}')
        logic = '''const verdict = $json.body?.verdict;
if (!['accepted','wrong_answer','runtime_error','time_limit','output_limit','memory_limit'].includes(verdict))
  throw new Error('Invalid sandbox verdict');
'''
        if phase == 'mutate':
            logic += f'''const variants = data.faults;
if (verdict !== 'wrong_answer') data.survivors.push(variants[data.variant][0]);
data.variant++;
const next = data.variant < variants.length ? 'mutate' :
  !data.survivors.length ? 'certified' : data.calls < (data.callLimit || 12) ? 'expand' : 'needs_review';
data.faultsKilled = data.variant - data.survivors.length;
return {{json: {{phase:next,data}}}};'''
            label = 'Count killed variants or request more coverage'
        else:
            logic += f'''let next = {json.dumps('suite' if phase == 'public' else 'mutate')};
if (verdict !== 'accepted') {{
  data.failure = {{case: ({cases})[$json.body.test_index-1], verdict}};
  next = data.calls < (data.callLimit || 12) ? 'repair' : 'needs_review';
}} else if (next === 'mutate') {{ data.variant = 0; data.survivors = []; data.faultsKilled = 0; }}
return {{json: {{phase:next,data}}}};'''
            label = 'Route public example verdict' if phase == 'public' else 'Route private test verdict'
        chain(route, req, reducer(label, route, logic, x+220, y))
link(previous, terminal, 1)

workflow = dict(name='LMS certification — reviewed queue', nodes=nodes, connections=edges,
                settings=dict(errorWorkflow='iZn7biFh6321a1w8', executionOrder='v1', timezone='Europe/Moscow',
                              executionTimeout=720, saveDataSuccessExecution='none', saveDataErrorExecution='all',
                              saveExecutionProgress=False, saveManualExecutions=False))
if __name__ == '__main__':
    (ROOT / 'workflow.json').write_text(json.dumps(workflow, ensure_ascii=False, indent=2)+'\n')
