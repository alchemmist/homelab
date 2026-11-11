'use strict';
// Yandex only. c-ares A resolution avoids slow libc A/AAAA/search expansion.
// Retries belong to DNS BEFORE a socket/request exists, never to HTTP/actions.
const https=require('node:https'),dns=require('node:dns'),net=require('node:net'),zlib=require('node:zlib');
function makeLookup(resolver=new dns.promises.Resolver({timeout:750,tries:2})){
 return (hostname,options,callback)=>{
  resolver.resolve4(hostname).then(addresses=>{
   if(!addresses.length||addresses.some(x=>!net.isIPv4(x))){const e=new Error('DNS_UNAVAILABLE');e.code='ENODATA';return callback(e);}
   if(options?.all)callback(null,addresses.map(address=>({address,family:4})));
   else callback(null,addresses[0],4);
  },e=>callback(e));
 };
}
const agent=new https.Agent({keepAlive:true,maxSockets:2,maxFreeSockets:1,family:4,lookup:makeLookup()});
function transport(url,options={}){
 const u=new URL(url);
 if(u.protocol!=='https:'||u.username||u.password)throw new Error('UNSAFE_AUTH_ENDPOINT');
 return new Promise((resolve,reject)=>{
  const headers={'Accept':'*/*','Accept-Encoding':'identity','User-Agent':'node',...options.headers};
  if(options.body!==undefined)headers['Content-Length']=String(Buffer.byteLength(options.body));
  const request=https.request(u,{method:options.method||'GET',headers,signal:options.signal,agent},response=>{
   const chunks=[];let size=0;
   const encoding=String(response.headers?.['content-encoding']||'identity').toLowerCase();
   const decoder={gzip:zlib.createGunzip,deflate:zlib.createInflate,br:zlib.createBrotliDecompress}[encoding];
   const stream=decoder?response.pipe(decoder()):response;
   stream.on('data',chunk=>{size+=chunk.length;if(size>5000000){const e=new Error('RESPONSE_TOO_LARGE');e.code='RESPONSE_TOO_LARGE';stream.destroy(e);response.destroy(e);request.destroy(e);}else chunks.push(chunk);});
   response.on('error',reject);
   if(stream!==response)stream.on('error',reject);
   stream.on('end',()=>{
    try{
     const headers=new Headers();for(let i=0;i<response.rawHeaders.length;i+=2)headers.append(response.rawHeaders[i],response.rawHeaders[i+1]);
     const status=response.statusCode;
     resolve(new Response([204,205,304].includes(status)?null:Buffer.concat(chunks),{status,headers}));
    }catch(e){reject(e);}
   });
  });
  request.on('error',reject);
  request.end(options.body);
 });
}
module.exports={transport,makeLookup};
