'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),cp=require('node:child_process'),path=require('node:path');
const chart=path.join(__dirname,'../../charts/n8n');const render=(...args)=>cp.execFileSync('helm',['template','n8n',chart,'--set','googleEgress.enabled=false',...args],{encoding:'utf8'});
test('disabled has no preload/module, enabled includes dependencies and exactly one NODE_OPTIONS',()=>{
 const off=render('--set','googleTransportEnabled=false');assert.doesNotMatch(off,/google-transport|google-dns|NODE_OPTIONS/);
 const on=render('--set','googleTransportEnabled=true');for(const n of ['google-dns.js:','google-transport.js:','google-transport-preload.js:'])assert.ok(on.includes(n));assert.match(on,/--require=\/opt\/n8n\/yandex-extension\/google-transport-preload.js/);assert.equal((on.match(/name: NODE_OPTIONS/g)||[]).length,1);
 const both=render('--set','googleTransportEnabled=true','--set','googleDnsEnabled=true');assert.equal((both.match(/name: NODE_OPTIONS/g)||[]).length,1);
});
test('Google egress uses static loopback-only forwards, dedicated secret, pinned SSH; disabled unchanged',()=>{
 const off=render('--set','googleEgress.enabled=false');assert.doesNotMatch(off,/name: google-egress|name: N8N_GOOGLE_SSH_EGRESS|secretName: n8n-google-egress/);
 const on=render('--set','googleEgress.enabled=true');for(const value of ['127.0.0.1:18443:www.googleapis.com:443','127.0.0.1:18444:oauth2.googleapis.com:443','StrictHostKeyChecking=yes','IdentitiesOnly=yes','secretName: n8n-google-egress','readOnlyRootFilesystem: true'])assert.ok(on.includes(value),value);
 assert.doesNotMatch(on,/venice-browser-egress|HTTPS_PROXY|hostNetwork: true|0.0.0.0:1844/);
 assert.throws(()=>render('--set','googleEgress.enabled=true','--set','googleTransportEnabled=false'));
});
