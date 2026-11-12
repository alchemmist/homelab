'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),http=require('node:http');
const {createLookup,HOSTS,DEADLINE_MS}=require('../../charts/n8n/extensions/google-dns');
const run=(fn,host='www.googleapis.com',opts={})=>new Promise((resolve,reject)=>fn(host,opts,(e,...v)=>e?reject(e):resolve(v)));
test('exact A query, no search suffix or AAAA, Node scalar/all callback shapes',async()=>{
 const queries=[];const lookup=createLookup(()=>assert.fail('libc used'),()=>({resolve4:async h=>{queries.push(h);return ['192.0.2.1','192.0.2.2'];}}));
 assert.deepEqual(await run(lookup),['192.0.2.1',4]);assert.deepEqual(await run(lookup,'OAUTH2.GOOGLEAPIS.COM.',{all:true}),[[{address:'192.0.2.1',family:4},{address:'192.0.2.2',family:4}]]);assert.deepEqual(queries,['www.googleapis.com','oauth2.googleapis.com']);
});
test('non-Google, deceptive suffix, literal IP, explicit IPv6 delegate arguments unchanged',()=>{
 const calls=[];const orig=(...args)=>calls.push(args);const lookup=createLookup(orig,()=>assert.fail('scoped resolver used'));const cb=()=>{};
 for(const h of ['googleapis.com','www.googleapis.com.attacker.invalid','example.org','10.43.194.185','localhost','yandex.ru']){lookup(h,{all:true},cb);assert.deepEqual(calls.at(-1),[h,{all:true},cb]);}
 lookup('www.googleapis.com',{family:6},cb);assert.deepEqual(calls.at(-1),['www.googleapis.com',{family:6},cb]);assert.equal(HOSTS.size,2);
});
test('callback-only and numeric family overloads',async()=>{
 const lookup=createLookup(()=>assert.fail(),()=>({resolve4:async()=>['192.0.2.1']}));
 assert.deepEqual(await new Promise((res,rej)=>lookup('www.googleapis.com',(e,...v)=>e?rej(e):res(v))),['192.0.2.1',4]);assert.deepEqual(await run(lookup,'www.googleapis.com',4),['192.0.2.1',4]);
});
test('concurrent lookups share in-flight resolution, not a stale persistent cache',async()=>{
 let calls=0,release;const lookup=createLookup(()=>assert.fail(),()=>({resolve4:()=>{calls++;return new Promise(r=>release=r);}}));
 const first=run(lookup),second=run(lookup);assert.equal(calls,1);release(['192.0.2.1']);await Promise.all([first,second]);
 const third=run(lookup);assert.equal(calls,2);release(['192.0.2.2']);assert.deepEqual(await third,['192.0.2.2',4]);
});
test('empty, malformed, oversized, IPv6-only DNS answers fail closed',async()=>{
 for(const a of [[],['::1'],['bad'],null,Array(65).fill('192.0.2.1')])await assert.rejects(run(createLookup(()=>assert.fail(),()=>({resolve4:async()=>a}))),{code:'ENOTFOUND'});
});
test('DNS failure is safe, no raw message, alternate resolver or libc fallback',async()=>{
 const records=[];const lookup=createLookup(()=>assert.fail('fallback'),()=>({resolve4:async()=>{throw Object.assign(new Error('private-cookie-token'),{code:'ETIMEOUT'});}}),r=>records.push(r));
 await assert.rejects(run(lookup),e=>e.code==='EAI_AGAIN'&&!e.message.includes('private-cookie-token'));assert.deepEqual(records,[{event:'google_dns_failed',host:'www.googleapis.com',code:'EAI_AGAIN',phase:'resolve_a'}]);
});
test('bounded resolution cancels once and late response cannot call callback twice',async()=>{
 let release,cancelled=0,callbacks=0;const lookup=createLookup(()=>assert.fail(),()=>({resolve4:()=>new Promise(r=>release=r),cancel:()=>cancelled++}));const t=Date.now();
 await new Promise(resolve=>lookup('www.googleapis.com',{},e=>{callbacks++;assert.equal(e.code,'EAI_AGAIN');resolve();}));
 assert.ok(Date.now()-t>=DEADLINE_MS-20);assert.equal(cancelled,1);release(['192.0.2.1']);await new Promise(r=>setImmediate(r));assert.equal(callbacks,1);
});
test('native HTTP request uses lookup once; lost POST is never replayed',async t=>{
 let requests=0;const server=http.createServer((req,res)=>{requests++;req.socket.destroy();});await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>server.close());
 const lookup=createLookup(()=>assert.fail(),()=>({resolve4:async()=>['127.0.0.1']}));
 await assert.rejects(new Promise((resolve,reject)=>{const r=http.request({hostname:'www.googleapis.com',port:server.address().port,method:'POST',lookup},resolve);r.on('error',reject);r.end('fixture');}));assert.equal(requests,1);
});
test('deployment preload is DNS-only; TLS and HTTP are untouched',()=>{
 const fs=require('node:fs'),path=require('node:path');const p=fs.readFileSync(path.join(__dirname,'../../charts/n8n/extensions/google-dns-preload.js'),'utf8');assert.match(p,/dns.lookup=createLookup/);assert.doesNotMatch(p,/rejectUnauthorized|NODE_TLS_REJECT_UNAUTHORIZED|https\.request|setServers|setDefaultResultOrder/);
});
