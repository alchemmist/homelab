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
    out = {'id': str(uuid5(NAMESPACE_URL, 'lms-certification/' + name)), 'name': name,
               'type': 'n8n-nodes-base.' + kind, 'typeVersion': version, 'position': [x, y], 'parameters': params}
    if credential:
        typ, role = credential
        out['credentials'] = {typ: {'id': 'REPLACE_' + role, 'name': role}}
    nodes.append(out)
    return name


def link(a, b, port=0):
    branches = edges.setdefault(a, {'main': []})['main']
    while len(branches) <= port:
        branches.append([])
    branches[port].append({'node': b, 'type': 'main', 'index': 0})


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
    params = {'url': url, 'options': {'timeout': 180000 if role=='LITELLM' else 90000 if body else 8000,
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
    valid = code(prefix + ' verify both metrics', r'''const values = $(__VALUES__).item.json;
const stamps = $json;
const invalid = {json: {idle: false, telemetryValid: false}};
const model = __MODEL__;
const names = ['running', 'waiting'];
const now = Date.now()/1000;
function rows(r) {
  return r && !Object.hasOwn(r, 'error') && r.statusCode === 200 &&
    r.body?.status === 'success' && !Object.hasOwn(r.body, 'error') &&
    r.body.data?.resultType === 'vector' && Array.isArray(r.body.data.result)
    ? r.body.data.result : null;
}
function sample(r, timestamp) {
  if (!r || !r.metric || typeof r.metric !== 'object' || Array.isArray(r.metric) ||
      Object.values(r.metric).some(v => typeof v !== 'string') ||
      r.metric.model_name !== model || !Array.isArray(r.value) || r.value.length !== 2 ||
      typeof r.value[0] !== 'number' || !Number.isFinite(r.value[0]) || r.value[0] <= 0 ||
      typeof r.value[1] !== 'string' ||
      !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(r.value[1]) ||
      !Number.isFinite(Number(r.value[1]))) return null;
  const metric = timestamp ? r.metric.queue_metric :
    r.metric.__name__?.replace(/^vllm:num_requests_/, '');
  if (!names.includes(metric) || (!timestamp &&
      (r.metric.__name__ !== 'vllm:num_requests_'+metric || Object.hasOwn(r.metric, 'queue_metric')))) return null;
  const labels = JSON.stringify(Object.entries(r.metric)
    .filter(([k]) => !['__name__', 'queue_metric'].includes(k))
    .sort(([a],[b]) => a.localeCompare(b)));
  return {metric, labels, key: JSON.stringify([metric, labels]), value: Number(r.value[1])};
}
const v = rows(values), t = rows(stamps);
if (!v || !t || !v.length || v.length !== t.length) return invalid;
const valuesByKey = new Map(), pairs = new Map();
let idle = true;
for (const row of v) {
  const s = sample(row, false);
  if (!s || valuesByKey.has(s.key)) return invalid;
  valuesByKey.set(s.key, s);
  if (!pairs.has(s.labels)) pairs.set(s.labels, new Set());
  pairs.get(s.labels).add(s.metric);
  idle = idle && s.value === 0;
}
if ([...pairs.values()].some(metrics => !names.every(n => metrics.has(n)))) return invalid;
const seen = new Set();
for (const row of t) {
  const s = sample(row, true);
  if (!s || seen.has(s.key) || !valuesByKey.has(s.key)) return invalid;
  const age = now - s.value;
  if (!Number.isFinite(age) || age < -5 || age > 45) return invalid;
  seen.add(s.key);
}
return {json: {idle, telemetryValid: true}};'''.replace('__VALUES__', json.dumps(values)).replace('__MODEL__', json.dumps(MODEL)), x+440, y)
    gate = check(prefix + ' model idle?', '$json.idle === true', x+660, y)
    chain(values, stamps, valid, gate)
    return values, gate


start = node('Every minute', 'scheduleTrigger', 1.2, {'rule': {'interval': [{'field': 'minutes', 'minutesInterval': 1}]}}, 0, 0)
entry, gate = idle('Admission:', 220, 0)
# One allowlist computed from reviewed source, never from untrusted queue rows.
reviewed = sorted({'differential_v1','echo','sum','length','parity','sign','leap'} | {spec[0] for spec in SPECS.values()})
assert all(name.isidentifier() and name.isascii() for name in reviewed)
contract_list = ','.join(repr(name) for name in reviewed)
# Only rebind reviewed, plain-prose contracts; do not normalize whitespace inside
# source listings, formatted templates or arbitrary statements. SQL folds only
# single newline word wraps in these five explicitly reviewed source texts.
refill = pg('Admit equivalent import if reviewed queue is empty', """WITH match AS (
 SELECT d.id, c.id AS origin, c.data AS ref
 FROM lms_certification.pilot d JOIN lms_certification.pilot c
 ON trim(replace(d.data->>'statement', E'\\n', ' '))=trim(replace(c.data->>'statement', E'\\n', ' '))
 WHERE d.phase='solve' AND d.data->>'contract'='draft_stdin' AND coalesce((d.data->>'calls')::int,0)=0
 AND c.phase='certified' AND c.id IN ('basics/conditionals/meow','basics/builtin-functions/add-two-numbers',
 'basics/conditionals/echo-2','basics/environment-intro/parrot','basics/environment-intro/reverse-parrot')
 AND jsonb_array_length(d.data->'examples') BETWEEN 1 AND 16
 AND NOT EXISTS(SELECT 1 FROM lms_certification.pilot pending WHERE pending.phase NOT IN ('certified','needs_review')
 AND pending.data->>'contract' IN (""" + contract_list + """))
 ORDER BY d.id LIMIT 1 FOR UPDATE OF d SKIP LOCKED
), admitted AS (
 UPDATE lms_certification.pilot d SET phase=CASE WHEN jsonb_array_length(kept.cases)>=3 THEN 'public' ELSE 'tests' END,
 data=d.data || jsonb_build_object('contract',m.ref->'contract','source',m.ref->'source','cases',kept.cases,
 'importedExamplesRaw',dest.data->'examples','examples',display.cases,'faults',m.ref->'faults','equivalentTo',m.origin,'calls',0,'coverageHints',m.ref->'coverageHints',
 'targetedCases',coalesce(m.ref->'targetedCases','[]'::jsonb)), updated_at=clock_timestamp()
 FROM match m JOIN lms_certification.pilot dest ON dest.id=m.id
 CROSS JOIN LATERAL (SELECT jsonb_agg(jsonb_build_object(
 'input',CASE WHEN right(x->>'input',1)=chr(10) THEN x->>'input' ELSE (x->>'input')||chr(10) END,
 'output',CASE WHEN right(x->>'output',1)=chr(10) OR x->>'output'='' THEN x->>'output' ELSE (x->>'output')||chr(10) END) ORDER BY ord) AS cases
 FROM jsonb_array_elements(dest.data->'examples') WITH ORDINALITY e(x,ord)) display
 CROSS JOIN LATERAL (SELECT coalesce(jsonb_agg(x ORDER BY ord),'[]'::jsonb) AS cases
 FROM jsonb_array_elements(m.ref->'cases') WITH ORDINALITY e(x,ord)
 WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(display.cases) pub WHERE pub->>'input'=x->>'input')) kept
 WHERE d.id=m.id RETURNING d.id
) SELECT count(*)::int AS admitted FROM admitted""", '[]', 1060, -160)
admit = pg('Admit next elementary stdin exercise', f'''WITH candidate AS (
 SELECT id FROM lms_certification.pilot
 WHERE data->>'contract'='draft_stdin' AND phase='solve'
 AND split_part(id,'/',2) IN ('lists-intro','list-string-methods','strings-indexing','strings-slicing','dicts-intro','sets','nested-lists','split-join-comprehensions','tuples-conversion','for-intro','nested-loops','while-intro','break-continue','builtin-functions')
 AND jsonb_array_length(data->'examples') BETWEEN 1 AND 12
 AND length(data->>'statement') BETWEEN 60 AND 6000
 AND (data->>'statement') !~* 'файл|функци[юя]|класс[а ]|предыдущ|интерактив|сеть|сервер|библиотек|запрос HTTP'
 AND NOT EXISTS (SELECT 1 FROM lms_certification.pilot WHERE phase NOT IN ('certified','needs_review') AND data->>'contract' IN ({contract_list}))
 ORDER BY length(data->>'statement'),id LIMIT 1 FOR UPDATE SKIP LOCKED
), added AS (UPDATE lms_certification.pilot p SET data=data || jsonb_build_object('contract','differential_v1','certificateScope','bounded_same_model_differential','callLimit',14),updated_at=clock_timestamp()
 FROM candidate c WHERE p.id=c.id RETURNING p.id) SELECT count(*)::int AS admitted FROM added''', '[]',1080,-300)
claim = pg('Claim next queued task and load checkpoint', f'''WITH candidate AS (
 SELECT id FROM lms_certification.pilot
 WHERE phase NOT IN ('certified','needs_review')
 AND data->>'contract' IN ({contract_list})
 AND (lease_until IS NULL OR lease_until < clock_timestamp())
 AND NOT EXISTS (SELECT 1 FROM lms_certification.pilot WHERE lease_until > clock_timestamp())
 ORDER BY CASE WHEN owner IS NOT NULL THEN 0 ELSE 1 END, updated_at, id FOR UPDATE SKIP LOCKED LIMIT 1
)
UPDATE lms_certification.pilot p SET owner=$1, lease_until=clock_timestamp()+interval '15 minutes'
FROM candidate c WHERE p.id=c.id RETURNING p.phase,p.data''', '[$execution.id]', 1100, 0)
chain(start, entry)
heartbeat_sql = """INSERT INTO lms_certification.heartbeat(singleton,at,execution_id,decision,ticks)
VALUES(true,clock_timestamp(),$1,$2,1) ON CONFLICT(singleton) DO UPDATE SET at=EXCLUDED.at,
execution_id=EXCLUDED.execution_id,decision=EXCLUDED.decision,ticks=lms_certification.heartbeat.ticks+1 RETURNING decision"""
ready = pg('Record idle tick',heartbeat_sql,"[$execution.id,'idle']",920,-180)
skipped = pg('Record busy or telemetry skip',heartbeat_sql,"[$execution.id,$json.telemetryValid?'busy':'telemetry_unavailable']",920,200)
# A busy GPU blocks inference, not a previously checkpointed Docker verdict.
# No new admission from this branch. Every subsequent LLM phase still has its
# own strict fresh-series check, including a transition from suite to repair.
sandbox_claim = pg('Resume sandbox-only checkpoint',f'''WITH candidate AS (
 SELECT id FROM lms_certification.pilot WHERE phase IN ('public','suite','mutate','plausible','wpublic','wsuite','triage')
 AND data->>'contract' IN ({contract_list}) AND (lease_until IS NULL OR lease_until < clock_timestamp())
 AND NOT EXISTS (SELECT 1 FROM lms_certification.pilot WHERE lease_until>clock_timestamp())
 ORDER BY updated_at,id FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE lms_certification.pilot p SET owner=$1,lease_until=clock_timestamp()+interval '15 minutes'
FROM candidate c WHERE p.id=c.id RETURNING p.phase,p.data''','[$execution.id]',1160,240)
link(gate, skipped, 1)
link(skipped,sandbox_claim)
chain(gate, ready, refill)
chain(refill, admit, claim)
checkpoint = pg('Checkpoint and dispatch next phase', '''UPDATE lms_certification.pilot
SET phase = $2, data = ($3::jsonb - 'transportRetries'), updated_at = clock_timestamp(),
lease_until = CASE WHEN $2 IN ('certified','needs_review') THEN NULL ELSE clock_timestamp() + interval '15 minutes' END
WHERE owner = $1 AND lease_until > clock_timestamp()
RETURNING phase, data''', '[$execution.id, $json.phase, JSON.stringify($json.data)]', 1480, -380)
release = pg('Pause and release lease', '''UPDATE lms_certification.pilot SET lease_until = NULL,
 phase=CASE WHEN $2='transport' AND coalesce((data->>'transportRetries')::int,0)>=2 THEN 'needs_review' ELSE phase END,
 data=data || jsonb_build_object('lastPause',$2::text,'pausedAt',clock_timestamp()) ||
 CASE WHEN $2='transport' THEN jsonb_build_object('transportRetries',coalesce((data->>'transportRetries')::int,0)+1) ELSE '{}'::jsonb END ||
 CASE WHEN $2='transport' AND coalesce((data->>'transportRetries')::int,0)>=2 THEN jsonb_build_object('reviewReason','consecutive_transport_failures','resumePhase',phase) ELSE '{}'::jsonb END
WHERE owner = $1 RETURNING phase''', "[$execution.id, $json.reason || 'not_idle_or_stale']", 1140, -580)
terminal = pg('Private outcome recorded', '''SELECT phase, count(*)::int AS tasks,
 max(updated_at) AS latest_update FROM lms_certification.pilot GROUP BY phase ORDER BY phase''', '[]', 4900, -380)



def ref(name):
    return '$(' + json.dumps(name) + ').item.json'


def reducer(name, route, js, x, y):
    n = code(name, f'''const {{phase,data}} = {ref(route)};
const status = $json.statusCode;
if ($json.error || status === 429 || status >= 500) return {{json: {{pause:true,reason:$json.error?'transport':'http_'+status}}}};
if (status !== 200) throw new Error('Unexpected service HTTP status: ' + status);
{js}''', x, y)
    ok = check(name + ' checkpoint?', '$json.pause !== true', x+220, y)
    chain(n, ok, checkpoint)
    link(ok, release, 1)
    return n


phase_specs = [('solve','Generate solution'), ('tests','Author blind tests'), ('public','Run public examples'),
               ('repair','Repair solution'), ('suite','Run verified private tests'), ('mutate','Run one fault variant'),
               ('expand','Add missing corner cases'), ('witness','Independent blind solution'), ('wrepair','Repair witness against public example'), ('audit','Review suite and curriculum'), ('probes','Design realistic wrong solutions'), ('wpublic','Cross-check witness on examples'), ('wsuite','Cross-check witness on private tests'), ('triage','Run disputed case on witness'), ('plausible','Check probe on a correct case')]
previous = None
for i, (phase, title) in enumerate(phase_specs):
    y = i * 300 + 120
    route = check('Phase: ' + phase, '$json.phase === ' + json.dumps(phase), 1490+i*240, y)
    if previous:
        link(previous, route, 1)
    else:
        link(claim, route)
        link(sandbox_claim,route)
        link(checkpoint, route)
    previous = route
    r = ref(route)
    x = 1770+i*240
    if phase in {'solve','tests','repair','expand','witness','wrepair','audit','probes'}:
        first, free = idle(title + ':', x, y)
        link(route, first)
        link(free, release, 1)
        test_prompt = ('Придумай корректные закрытые тесты по условию. JSON {"cases":[{"input":"строка\\n","output":"строка\\n"}]}. '
                       'Добавь допустимые граничные случаи: нули, отрицательные числа или особенности строк, если они разрешены условием. ' + 'Не придумывай недопустимые входы. Верни не менее 6 различных случаев. ')
        if phase in {'tests','expand'}:
            prompt = json.dumps(test_prompt, ensure_ascii=False) + f" + '\\nУсловие: ' + {r}.data.statement"
            prompt = f"({r}.data.contract === 'mult_table' ? " + json.dumps('Предложи четыре разных маленьких натуральных размера таблицы от 1 до 6 кроме публичного примера 3. Только входы: JSON {"cases":[{"input":"1\\n"}]}. Не генерируй таблицы вывода. Условие: ') + f" + {r}.data.statement : (" + prompt + "))"
            prompt = f"({r}.data.contract === 'thank_count' ? " + json.dumps('Предложи 6 разных входов, включая немедленное завершение, пустую строку до завершения и похожие, но неточные варианты маркера. Каждый вход содержит отдельную строку ровно Спасибо. и перевод строки после неё. Только JSON {"cases":[{"input":"Спасибо.\\n"}]}; ожидаемые ответы вычисляет проверяющая программа. Условие: ') + f" + {r}.data.statement : (" + prompt + "))"
            prompt = f"({r}.data.contract === 'noinput_reviewed' ? " + json.dumps('У задачи нет ввода. Независимо выведи единственный полный ожидаемый stdout с финальным переводом строки. JSON {"cases":[{"input":"","output":"..."}]}. Условие: ') + f" + {r}.data.statement : (" + prompt + "))"
            prompt += f" + ({r}.data.contract==='differential_v1' ? '\\nИспользуй только бесспорно допустимые входы. Если требуется слово — непустые буквенные слова, в том числе односимвольные. Возьми короткие примеры: для перечисления чисел выбирай n до 8, не используй большие ответы или многоточия. Общий ответ JSON до 700 токенов. Чередуй разные длины и состав входа. Не тестируй неоговоренные пробелы, пустой ввод, ошибки или неоднозначное форматирование. Буквальные публичные примеры не повторяй: '+JSON.stringify({r}.data.examples) : '')"
            if phase == 'expand':
                prompt += f''' + '\\nУже проверенные входы: ' + JSON.stringify({r}.data.cases.map(c => c.input)) + '\\nЧто не поймано: ' + JSON.stringify({r}.data.survivors) + '\\nЦелевые условия для покрытия: ' + JSON.stringify({r}.data.coverageHints || '')'''
        else:
            prompt = json.dumps('Верни решение на Python 3 в формате JSON {"source":"..."}. Только учебный Python, без файлов и сети. Условие: ', ensure_ascii=False) + f' + {r}.data.statement'
            if phase == 'repair':
                prompt += f''' + '\\nПредыдущее решение: ' + JSON.stringify({r}.data.source) + '\\nПроваленный проверенный тест: ' + JSON.stringify({r}.data.failure)'''
                prompt += f" + '\\nДиагностика: ' + JSON.stringify({r}.data.repairGuidance || '') + '\\nНе нормализуй пробелы и регистр, если условие этого явно не требует. Исправь причину ошибки, не меняй проверенный тест. Верни JSON с diagnosis и source. Не повторяй прежнюю программу.'"
        if phase in ('witness','wrepair'):
            prompt=json.dumps('Независимо реши задачу на Python 3, только stdin/stdout. По возможности используй альтернативный простой подход. Код краткий, без комментариев и черновых рассуждений. Не считывай вход дважды. JSON {"source":"..."}. Условие: ') + f' + {r}.data.statement'
            if phase=='wrepair':prompt += f" + '\\nСвой предыдущий исходник и собственный проваленный публичный пример: ' + JSON.stringify([{r}.data.witness,{r}.data.witnessFailure])"
        if phase=='audit':
            prompt=json.dumps('Проверь по условию каждую пару вход/выход, границы и допустимость входов, покрытие обычных и крайних случаев, а также соответствие решения ограничениям урока. Не требуй обработки недопустимых входов, если их нет среди предложенных тестов. Например, слово из букв непустое; ошибка на пустом вводе вне области сама по себе не недостаток. Не одобряй реально спорные результаты на допустимых входах, неполные задачи, неверный формат или тесты вне области. Верни JSON {"approved":true/false,"reason":"...","issue":"cases|spec|solution","badIndices":[]}. Для изолированной ошибки частных тестов укажи issue=cases и точные нумерованные с нуля индексы неверных случаев. Не меняй публичные примеры. Материалы: ') + f' + JSON.stringify({{statement:{r}.data.statement,examples:{r}.data.examples,cases:{r}.data.cases,source:{r}.data.source,disputedIndex:{r}.data.disputedIndex,disputeNote:{r}.data.disputeNote}})'
        if phase=='probes':
            prompt=json.dumps('По условию составь от трёх до пяти разных правдоподобных ошибочных решения школьника на Python: ошибка границы, пропущенное условие или неверное преобразование. Каждое должно читать корректный ввод, завершаться без исключений и отличаться от правильного результата на части (не всех) допустимых входов. Не возвращай пустые программы или константы. JSON {"faults":[{"label":"...","source":"..."}]}. Условие: ') + f" + {r}.data.statement + '\\nИзмени одну содержательную операцию в данном решении, сохрани ввод, вывод и все остальные строки. Для каждой версии оставь часть допустимых входов верной. Не подгоняй под примеры. Исходник: ' + JSON.stringify({r}.data.source) + '\\nРанее непригодные модели ошибок: ' + JSON.stringify({r}.data.rejectedProbeLabels||[]) + '\\nСписок входов, на которых будут проверены варианты: '+JSON.stringify([...{r}.data.examples,...{r}.data.cases].map(c=>c.input)) + '\\nДля каждого варианта мысленно проверь два конкретных входа из списка: один проходит, другой нет. Выбери содержательные ошибки (например, ошибочное приведение регистра, неверная граница). Запрещены сравнения с конкретным тестовым входом и зашитые ответы.'"
        req = http('LLM: ' + title, LLM, x+880, y, role='LITELLM', body=
                   f'''{{model:{json.dumps(MODEL)}, temperature:0, max_tokens:1000, response_format:{{type:'json_object'}}, messages:[{{role:'user', content: {prompt}}}]}}''')
        parse = '''let payload;
try { payload = JSON.parse($json.body.choices[0].message.content); } catch { payload = {}; data.modelFormatErrors=(data.modelFormatErrors||0)+1; data.lastFinishReason=String($json.body?.choices?.[0]?.finish_reason||'unknown').slice(0,40); }
 data.calls = (data.calls || 0) + 1;
 const out = next => ({json:{phase:data.calls >= (data.callLimit || 12) && ['solve','repair','tests','expand','witness','wrepair','audit','probes'].includes(next) ? 'needs_review' : next,data}});
'''
        if phase in ('witness','wrepair'):
            logic='''const w=payload?.source;if(typeof w!=='string'||!w.trim()||w.length>6000||w.replace(/\\s/g,'')===data.source.replace(/\\s/g,'')){data.reviewReason='no_distinct_witness';return out('needs_review');} data.witness=w;return out('wpublic');''';label='Validate blind witness' if phase=='witness' else 'Validate repaired witness'
        elif phase=='audit':
            logic='''if(payload?.approved!==true){data.reviewReason='semantic_review_failed';data.reviewDetail=String(payload?.reason||'').slice(0,500);
const ids=payload?.badIndices; if(payload?.issue==='cases' && Array.isArray(ids)&&ids.length && ids.every(i=>Number.isInteger(i)&&i>=0&&i<data.cases.length)&& (data.auditRetries||0)<2 && (!data.semanticApproved || (ids.length===1 && ids[0]===data.disputedIndex))){
 data.disputedIndex=null;data.disputeNote=null;data.quarantine=[...(data.quarantine||[]),...data.cases.filter((c,i)=>ids.includes(i))];data.cases=data.cases.filter((c,i)=>!ids.includes(i));data.coverageHints=data.reviewDetail;data.auditRetries=(data.auditRetries||0)+1;return out('expand');
}return out('needs_review');}data.semanticApproved=true;if(Number.isInteger(data.disputedIndex)){data.reviewReason='both_references_disagree_with_approved_expected';return out('needs_review');}return out(data.faults?.length?'public':'probes');''';label='Require semantic approval'
        elif phase=='probes':
            logic='''const probes=Array.isArray(payload?.faults)?payload.faults:[];const seen=new Set([data.source.trim(),data.witness.trim()]);data.faults=[];for(const p of probes){if(typeof p?.source!=='string'||!p.source.includes('input(')||p.source.length>6000||typeof p.label!=='string'||seen.has(p.source.trim()))continue;seen.add(p.source.trim());data.faults.push([p.label.slice(0,100),p.source]);}if(data.faults.length<3){data.reviewReason='insufficient_distinct_probes';return out('needs_review');}data.faults=data.faults.slice(0,5);return out('public');''';label='Require three distinct probes'
        elif phase in {'solve','repair'}:
            logic = '''const source = typeof payload?.source === 'string' ? payload.source.trim() : '';
if (!source || source.length > 6000 || (data.contract === 'echo' && (/[\\r\\n]/.test(source) || [...source].length > 14))) return out(phase);
data.repeatedSource = phase === 'repair' && source === data.source;
data.source = source;
if(data.contract==='noinput_reviewed'){data.cases=[{input:'',output:data.reviewedOutput}];return out(data.examples.length?'public':'suite');}
if(data.contract==='differential_v1')return out(phase==='solve'?'witness':'audit');
return out(phase === 'solve' ? 'tests' : (data.contract==='noinput_reviewed' && !data.examples.length ? 'suite' : 'public'));'''
            label = 'Validate solution format' if phase == 'solve' else 'Validate repaired solution format'
        else:
            logic = r'''if(data.contract==='differential_v1'){
 const cases=data.cases||[],seen=new Set([...data.examples,...cases,...(data.quarantine||[])].map(c=>c.input));
 for(const c of Array.isArray(payload?.cases)?payload.cases:[]){if(typeof c?.input!=='string'||typeof c.output!=='string'||Math.max(c.input.length,c.output.length)>1500||seen.has(c.input)||cases.length>=16)continue;cases.push({input:c.input,output:c.output});seen.add(c.input);}
 data.cases=cases;return out(cases.length>=4?'audit':phase);
}
// Reviewed deterministic oracle: no candidate source is read here.
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
 if (typeof c?.input !== 'string' || c.input.length>256) continue;
 const oracle = expected(c.input);
 const output = ['mult_table','thank_count'].includes(data.contract) && c.output===undefined ? oracle : c.output;
 if (typeof output !== 'string' || oracle !== output || seen.has(c.input) ||
     (data.contract!=='noinput_reviewed' && data.examples.some(e=>e.input===c.input)) || cases.length>=16) continue;
 cases.push({input:c.input,output});seen.add(c.input);
}
data.cases=cases;
if(data.contract==='noinput_reviewed')return out(!cases.length?phase:data.examples.length?'public':'suite');
return out(cases.length<3?phase:'public');'''
            logic = logic.replace('__BATCH_ORACLE__', ORACLE_JS)
            label = 'Verify new tests against reviewed specification' if phase == 'tests' else 'Verify added cases and preserve existing tests'
        chain(free, req, reducer(label, route, parse+logic, x+1100, y))
    else:
        cases = r + '.data.examples' if phase in ('public','wpublic') else r + '.data.cases'
        source = r + '.data.source' if phase != 'mutate' else r + '.data.faults[' + r + '.data.variant][1]'
        if phase=='plausible':
            source=r+'.data.faults['+r+'.data.variant][1]'
            cases='[['+r+'.data.examples,'+r+'.data.cases].flat()['+r+'.data.probeCase]]'
        if phase=='triage':cases='['+r+'.data.failure.case]'
        if phase in ('wpublic','wsuite','triage'):source=r+'.data.witness'
        req = http('Sandbox: ' + title, RUNNER, x, y, role='SANDBOX', body=f'{{source:{source}, cases:{cases}}}')
        logic = '''const verdict = $json.body?.verdict;
if (!['accepted','wrong_answer','runtime_error','time_limit','output_limit','memory_limit'].includes(verdict))
  throw new Error('Invalid sandbox verdict');
'''
        if phase=='triage':
            logic+='''if(verdict==='accepted')return {json:{phase:data.calls<(data.callLimit||12)?'repair':'needs_review',data}};
if(verdict!=='wrong_answer'){data.reviewReason='dispute_inconclusive';return {json:{phase:'needs_review',data}};}
data.disputedIndex=data.failure.index;data.disputeNote='Both independently written programs failed this proposed case. Recompute its expected output from the statement; do not change the statement or public examples.';return {json:{phase:data.calls<(data.callLimit||12)?'audit':'needs_review',data}};''';label='Distinguish bad case from bad solution'
        elif phase in ('wpublic','wsuite'):
            logic+=("if(verdict!=='accepted'){data.witnessFailure=data.examples[$json.body.test_index-1];data.witnessRetries=(data.witnessRetries||0)+1;return {json:{phase:data.witnessRetries<=2 && data.calls<(data.callLimit||12)?'wrepair':'needs_review',data}};}" if phase=='wpublic' else "if(verdict!=='accepted'){data.reviewReason='independent_witness_disagrees';return {json:{phase:'needs_review',data}};}")+ ("return {json:{phase:data.semanticApproved?'wsuite':'tests',data}};" if phase=='wpublic' else "data.variant=0;data.survivors=[];data.faultsKilled=0;return {json:{phase:'mutate',data}};")
            label='Check witness verdict '+phase
        elif phase=='plausible':
            logic+='''if(verdict==='wrong_answer' && ++data.probeCase<data.examples.length+data.cases.length)return {json:{phase:'plausible',data}};
if(verdict==='accepted') data.faultsKilled=(data.faultsKilled||0)+1;
else {data.rejectedProbeLabels=[...(data.rejectedProbeLabels||[]),data.faults[data.variant][0]];}
data.variant++; data.probeCase=0;
if(data.variant<data.faults.length)return {json:{phase:'mutate',data}};
if(data.faultsKilled>=3)return {json:{phase:'certified',data}};
data.reviewReason='probe_not_plausible';data.probeRetries=(data.probeRetries||0)+1;return {json:{phase:data.probeRetries<=2 && data.calls<(data.callLimit||12)?'probes':'needs_review',data}};'''
            label='Reject crashes and always-wrong probes'
        elif phase == 'mutate':
            logic += f'''const variants = data.faults;
if(data.contract==='differential_v1') {{
 if(verdict==='wrong_answer') {{data.probeCase=0;return {{json:{{phase:'plausible',data}}}};}}
 if(verdict!=='accepted') {{data.reviewReason='probe_crashed';return {{json:{{phase:'needs_review',data}}}};}}
 data.survivors=[variants[data.variant][0]];return {{json:{{phase:data.calls<(data.callLimit||12)?'expand':'needs_review',data}}}};
}}
if (verdict !== 'wrong_answer') data.survivors.push(variants[data.variant][0]);
data.variant++;
const next = data.variant < variants.length ? 'mutate' :
  !data.survivors.length ? 'certified' : data.calls < (data.callLimit || 12) ? 'expand' : 'needs_review';
data.faultsKilled = data.variant - data.survivors.length;
return {{json: {{phase:next,data}}}};'''
            label = 'Count killed variants or request more coverage'
        else:
            logic += f'''let next = {json.dumps('suite' if phase == 'public' else 'mutate')};
if(next==='mutate' && data.contract==='differential_v1')next='wpublic';
if (verdict !== 'accepted') {{
  data.failure = {{case: ({cases})[$json.body.test_index-1], index:$json.body.test_index-1, verdict}};
  if(data.contract==='differential_v1' && phase==='suite' && verdict==='wrong_answer') return {{json:{{phase:'triage',data}}}};
  next = data.calls < (data.callLimit || 12) ? 'repair' : 'needs_review';
}} else if (next === 'mutate') {{ data.variant = 0; data.survivors = []; data.faultsKilled = 0; }}
return {{json: {{phase:next,data}}}};'''
            label = 'Route public example verdict' if phase == 'public' else 'Route private test verdict'
        chain(route, req, reducer(label, route, logic, x+220, y))
link(previous, terminal, 1)

assert len({n['name'] for n in nodes}) == len(nodes) == len({n['id'] for n in nodes}), 'Duplicate node names or IDs'
workflow = {'name': 'LMS certification — reviewed queue', 'nodes': nodes, 'connections': edges,
                'settings': {'errorWorkflow': 'iZn7biFh6321a1w8', 'executionOrder': 'v1', 'timezone': 'Europe/Moscow',
                              'executionTimeout': 720, 'saveDataSuccessExecution': 'none', 'saveDataErrorExecution': 'all',
                              'saveExecutionProgress': False, 'saveManualExecutions': False}}
if __name__ == '__main__':
    (ROOT / 'workflow.json').write_text(json.dumps(workflow, ensure_ascii=False, indent=2)+'\n')
