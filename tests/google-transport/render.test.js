'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),cp=require('node:child_process'),path=require('node:path');
const chart=path.join(__dirname,'../../charts/n8n');const render=(...args)=>cp.execFileSync('helm',['template','n8n',chart,...args],{encoding:'utf8'});
test('disabled has no preload/module, enabled includes dependencies and exactly one NODE_OPTIONS',()=>{
 const off=render('--set','googleTransportEnabled=false');assert.doesNotMatch(off,/google-transport|google-dns|NODE_OPTIONS/);
 const on=render('--set','googleTransportEnabled=true');for(const n of ['google-dns.js:','google-transport.js:','google-transport-preload.js:'])assert.ok(on.includes(n));assert.match(on,/--require=\/opt\/n8n\/yandex-extension\/google-transport-preload.js/);assert.equal((on.match(/name: NODE_OPTIONS/g)||[]).length,1);
 const both=render('--set','googleTransportEnabled=true','--set','googleDnsEnabled=true');assert.equal((both.match(/name: NODE_OPTIONS/g)||[]).length,1);
});
