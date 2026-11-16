'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const {createConnection,MAX_ATTEMPTS}=require('../../charts/n8n/extensions/google-transport');
const records=['192.0.2.1','192.0.2.2','192.0.2.3','192.0.2.4','192.0.2.5'].map(address=>({address,family:4}));
const lookup=(h,o,cb)=>cb(null,records);const options={host:'www.googleapis.com',port:443,servername:'www.googleapis.com',_agentKey:'fixture',ca:'fixture-ca'};
function sock(){const s=new EventEmitter();s.destroyed=false;s.destroy=()=>{s.destroyed=true;};s.authorized=true;return s;}
function run(fn,opts=options){return new Promise((res,rej)=>{const v=fn(opts,(e,s)=>e?rej(e):res(s));assert.equal(v,undefined,'raw socket must not reach HTTP');});}
test('only verified socket is handed to HTTP; bad address fails over without application bytes',async()=>{
 const sockets=[],opts=[],reports=[];let delivered=0;const original=o=>{opts.push(o);const s=sock();sockets.push(s);if(sockets.length===2)setImmediate(()=>s.emit('secureConnect'));return s;};
 const fn=createConnection(original,lookup,r=>reports.push(r),{attemptMs:15,totalMs:200});const p=run(fn).then(s=>{delivered++;return s;});assert.equal(delivered,0);assert.equal(await p,sockets[1]);assert.equal(sockets[0].destroyed,true);assert.equal(opts[1].servername,options.host);assert.equal(opts[1].ca,options.ca);assert.equal(opts[1]._agentKey,options._agentKey);assert.equal(reports[0].attempts,2);assert.equal(delivered,1);
});
test('non-Google, deceptive suffix, explicit IPv6, wrong port and existing socket delegate untouched',()=>{
 const calls=[],native=(...a)=>{calls.push(a);return 'native';};const f=createConnection(native,()=>assert.fail());const cb=()=>{};
 for(const o of [{...options,host:'www.googleapis.com.evil'},{...options,host:'yandex.ru'},{...options,port:8443},{...options,family:6},{...options,socket:{}}]){assert.equal(f(o,cb),'native');assert.deepEqual(calls.at(-1),[o,cb]);}
});
test('TLS bypass or different SNI rejected without connection',async()=>{
 for(const o of [{...options,rejectUnauthorized:false},{...options,servername:'evil.invalid'}])await assert.rejects(run(createConnection(()=>assert.fail(),lookup),o),{code:'GOOGLE_TLS_POLICY_REJECTED'});
});
test('certificate rejection never retries even with more DNS addresses',async()=>{
 let n=0;const f=createConnection(()=>{n++;const s=sock();setImmediate(()=>s.emit('error',{code:'CERT_HAS_EXPIRED',message:'private secret'}));return s;},lookup);
 await assert.rejects(run(f),e=>e.code==='GOOGLE_TLS_REJECTED'&&!e.message.includes('private secret'));assert.equal(n,1);
});
test('unauthorized secureConnect fails closed',async()=>{
 const f=createConnection(()=>{const s=sock();s.authorized=false;setImmediate(()=>s.emit('secureConnect'));return s;},lookup);await assert.rejects(run(f),{code:'GOOGLE_TLS_REJECTED'});
});
test('at most four fresh-DNS candidates, all failed sockets destroyed',async()=>{
 const sockets=[];const f=createConnection(()=>{const s=sock();sockets.push(s);return s;},lookup,()=>{},{attemptMs:5,totalMs:200});await assert.rejects(run(f),{code:'GOOGLE_CONNECT_EXHAUSTED'});assert.equal(sockets.length,MAX_ATTEMPTS);assert.ok(sockets.every(s=>s.destroyed));
});
test('whole deadline covers DNS; late answer cannot start connection',async()=>{
 let release;const f=createConnection(()=>assert.fail(),(h,o,c)=>release=c,()=>{},{totalMs:10});await assert.rejects(run(f),{code:'GOOGLE_CONNECT_DEADLINE'});release(null,records);
});
test('successful TLS socket subsequent HTTP/POST failure is not retried',async()=>{
 let n=0;const f=createConnection(()=>{n++;const s=sock();setImmediate(()=>s.emit('secureConnect'));return s;},lookup);const s=await run(f);s.on('error',()=>{});s.emit('error',{code:'ECONNRESET'});await new Promise(r=>setImmediate(r));assert.equal(n,1);
});
test('empty DNS fails; private DNS error sanitized',async()=>{
 for(const fn of [(h,o,c)=>c(null,[]),(h,o,c)=>c(new Error('private token'))])await assert.rejects(run(createConnection(()=>assert.fail(),fn)),e=>['GOOGLE_CONNECT_EXHAUSTED','GOOGLE_DNS_FAILED'].includes(e.code)&&!e.message.includes('token'));
});
test('late secure/error after attempt expiry cannot deliver twice',async()=>{
 const ss=[];let callbacks=0;const f=createConnection(()=>{const s=sock();ss.push(s);if(ss.length===2)setImmediate(()=>s.emit('secureConnect'));return s;},lookup,()=>{},{attemptMs:10,totalMs:100});await new Promise((r,j)=>f(options,(e,s)=>{callbacks++;e?j(e):r(s);}));ss[0].emit('secureConnect');ss[0].emit('error',{code:'ECONNRESET'});assert.equal(callbacks,1);
});
test('real native HTTPS: stalled handshake -> verified next socket -> one lost POST, never replayed',async t=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),https=require('node:https');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'google-transport-test-'));fs.chmodSync(dir,0o700);t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 cp.execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-keyout',dir+'/key','-out',dir+'/cert','-days','1','-subj','/CN=www.googleapis.com','-addext','subjectAltName=DNS:www.googleapis.com'],{stdio:'ignore'});
 const sockets=new Set();let requests=0,connections=0;const good=https.createServer({key:fs.readFileSync(dir+'/key'),cert:fs.readFileSync(dir+'/cert')},(req,res)=>{requests++;req.resume();req.on('end',()=>req.socket.destroy());});const stall=net.createServer(s=>{sockets.add(s);s.on('close',()=>sockets.delete(s));});
 await Promise.all([new Promise(r=>good.listen(0,'127.0.0.1',r)),new Promise(r=>stall.listen(0,'127.0.0.1',r))]);t.after(()=>{for(const s of sockets)s.destroy();stall.close();good.close();});
 const original=https.Agent.prototype.createConnection;const agent=new https.Agent({ca:fs.readFileSync(dir+'/cert')});agent.createConnection=createConnection(function(o){connections++;return original.call(this,{...o,host:'127.0.0.1',port:connections===1?stall.address().port:good.address().port});},lookup,()=>{},{attemptMs:40,totalMs:1000});
 await assert.rejects(new Promise((resolve,reject)=>{const req=https.request('https://www.googleapis.com/',{method:'POST',agent},resolve);req.on('error',reject);req.end('fixture-only');}),{code:'ECONNRESET'});
 assert.equal(connections,2);assert.equal(requests,1);agent.destroy();
});
