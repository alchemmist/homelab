'use strict';
// Subscription adapter only; all VPN transport/crypto is official Xray-core.
const fs=require('node:fs');
const ENDPOINT='91.189.82.238',PORT=32053;
function prepareSubscription(value){
 const profiles=Array.isArray(value)?value:[value];
 const candidates=profiles.flatMap(p=>p&&Array.isArray(p.outbounds)?p.outbounds:[]).filter(o=>o.protocol==='vless');
 if(candidates.length!==1)throw Error('PROFILE_COUNT');
 const outbound=structuredClone(candidates[0]),s=outbound.settings||{},endpoint=s.vnext?.[0]||s;
 if(endpoint.address!==ENDPOINT||endpoint.port!==PORT||outbound.streamSettings?.security!=='reality')throw Error('PROFILE_POLICY');
 function check(v){if(!v||typeof v!=='object')return;for(const[k,x]of Object.entries(v)){if(k==='allowInsecure'&&x!==false)throw Error('TLS_POLICY');check(x);}}
 check(outbound);
 if(typeof outbound.streamSettings.realitySettings?.publicKey!=='string')throw Error('REALITY_IDENTITY');
 outbound.tag='service-vpn';
 return {log:{loglevel:'none'},inbounds:[
  {tag:'google-api',listen:'127.0.0.1',port:18443,protocol:'dokodemo-door',settings:{address:'www.googleapis.com',port:443,network:'tcp'}},
  {tag:'google-oauth',listen:'127.0.0.1',port:18444,protocol:'dokodemo-door',settings:{address:'oauth2.googleapis.com',port:443,network:'tcp'}}
 ],outbounds:[outbound]};
}
async function main(){
 const url=new URL(fs.readFileSync('/vpn-identity/subscription-url','utf8').trim());
 if(url.protocol!=='https:'||url.hostname!=='vpn.alchemmist.xyz'||url.port||url.username||url.password||url.search||url.hash)throw Error('SUBSCRIPTION_POLICY');
 const response=await fetch(url,{redirect:'error',signal:AbortSignal.timeout(8000)});
 if(!response.ok)throw Error('SUBSCRIPTION_HTTP');
 const reader=response.body.getReader();const chunks=[];let length=0;
 for(;;){const{done,value}=await reader.read();if(done)break;length+=value.length;if(length>262144){await reader.cancel();throw Error('SUBSCRIPTION_SIZE');}chunks.push(Buffer.from(value));}
 const config=prepareSubscription(JSON.parse(Buffer.concat(chunks).toString('utf8')));
 fs.writeFileSync('/vpn-runtime/client.json.tmp',JSON.stringify(config),{mode:0o600});
 fs.renameSync('/vpn-runtime/client.json.tmp','/vpn-runtime/client.json');
 console.log('VPN_SUBSCRIPTION_PREPARED');
}
if(require.main===module)main().catch(()=>{console.error('VPN_SUBSCRIPTION_PREPARE_FAILED');process.exitCode=1;});
module.exports={prepareSubscription};
