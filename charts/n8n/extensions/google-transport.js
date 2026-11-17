'use strict';
// Race only connection establishment. HTTP receives exactly one verified socket.
// No request/response/body/credential or OAuth POST can be replayed here.
const https=require('node:https');
const {createLookup,HOSTS}=require('./google-dns');
const ATTEMPT_MS=2000, TOTAL_MS=9500, MAX_ATTEMPTS=8, MAX_PARALLEL=2, HEDGE_MS=250;
const TRANSIENT=new Set(['ETIMEDOUT','ECONNRESET','ECONNREFUSED','EHOSTUNREACH','ENETUNREACH','EPIPE','ERR_TLS_HANDSHAKE_TIMEOUT']);
function safeError(code){return Object.assign(new Error('Google TLS connection could not be established'),{code});}
function createConnection(original,lookup=createLookup(),report=()=>{},limits={}){
 const attemptMs=limits.attemptMs??ATTEMPT_MS,totalMs=limits.totalMs??TOTAL_MS,hedgeMs=limits.hedgeMs??HEDGE_MS;
 return function(options,callback){
  const args=arguments,host=typeof options?.host==='string'?options.host.toLowerCase().replace(/\.$/,''):'';
  if(!HOSTS.has(host)||Number(options.port??443)!==443||typeof callback!=='function'||options.socket||options.path||options.family===6||options.family==='IPv6')return original.apply(this,args);
  if(options.rejectUnauthorized===false||(options.servername&&options.servername.toLowerCase().replace(/\.$/,'')!==host)){
   queueMicrotask(()=>callback(safeError('GOOGLE_TLS_POLICY_REJECTED')));return undefined;
  }
  let finished=false,totalTimer,hedgeTimer,attempts=0,index=0,addresses=[],handshakeTimeouts=0;
  const agent=this,active=new Set();
  function retire(entry,destroy=true){
   clearTimeout(entry.timer);active.delete(entry);
   entry.socket?.removeListener('secureConnect',entry.ready);entry.socket?.removeListener('error',entry.failed);
   if(destroy&&entry.socket){entry.socket.on('error',()=>{});entry.socket.destroy();}
  }
  function finish(error,winner){
   if(finished)return;finished=true;clearTimeout(totalTimer);clearTimeout(hedgeTimer);
   for(const entry of active)retire(entry,entry.socket!==winner);
   const record={host,attempts,handshakeTimeouts,candidates:addresses.length};
   if(error){report({event:'google_connect_failed',...record,code:error.code});callback(error);}
   else{if(attempts>1)report({event:'google_connect_failover',...record,code:'CONNECTED'});callback(null,winner);}
  }
  function launch(){
   if(finished)return;
   if(index>=addresses.length||attempts>=MAX_ATTEMPTS){if(!active.size)finish(safeError('GOOGLE_CONNECT_EXHAUSTED'));return;}
   if(active.size>=MAX_PARALLEL)return;
   attempts++;const address=addresses[index++],entry={};active.add(entry);
   entry.failed=error=>{
    if(finished||!active.has(entry))return;
    retire(entry);
    if(error?.code==='ETIMEDOUT')handshakeTimeouts++;
    if(TRANSIENT.has(error?.code))launch();else finish(safeError('GOOGLE_TLS_REJECTED'));
   };
   entry.ready=()=>{
    if(finished||!active.has(entry))return;
    if(!entry.socket.authorized)return finish(safeError('GOOGLE_TLS_REJECTED'));
    finish(null,entry.socket);
   };
   try{
    // Native CA/session/cipher checks retained; verify the original hostname,
    // not the selected ephemeral DNS address. No fixed address/blacklist.
    entry.socket=original.call(agent,{...options,host:address,hostname:address,servername:host,family:4});
    entry.socket.once('secureConnect',entry.ready);entry.socket.once('error',entry.failed);
    entry.timer=setTimeout(()=>entry.failed({code:'ETIMEDOUT'}),attemptMs);
   }catch(error){entry.failed(error);}
  }
  totalTimer=setTimeout(()=>finish(safeError('GOOGLE_CONNECT_DEADLINE')),totalMs);
  lookup(host,{all:true,family:4},(error,records)=>{
   if(finished)return;
   if(error)return finish(safeError('GOOGLE_DNS_FAILED'));
   addresses=[...new Set(records.filter(r=>r.family===4).map(r=>r.address))].slice(0,MAX_ATTEMPTS);
   // Healthy first handshakes normally finish before the second starts.
   // If slow, keep at most two pre-HTTP sockets to cover more DNS candidates
   // within the SAME absolute budget. All losing sockets are destroyed.
   hedgeTimer=setTimeout(launch,hedgeMs);launch();
  });
  return undefined;
 };
}
function install(report){
 const original=https.Agent.prototype.createConnection;
 https.Agent.prototype.createConnection=createConnection(original,undefined,report);
 return ()=>{https.Agent.prototype.createConnection=original;};
}
module.exports={createConnection,install,ATTEMPT_MS,TOTAL_MS,MAX_ATTEMPTS,MAX_PARALLEL,HEDGE_MS};
