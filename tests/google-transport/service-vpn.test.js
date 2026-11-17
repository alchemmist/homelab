'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const{prepareSubscription}=require('../../charts/n8n/service-vpn/prepare');
function profile(){return {inbounds:[{listen:'0.0.0.0',port:1080}],routing:{rules:[{outboundTag:'direct'}]},outbounds:[{tag:'proxy',protocol:'vless',settings:{address:'91.189.82.238',port:32053,id:'00000000-0000-4000-8000-000000000001'},streamSettings:{network:'xhttp',security:'reality',realitySettings:{publicKey:'fixture-public-key',serverName:'example.com'}}},{protocol:'freedom',tag:'direct'}]};}
test('imports native subscription credentials/Reality unchanged but only two private Google listeners',()=>{
 const p=profile(),before=structuredClone(p),out=prepareSubscription(p);assert.deepEqual(p,before);assert.equal(out.outbounds.length,1);assert.equal(out.outbounds[0].protocol,'vless');assert.deepEqual(out.outbounds[0].settings,p.outbounds[0].settings);assert.deepEqual(out.outbounds[0].streamSettings,p.outbounds[0].streamSettings);assert.ok(out.inbounds.every(x=>x.listen==='127.0.0.1'&&x.protocol==='dokodemo-door'));assert.deepEqual(out.inbounds.map(x=>x.settings.address),['www.googleapis.com','oauth2.googleapis.com']);assert.equal(out.routing,undefined);
});
test('no guessed profile or direct fallback on missing/ambiguous/wrong/insecure subscription',()=>{
 for(const change of [p=>p.outbounds=[],p=>p.outbounds.push(p.outbounds[0]),p=>p.outbounds[0].settings.address='109.120.141.60',p=>p.outbounds[0].settings.port=443,p=>p.outbounds[0].streamSettings.security='none',p=>p.outbounds[0].streamSettings.realitySettings.allowInsecure=true]){const p=profile();change(p);assert.throws(()=>prepareSubscription(p));}
});
test('native array profile accepted; foreign routing/listeners never trusted',()=>{const out=prepareSubscription([profile()]);assert.equal(out.inbounds.length,2);assert.equal(out.log.loglevel,'none');});
