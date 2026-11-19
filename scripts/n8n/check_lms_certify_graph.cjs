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
const prom = result => ({statusCode:200,body:{status:'success',data:{result}}});
const values = ['running','waiting'].map(m => ({metric:{__name__:`vllm:num_requests_${m}`, instance:'a'},value:[now,'0']}));
const timestamps = ['running','waiting'].map(m => ({metric:{queue_metric:m,instance:'a'},value:[now,String(now)]}));
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
assert.deepEqual(run('Validate repaired solution format',{statusCode:429},bad),{pause:true});
console.log('Graph routing, admission and reducers passed');
for (const [contract,input,output] of [['sum','999999999999999999999999\n1\n','1000000000000000000000000\n'],['length',' а😀 \n','Слово  а😀  имеет длину 4\n'],['parity','-2\n','чётное\n'],['sign','-0.25\n','-\n']]) {
 const r=run('Verify new tests against reviewed specification',response({cases:[{input,output},{input,output:'wrong\n'}]}),{phase:'tests',data:{contract,cases:[],examples:[],calls:0}});
 assert.equal(r.data.cases.length,1,contract);
}
console.log('Reviewed queue oracles passed');
assert.deepEqual(run('Validate repaired solution format',{error:'socket timeout'},bad),{pause:true});
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
