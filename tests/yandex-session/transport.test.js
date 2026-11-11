'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),https=require('node:https'),{EventEmitter}=require('node:events');
const {makeLookup,transport}=require('../../charts/n8n/extensions/yandex-transport');
const {operation}=require('../../charts/n8n/extensions/yandex-client');
function lookup(fn,all=false){return new Promise((resolve,reject)=>fn('yandex.ru',{all},(e,...value)=>e?reject(e):resolve(value)));}
test('lookup queries the exact A name and honors Node all shape',async()=>{
 const calls=[];const fn=makeLookup({resolve4:async host=>{calls.push(host);return ['77.88.55.88','5.255.255.77'];}});
 assert.deepEqual(await lookup(fn),['77.88.55.88',4]);assert.deepEqual(await lookup(fn,true),[[{address:'77.88.55.88',family:4},{address:'5.255.255.77',family:4}]]);assert.deepEqual(calls,['yandex.ru','yandex.ru']);
});
test('empty or malformed DNS answers fail, no invented fallback IP',async()=>{
 for(const answer of [[],['::1'],['not-an-ip']])await assert.rejects(lookup(makeLookup({resolve4:async()=>answer})),{code:'ENODATA'});
});
test('DNS failure surfaces once and does not invoke another HTTP request',async()=>{
 let calls=0;const e=Object.assign(new Error('private diagnostic'),{code:'ETIMEOUT'});
 await assert.rejects(lookup(makeLookup({resolve4:async()=>{calls++;throw e;}})),{code:'ETIMEOUT'});assert.equal(calls,1);
});
test('native HTTPS preserves TLS verification, cookies, redirect response and body',async t=>{
 let calls=0,body;
 t.mock.method(https,'request',(url,opts,callback)=>{
  calls++;assert.equal(url.hostname,'yandex.ru');assert.equal(opts.method,'POST');assert.equal(opts.headers.Cookie,'test-cookie');assert.notEqual(opts.agent.options.rejectUnauthorized,false);assert.equal(opts.agent.options.family,4);assert.equal(typeof opts.agent.options.lookup,'function');
  const request=new EventEmitter();request.end=value=>{body=value;queueMicrotask(()=>{const r=new EventEmitter();r.statusCode=302;r.rawHeaders=['Set-Cookie','a=1; Secure','Set-Cookie','b=2; Secure','Location','https://passport.yandex.ru/'];callback(r);r.emit('data',Buffer.from('ok'));r.emit('end');});};return request;
 });
 const r=await transport('https://yandex.ru/',{method:'POST',headers:{Cookie:'test-cookie'},body:'test-body'});assert.equal(r.status,302);assert.equal(await r.text(),'ok');assert.equal(r.headers.getSetCookie().length,2);assert.equal(calls,1);assert.equal(body,'test-body');
});
test('connection loss performs one request, never retries a POST',async t=>{
 let calls=0;t.mock.method(https,'request',()=>{calls++;const r=new EventEmitter();r.end=()=>queueMicrotask(()=>r.emit('error',Object.assign(new Error('private'),{code:'ECONNRESET'})));return r;});
 await assert.rejects(transport('https://iot.quasar.yandex.ru/actions',{method:'POST'}),{code:'ECONNRESET'});assert.equal(calls,1);
});
test('network diagnostic identifies fixed phase without raw exception/token',async()=>{
 await assert.rejects(operation({xToken:'fixture-private-token',deviceId:'test',scenarioId:'test'},{check:true,transport:async()=>{throw Object.assign(new Error('fixture-private-token Cookie secret'),{code:'EAI_AGAIN'});}}),e=>e.code==='NETWORK_OR_TIMEOUT'&&e.phase==='X_TOKEN'&&e.transportCode==='EAI_AGAIN'&&!e.message.includes('fixture-private-token'));
});
test('compressed upstream response is decoded within the existing size guard',async t=>{
 const {PassThrough}=require('node:stream'),zlib=require('node:zlib');
 t.mock.method(https,'request',(url,opts,callback)=>{
  assert.equal(opts.headers['Content-Length'],'3');const r=new EventEmitter();r.end=()=>queueMicrotask(()=>{const response=new PassThrough();response.statusCode=200;response.headers={'content-encoding':'gzip'};response.rawHeaders=['Content-Encoding','gzip'];callback(response);response.end(zlib.gzipSync(Buffer.from('{"status":"ok"}')));});return r;
 });
 const r=await transport('https://yandex.ru/',{method:'POST',body:'abc'});assert.deepEqual(await r.json(),{status:'ok'});
});
