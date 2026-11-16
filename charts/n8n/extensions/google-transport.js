'use strict';
// Only fail over a TCP/TLS connection BEFORE handing its socket to HTTP.
// No HTTP response, request, headers, body, credential or POST is replayed.
const https=require('node:https');
const {createLookup,HOSTS}=require('./google-dns');
const ATTEMPT_MS=2000, TOTAL_MS=9500, MAX_ATTEMPTS=4;
const TRANSIENT=new Set(['ETIMEDOUT','ECONNRESET','ECONNREFUSED','EHOSTUNREACH','ENETUNREACH','EPIPE','ERR_TLS_HANDSHAKE_TIMEOUT']);
function safeError(code){return Object.assign(new Error('Google TLS connection could not be established'),{code});}
function createConnection(original,lookup=createLookup(),report=()=>{},limits={}){
 const attemptMs=limits.attemptMs??ATTEMPT_MS,totalMs=limits.totalMs??TOTAL_MS;
 return function(options,callback){
  const args=arguments,host=typeof options?.host==='string'?options.host.toLowerCase().replace(/\.$/,''):'';
  if(!HOSTS.has(host)||Number(options.port??443)!==443||typeof callback!=='function'||options.socket||options.path||options.family===6||options.family==='IPv6')return original.apply(this,args);
  // A caller specifying another TLS identity must not silently be rewritten.
  if(options.rejectUnauthorized===false||(options.servername&&options.servername.toLowerCase().replace(/\.$/,'')!==host)){
   queueMicrotask(()=>callback(safeError('GOOGLE_TLS_POLICY_REJECTED')));return undefined;
  }
  let finished=false,socket,attemptTimer,totalTimer,attempts=0,index=0,addresses=[];
  const agent=this;
  function emit(event,code){report({event,host,code,attempts});}
  function cleanup(){clearTimeout(attemptTimer);clearTimeout(totalTimer);}
  function finish(error,value){
   if(finished){if(value)value.destroy();return;}finished=true;cleanup();
   if(error){if(socket)socket.destroy();emit('google_connect_failed',error.code);callback(error);}
   else{if(attempts>1)emit('google_connect_failover','CONNECTED');callback(null,value);}
  }
  totalTimer=setTimeout(()=>finish(safeError('GOOGLE_CONNECT_DEADLINE')),totalMs);
  function next(){
   if(finished)return;
   if(index>=addresses.length||attempts>=MAX_ATTEMPTS)return finish(safeError('GOOGLE_CONNECT_EXHAUSTED'));
   attempts++;const address=addresses[index++];let current,settled=false;
   function detach(){clearTimeout(attemptTimer);current?.removeListener('secureConnect',ready);current?.removeListener('error',failed);}
   function failed(error){
    if(settled||finished)return;settled=true;detach();
    // Retain a harmless error listener until close; no raw errors escape/log.
    if(current){current.on('error',()=>{});current.destroy();}
    if(TRANSIENT.has(error?.code))next();else finish(safeError('GOOGLE_TLS_REJECTED'));
   }
   function ready(){
    if(settled||finished)return;settled=true;detach();
    if(!current.authorized)return finish(safeError('GOOGLE_TLS_REJECTED'));
    finish(null,current);
   }
   try{
    // Preserve native CA/SNI/cipher/session/client-cert options; native TLS
    // still validates the ORIGINAL DNS hostname. No hard-coded address.
    current=original.call(agent,{...options,host:address,hostname:address,servername:host,family:4});
    socket=current;
    current.once('secureConnect',ready);current.once('error',failed);
    attemptTimer=setTimeout(()=>failed({code:'ETIMEDOUT'}),attemptMs);
   }catch(error){failed(error);}
  }
  lookup(host,{all:true,family:4},(error,records)=>{
   if(finished)return;
   if(error)return finish(safeError('GOOGLE_DNS_FAILED'));
   addresses=[...new Set(records.filter(r=>r.family===4).map(r=>r.address))];next();
  });
  // Critical: NEVER return the raw unverified socket. HTTP must not receive it
  // (and cannot queue/send application bytes) until verified secureConnect.
  return undefined;
 };
}
function install(report){
 const original=https.Agent.prototype.createConnection;
 https.Agent.prototype.createConnection=createConnection(original,undefined,report);
 return ()=>{https.Agent.prototype.createConnection=original;};
}
module.exports={createConnection,install,ATTEMPT_MS,TOTAL_MS,MAX_ATTEMPTS};
