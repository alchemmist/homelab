'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const{SocratAlertWebhook}=require('../../charts/n8n/extensions/SocratAlertWebhook.node');
const ingress='fake-ingress-credential',worker='fake-worker-credential';
function context(authorization='Bearer '+ingress,requireAuth=true){
 const response={code:0,body:'',writeHead(c){this.code=c;},end(b){this.body=b;}};
 return{response,getCredentials:async k=>k==='socratAlertIngress'?{token:ingress}:{name:'X-Worker-Token',value:worker},
 getNodeParameter:()=>requireAuth,getRequestObject:()=>({headers:{authorization},body:{externalURL:'test',alerts:[{status:'firing',labels:{alertname:'Test',password:'hidden'},annotations:{summary:'Test '+ingress},startsAt:'2026-11-03T13:00:00Z'}]}}),getResponseObject:()=>response};
}
test('rejects unauthenticated requests without queue or workflow',async()=>{
 const c=context('');const r=await new SocratAlertWebhook().webhook(c);assert.equal(c.response.code,401);assert.equal(r.workflowData,undefined);
});
test('authenticated request is queued and auth never enters execution data',async()=>{
 const old=global.fetch;let payload;
 global.fetch=async(u,o)=>{payload=JSON.parse(o.body);assert.equal(o.headers['X-Worker-Token'],worker);return{ok:true,json:async()=>({accepted:1})};};
 try{const c=context(),r=await new SocratAlertWebhook().webhook(c);const output=JSON.stringify(r);assert(!output.includes(ingress));assert(!output.includes(worker));assert(!output.includes('headers'));assert.equal(payload.alerts[0].labels.password,'[REDACTED]');assert.equal(r.webhookResponse.status,'accepted');}finally{global.fetch=old;}
});
test('queue failure returns retryable 503 but still triggers Telegram',async()=>{
 const old=global.fetch;global.fetch=async()=>{throw new Error('test');};
 try{const c=context(),r=await new SocratAlertWebhook().webhook(c);assert.equal(c.response.code,503);assert(r.workflowData);assert(r.noWebhookResponse);assert.equal(r.workflowData[0][0].json.triageQueued,false);assert.match(r.workflowData[0][0].json.triageEvents[0].episode,/^[a-f0-9]{64}$/);}finally{global.fetch=old;}
});
test('legacy migration mode cannot enqueue unauthenticated incidents',async()=>{
 const old=global.fetch;global.fetch=async()=>{throw new Error('Must not call');};
 try{const r=await new SocratAlertWebhook().webhook(context('',false));assert.equal(r.webhookResponse.status,'legacy_telegram_only');assert(r.workflowData);}finally{global.fetch=old;}
});

test('supports the installed n8n custom-node bound-context calling convention',async()=>{
 const c=context('');const r=await new SocratAlertWebhook().webhook.call(c);assert.equal(c.response.code,401);assert.equal(r.workflowData,undefined);
});
