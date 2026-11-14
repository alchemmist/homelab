'use strict';
// DNS-only compatibility seam for native Google Calendar/OAuth HTTP clients.
// No HTTP interception/retry, alternate DNS server, IP pin or TLS modification.
const dns=require('node:dns'),net=require('node:net');
const HOSTS=new Set(['www.googleapis.com','oauth2.googleapis.com']);
const DEADLINE_MS=2500;
function createLookup(original=dns.lookup.bind(dns),makeResolver=()=>new dns.promises.Resolver({timeout:750,tries:2}),report=()=>{}){
 const pending=new Map();
 function resolve(host){
  if(pending.has(host))return pending.get(host);
  const work=new Promise((resolve,reject)=>{
   let resolver,timer,done=false;
   function finish(error,addresses){
    if(done)return;done=true;clearTimeout(timer);
    if(error){
     const code=['ENOTFOUND','ENODATA'].includes(error.code)?'ENOTFOUND':'EAI_AGAIN';
     report({event:'google_dns_failed',host,code,phase:'resolve_a'});
     const safe=Object.assign(new Error('Google DNS resolution failed'),{code,syscall:'getaddrinfo',hostname:host});reject(safe);
    }else resolve(addresses);
   }
   try{
    resolver=makeResolver();
    timer=setTimeout(()=>{finish({code:'ETIMEOUT'});resolver.cancel();},DEADLINE_MS);
    // c-ares resolve4 sends the exact name; no libc search/A+AAAA expansion.
    Promise.resolve(resolver.resolve4(host)).then(addresses=>{
     if(!Array.isArray(addresses)||!addresses.length||addresses.length>64||addresses.some(a=>typeof a!=='string'||!net.isIPv4(a)))return finish({code:'ENODATA'});
     finish(null,[...new Set(addresses)]);
    },error=>finish(error));
   }catch(error){finish(error);}
  });
  pending.set(host,work);work.then(()=>pending.delete(host),()=>pending.delete(host));return work;
 }
 return function lookup(hostname,options,callback){
  const args=arguments;
  if(typeof options==='function'){callback=options;options={};}
  const opts=typeof options==='number'?{family:options}:options||{};
  const family=opts.family||0;
  if((options!==undefined&&options!==null&&typeof options!=='object'&&typeof options!=='number'&&typeof options!=='function')||typeof hostname!=='string'||!HOSTS.has(hostname.toLowerCase().replace(/\.$/,''))||typeof callback!=='function'||![0,4,'IPv4'].includes(family))return original(...args);
  const host=hostname.toLowerCase().replace(/\.$/,'');
  resolve(host).then(addresses=>{
   if(opts.all)callback(null,addresses.map(address=>({address,family:4})));
   else callback(null,addresses[0],4);
  },error=>callback(error));
 };
}
module.exports={createLookup,HOSTS,DEADLINE_MS};
