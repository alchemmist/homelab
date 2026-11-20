const assert = require('node:assert/strict');
const graph = require('../../docs/n8n/lms-certify/workflow.json');
const nodes = new Map(graph.nodes.map(n => [n.name, n]));
const run = (name, input, prev = {}) => new Function('$json', '$', nodes.get(name).parameters.jsCode)(input, () => ({item:{json:prev}})).json;
assert.equal(nodes.has('One certify step'), false);
for (const [name, {main}] of Object.entries(graph.connections)) {
  assert(nodes.has(name));
  for (const e of main.flat()) assert(nodes.has(e.node));
}
for (const n of graph.nodes.filter(n => n.type === 'n8n-nodes-base.code')) new Function(n.parameters.jsCode);
const now = Date.now()/1000;
const prom = result => ({statusCode:200,body:{status:'success',data:{resultType:'vector',result}}});
const values = ['running','waiting'].map(m => ({metric:{__name__:`vllm:num_requests_${m}`, instance:'a',model_name:'qwen3.8-27b'},value:[now,'0']}));
const timestamps = ['running','waiting'].map(m => ({metric:{queue_metric:m,instance:'a',model_name:'qwen3.8-27b'},value:[now,String(now)]}));
const idle = (v,t) => run('Admission: verify both metrics',prom(t),prom(v)).idle;
assert.equal(idle(values,timestamps),true);
assert.equal(idle(values.slice(0,1),timestamps),false);
assert.equal(idle(values,[timestamps[0],{...timestamps[1],value:[now,String(now-60)]}]),false);
assert.equal(idle([values[0],{...values[1],value:[now,'1']}],timestamps),false);
const response = payload => ({statusCode:200,body:{choices:[{message:{content:JSON.stringify(payload)}}]}});
const cases = ['  Leading  \n','Two Words\n','\n'].map(input=>({input,output:input}));
const validated = run('Verify new tests against reviewed specification',response({cases:[...cases,{input:'Oops\n',output:'Bad\n'}]}),{phase:'tests',data:{calls:1,source:'print(input())',contract:'echo',examples:[],faults:[['empty program','pass'],['strip whitespace','x'],['first word','x'],['lower','x'],['trim','x']]}});
assert.equal(validated.phase,'public');
assert.deepEqual(validated.data.cases,cases);
const verdict = (v, test_index) => ({statusCode:200,body:{verdict:v,test_index}});
const bad = run('Route private test verdict',verdict('wrong_answer',1),validated);
assert.equal(bad.phase,'repair');
assert.deepEqual(bad.data.failure.case,cases[0]);
const repaired = run('Validate repaired solution format',response({source:'print(input())'}),bad);
assert.equal(repaired.phase,'public');
assert.deepEqual(repaired.data.cases,cases);
let mutation = run('Route private test verdict',verdict('accepted'),repaired);
for (let i=0;i<5;i++) mutation = run('Count killed variants or request more coverage',verdict(i===1?'accepted':'wrong_answer'),mutation);
assert.equal(mutation.phase,'expand');
assert.equal(mutation.data.faultsKilled,4);
assert.deepEqual(mutation.data.survivors,['strip whitespace']);
assert.deepEqual(run('Validate repaired solution format',{statusCode:429},bad),{pause:true,reason:'http_429'});
console.log('Graph routing, admission and reducers passed');
for (const [contract,input,output] of [['sum','999999999999999999999999\n1\n','1000000000000000000000000\n'],['length',' а😀 \n','Слово  а😀  имеет длину 4\n'],['parity','-2\n','чётное\n'],['sign','-0.25\n','-\n']]) {
 const r=run('Verify new tests against reviewed specification',response({cases:[{input,output},{input,output:'wrong\n'}]}),{phase:'tests',data:{contract,cases:[],examples:[],calls:0}});
 assert.equal(r.data.cases.length,1,contract);
}
console.log('Reviewed queue oracles passed');
assert.deepEqual(run('Validate repaired solution format',{error:'socket timeout'},bad),{pause:true,reason:'transport'});
for (const [year,answer] of [['2000','Високосный'],['2100','Не високосный'],['2024','Високосный'],['2023','Не високосный']]) {
 const r=run('Verify new tests against reviewed specification',response({cases:[{input:year+'\n',output:answer+'\n'}]}),{phase:'tests',data:{contract:'leap',calls:0,cases:[],examples:[]}});
 assert.equal(r.data.cases.length,1,year);
}
assert(graph.nodes.find(n=>n.name==='Claim next queued task and load checkpoint').parameters.query.includes("'leap'"));
console.log('Leap-year oracle and transport timeout recovery passed');
for (const [contract,input,output] of [
 ['repeat4',' a \n',' a  a  a  a \n'],['python_exact','python\n','НЕТ\n'],['zen',' \n','НЕТ\n'],
 ['meow','скотина\n','МЯУ\n'],['yes_no','да\nнет\n','ВЕРНО\n'],['xmas','1\n2\n3\n','НЕ ГОРИ\n'],
 ['parrot',' a \nb\n\n',' a \nb\n\n'],['reverse',' a \nb\n\n','\nb\n a \n'],
 ['temperature','15.5\n','НОРМАЛЬНО\n'],['temperature','28\n','НОРМАЛЬНО\n'],['heights','9\n100\n9\n','100\n9\n9\n']
]) {
 const r=run('Verify new tests against reviewed specification',response({cases:[{input,output},{input,output:'wrong\n'}]}),{phase:'tests',data:{contract,calls:0,cases:[],examples:[]}});
 assert.equal(r.data.cases.length,1,contract);
}
console.log('Batch boundary oracles passed');
const existing = Array.from({length:12},(_,i)=>({input:`a${i}\nb\nc\n`,output:`c\nb\na${i}\n`}));
const targeted = {input:' left \n mid \n right \n',output:' right \n mid \n left \n'};
const expanded = run('Verify added cases and preserve existing tests',response({cases:[]}),{phase:'expand',data:{contract:'reverse',calls:3,cases:existing,examples:[],targetedCases:[targeted]}});
assert.equal(expanded.phase,'public');
assert.equal(expanded.data.cases.length,13);
assert.deepEqual(expanded.data.cases.slice(0,12),existing.slice(0,12));
const boundedRepair = run('Validate repaired solution format',response({source:'print(input())'}),{phase:'repair',data:{calls:13,callLimit:16,source:'pass',cases:[]}});
assert.equal(boundedRepair.phase,'public');
assert.equal(boundedRepair.data.calls,14);
console.log('Targeted expansion preserves full suites; explicit repair budget passed');
for (const [contract,input,output] of [['until_zero','-2\n1\n0\n9\n','-2\n1\n'],['until_nonmultiple','0\n-20\n4\n10\n','0\n-20\n'],['until_empty',' \na\n\nextra\n',' \na\n']]) {
 const r=run('Verify new tests against reviewed specification',response({cases:[{input,output},{input:'9\n',output:'9\n'}]}),{phase:'tests',data:{contract,calls:0,cases:[],examples:[]}});
 assert.deepEqual(r.data.cases,[{input,output}]);
}
for (const [contract,input,output] of [['xmas2','один\nдва\nтри\n','НЕ ГОРИ\n'],['xmas3','один\nдва\nтри\n','ГОРИ\n'],['xmas3','один\n2\n3\n','НЕ ГОРИ\n'],['xmas2','1\n2\n3\n','ГОРИ\n']]){
 const r=run('Verify new tests against reviewed specification',response({cases:[{input,output}]}),{phase:'tests',data:{contract,calls:0,cases:[],examples:[]}});assert.deepEqual(r.data.cases,[{input,output}]);
}
{
 const input='14\n16\n',output='14\nFizzBuzz\n16\n';
 const r=run('Verify new tests against reviewed specification',response({cases:[{input,output},{input:'4\n4\n',output:'4\n'}]}),{phase:'tests',data:{contract:'fizzbuzz',calls:0,cases:[],examples:[]}});assert.deepEqual(r.data.cases,[{input,output}]);
}
for(const [contract,input,output] of [['thank_count','спасибо.\n Спасибо. \nСпасибо.\n','3\n'],['mult_table','2\n','1 * 1 = 1\n1 * 2 = 2\n2 * 1 = 2\n2 * 2 = 4\n']]) {
 const r=run('Verify new tests against reviewed specification',response({cases:[{input,output}]}),{phase:'tests',data:{contract,calls:0,cases:[],examples:[]}});assert.deepEqual(r.data.cases,[{input,output}]);
}

assert.deepEqual(run('Verify new tests against reviewed specification',response({cases:[{input:"1\n"}]}),{phase:"tests",data:{contract:"mult_table",calls:0,cases:[],examples:[]}}).data.cases,[{input:"1\n",output:"1 * 1 = 1\n"}]);
assert.deepEqual(run('Verify new tests against reviewed specification',response({cases:[{input:'Спасибо.\n'},{input:'Спасибо\n'}]}),{phase:'tests',data:{contract:'thank_count',calls:0,cases:[],examples:[]}}).data.cases,[{input:'Спасибо.\n',output:'1\n'}]);
for (const [contract,input,output] of [['beautiful_digits','513\n','Вы ввели красивое число\n'],['beautiful_digits','124\n','Жаль, вы ввели обычное число\n'],['adjacent_sums','258\n','137\n']]){
 const r=run('Verify new tests against reviewed specification',response({cases:[{input,output}]}),{phase:'tests',data:{contract,calls:0,cases:[],examples:[]}});assert.deepEqual(r.data.cases,[{input,output}]);
}
{
 const args={phase:'tests',data:{contract:'noinput_reviewed',reviewedOutput:'234\n',calls:0,cases:[],examples:[]}};
 const r=run('Verify new tests against reviewed specification',response({cases:[{input:'0\n',output:'234\n'},{input:'',output:'233\n'},{input:'',output:'234\n'}]}),args);
 assert.equal(r.phase,'suite');assert.deepEqual(r.data.cases,[{input:'',output:'234\n'}]);
}
const diff={contract:'differential_v1',source:'print(input())',witness:'s=input();print(s)',examples:[{input:'x\n',output:'x\n'}],cases:[],faults:[],calls:1,variant:0};
assert.equal(run('Validate blind witness',response({source:'print(input())'}),{phase:'witness',data:{...diff}}).phase,'needs_review');
assert.equal(run('Require semantic approval',response({approved:false,reason:'ambiguous'}),{phase:'audit',data:{...diff}}).phase,'needs_review');
assert.equal(run('Check witness verdict wsuite',verdict('wrong_answer',1),{phase:'wsuite',data:{...diff}}).phase,'needs_review');
const faults=[['edge','source1'],['branch','source2'],['order','source3']];
assert.equal(run('Count killed variants or request more coverage',verdict('runtime_error',1),{phase:'mutate',data:{...diff,faults}}).phase,'needs_review');
assert.equal(run('Count killed variants or request more coverage',verdict('accepted'),{phase:'mutate',data:{...diff,faults}}).phase,'expand');
assert.equal(run('Count killed variants or request more coverage',verdict('wrong_answer',1),{phase:'mutate',data:{...diff,faults}}).phase,'plausible');
assert.equal(run('Reject crashes and always-wrong probes',verdict('wrong_answer',1),{phase:'plausible',data:{...diff,faults,variant:2,probeCase:0,probeRetries:2}}).phase,'needs_review');
assert.equal(run('Reject crashes and always-wrong probes',verdict('accepted'),{phase:'plausible',data:{...diff,faults,variant:2,probeCase:0,faultsKilled:2}}).phase,'certified');
const sandboxOnly = nodes.get('Resume sandbox-only checkpoint').parameters.query;
assert.match(sandboxOnly,/phase IN \('public','suite','mutate','plausible','wpublic','wsuite'\)/);
assert(!sandboxOnly.includes("'repair'"));
assert.deepEqual(graph.connections['Record busy or telemetry skip'].main[0].map(x=>x.node),['Resume sandbox-only checkpoint']);
{
 const submitted=[{input:'xy\n',output:'y\n'},{input:'\n',output:'\n'}];const feedback=response({approved:false,issue:'cases',badIndices:[1],reason:'empty word'});
 const r=run('Require semantic approval',feedback,{phase:'audit',data:{...diff,cases:submitted}});
 assert.equal(r.phase,'expand');assert.deepEqual(r.data.cases,submitted.slice(0,1));assert.deepEqual(r.data.quarantine,submitted.slice(1));
 assert.equal(run('Require semantic approval',feedback,{phase:'audit',data:{...diff,cases:submitted,semanticApproved:true}}).phase,'needs_review');
}
{
 const w=run('Validate blind witness',response({source:'s=input(); print(s)'}),{phase:'witness',data:{...diff}});assert.equal(w.phase,'wpublic');
 const bad=run('Check witness verdict wpublic',verdict('wrong_answer',1),{phase:'wpublic',data:{...diff}});assert.equal(bad.phase,'wrepair');
 assert.equal(run('Check witness verdict wpublic',verdict('accepted'),{phase:'wpublic',data:{...diff}}).phase,'tests');
 assert.equal(run('Check witness verdict wpublic',verdict('accepted'),{phase:'wpublic',data:{...diff,semanticApproved:true}}).phase,'wsuite');
}
