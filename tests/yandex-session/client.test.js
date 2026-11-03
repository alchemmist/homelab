'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {operation,CookieJar}=require('../../charts/n8n/extensions/yandex-client');
let count=0;
function fixture(config={}){
 const calls=[],credentials={xToken:'test-token-'+(++count),deviceId:'test-device',scenarioId:'test-scenario'};let puts=0;
 const transport=async(url,opts)=>{
  const u=new URL(url);calls.push({url,opts});
  if(u.hostname==='mobileproxy.passport.yandex.net')return Response.json(config.reject?{status:'error',sensitive:'never-display'}:{status:'ok',passport_host:'https://passport.yandex.ru',track_id:'test-track'});
  if(u.pathname==='/auth/session/')return new Response('',{status:302,headers:{'set-cookie':'Session_id=test-session; Domain=.yandex.ru; Path=/; Secure'}});
  if(u.search==='?storage=1')return Response.json({storage:{user:{uid:'test-user'}}});
  if(u.pathname==='/iot')return new Response('"csrfToken2":"test-csrf"');
  if(opts.method==='PUT'){puts++;if(config.forbidden&&puts===1)return Response.json({status:'error'},{status:403});return Response.json({status:'ok'});}
  if(u.pathname.endsWith('/actions')){if(config.lost)throw new Error('sensitive transport detail');return Response.json({status:'ok'});}
  throw new Error('Unexpected test request');
 };
 return {calls,credentials,transport};
}
test('fresh check authenticates then validates PUT without sound',async()=>{
 const f=fixture();const r=await operation(f.credentials,{check:true,forceRefresh:true,transport:f.transport});assert.equal(r.status,'ok');assert.equal(r.sessionRefreshed,true);assert.equal(f.calls.length,5);assert(!f.calls.some(c=>new URL(c.url).pathname.endsWith('/actions')));assert(!JSON.stringify(r).includes('test-token'));
 const put=f.calls.at(-1);assert.match(put.opts.headers.Cookie,/Session_id=test-session/);assert.equal(put.opts.headers['x-csrf-token'],'test-csrf');
});
test('403 on preparation automatically renews exactly once',async()=>{
 const f=fixture({forbidden:true});await operation(f.credentials,{text:'Meeting',transport:f.transport});assert.equal(f.calls.filter(c=>new URL(c.url).hostname==='mobileproxy.passport.yandex.net').length,2);assert.equal(f.calls.filter(c=>c.opts.method==='PUT').length,2);assert.equal(f.calls.filter(c=>new URL(c.url).pathname.endsWith('/actions')).length,1);
});
test('revoked x-token fails with sanitized code',async()=>{
 const f=fixture({reject:true});await assert.rejects(operation(f.credentials,{check:true,transport:f.transport}),e=>e.message==='X_TOKEN_REJECTED'&&!e.message.includes('sensitive'));assert.equal(f.calls.length,1);
});
test('lost execution response is not retried',async()=>{
 const f=fixture({lost:true});await assert.rejects(operation(f.credentials,{text:'Meeting',transport:f.transport}),/NETWORK_OR_TIMEOUT/);assert.equal(f.calls.filter(c=>new URL(c.url).pathname.endsWith('/actions')).length,1);
});
test('announcements serialize prepare and execute, and reuse fresh session',async()=>{
 const f=fixture();await Promise.all(['one','two'].map(text=>operation(f.credentials,{text,transport:f.transport})));
 const actual=f.calls.filter(c=>c.opts.method==='PUT'||new URL(c.url).pathname.endsWith('/actions'));
 assert.deepEqual(actual.map(c=>c.opts.method),['PUT','POST','PUT','POST']);
 assert.equal(JSON.parse(actual[0].opts.body).steps[0].parameters.items[0].value.capabilities[1].state.value.text,'one');assert.equal(JSON.parse(actual[2].opts.body).steps[0].parameters.items[0].value.capabilities[1].state.value.text,'two');assert.equal(f.calls.filter(c=>new URL(c.url).hostname==='mobileproxy.passport.yandex.net').length,1);
});
test('cancelled execution never performs requests',async()=>{
 const f=fixture();const controller=new AbortController();controller.abort();await assert.rejects(operation(f.credentials,{text:'Meeting',signal:controller.signal,transport:f.transport}),/CANCELLED/);assert.equal(f.calls.length,0);
});
test('cookie jar respects domain, path and expiration',()=>{
 const j=new CookieJar();j.accept('https://passport.yandex.ru/auth/session/',new Headers({'set-cookie':'Session_id=test; Domain=.yandex.ru; Path=/; Secure'}));assert.match(j.header('https://iot.quasar.yandex.ru/m/user'),/Session_id=test/);assert.equal(j.header('https://evil.test/'),'');j.accept('https://passport.yandex.ru/',new Headers({'set-cookie':'Session_id=gone; Domain=.yandex.ru; Path=/; Max-Age=0'}));assert.equal(j.header('https://iot.quasar.yandex.ru/'),'');
});
