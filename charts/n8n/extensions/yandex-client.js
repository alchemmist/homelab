'use strict';
const {createHash}=require('crypto');
const sessions=new Map(), locks=new Map(), announced=new Map();
class YandexError extends Error { constructor(code){super(code);this.code=code;} }
class CookieJar {
 constructor(){this.values=new Map();}
 accept(url,headers){
  const host=new URL(url).hostname;
  for(const line of headers.getSetCookie()){
   const [first,...rest]=line.split(';'),at=first.indexOf('=');if(at<1)continue;
   const c={name:first.slice(0,at).trim(),value:first.slice(at+1),domain:host,path:'/',hostOnly:true,expires:Infinity};
   for(const attr of rest){const i=attr.indexOf('='),k=(i<0?attr:attr.slice(0,i)).trim().toLowerCase(),v=i<0?'':attr.slice(i+1).trim();
    if(k==='domain'){c.domain=v.replace(/^\./,'').toLowerCase();c.hostOnly=false;}
    if(k==='path')c.path=v;
    if(k==='max-age')c.expires=Date.now()+Number(v)*1000;
    if(k==='expires'&&c.expires===Infinity)c.expires=Date.parse(v);
   }
   if(host!==c.domain&&!host.endsWith('.'+c.domain))continue;
   this.values.set(c.domain+'|'+c.path+'|'+c.name,c);
  }
 }
 header(url){const u=new URL(url);return [...this.values.values()].filter(c=>c.expires>Date.now()&&(c.hostOnly?u.hostname===c.domain:u.hostname===c.domain||u.hostname.endsWith('.'+c.domain))&&u.pathname.startsWith(c.path)).sort((a,b)=>b.path.length-a.path.length).map(c=>c.name+'='+c.value).join('; ');}
}
const allowed=new Set(['mobileproxy.passport.yandex.net','passport.yandex.ru','passport.yandex.com','passport.yandex.by','passport.yandex.kz','passport.yandex.uz','yandex.ru','www.yandex.ru','iot.quasar.yandex.ru']);
async function request(url,options={},jar,signal,transport=fetch){
 const u=new URL(url);if(u.protocol!=='https:'||!allowed.has(u.hostname))throw new YandexError('UNSAFE_AUTH_ENDPOINT');
 if(signal?.aborted)throw new YandexError('CANCELLED');
 try{
  const headers={...options.headers};if(jar?.header(url))headers.Cookie=jar.header(url);
  const combined=signal?AbortSignal.any([signal,AbortSignal.timeout(10000)]):AbortSignal.timeout(10000);
  const r=await transport(url,{...options,headers,redirect:'manual',signal:combined});jar?.accept(url,r.headers);
  const text=await r.text();if(text.length>5000000)throw new YandexError('RESPONSE_TOO_LARGE');
  let data;try{data=JSON.parse(text);}catch{}
  return {status:r.status,data,text};
 }catch(e){if(e instanceof YandexError)throw e;throw new YandexError(signal?.aborted?'CANCELLED':'NETWORK_OR_TIMEOUT');}
}
function ok(r,code){if(r.status<200||r.status>=300||r.data?.status!=='ok')throw new YandexError(code);return r.data;}
async function fresh(credentials,signal,transport){
 const jar=new CookieJar();
 const auth=ok(await request('https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/',{method:'POST',headers:{'Ya-Consumer-Authorization':'OAuth '+credentials.xToken,'Content-Type':'application/x-www-form-urlencoded'},body:'type=x-token&retpath=https%3A%2F%2Fwww.yandex.ru'},jar,signal,transport),'X_TOKEN_REJECTED');
 let host;try{host=new URL(auth.passport_host);}catch{throw new YandexError('INVALID_PASSPORT_HOST');}
 if(!allowed.has(host.hostname)||!host.hostname.startsWith('passport.')||host.protocol!=='https:'||host.username||host.password)throw new YandexError('INVALID_PASSPORT_HOST');
 const login=await request(host.origin+'/auth/session/?'+new URLSearchParams({track_id:auth.track_id}),{},jar,signal,transport);
 if(![200,302,303].includes(login.status))throw new YandexError('SESSION_LOGIN_FAILED');
 const state=await request('https://yandex.ru/iot?storage=1',{},jar,signal,transport);
 if(state.status!==200||!state.data?.storage?.user?.uid)throw new YandexError('SESSION_NOT_AUTHENTICATED');
 const page=await request('https://yandex.ru/iot',{},jar,signal,transport),match=page.text.match(/"csrfToken2":"([^"\n]+)"/);
 if(page.status!==200||!match)throw new YandexError('CSRF_NOT_AVAILABLE');
 let csrf;try{csrf=JSON.parse('"'+match[1]+'"');}catch{throw new YandexError('CSRF_NOT_AVAILABLE');}
 return {jar,csrf,until:Date.now()+6*60*60*1000};
}
function payload(credentials,text){return {name:'Calendar reminders',icon:'home',triggers:[{trigger:{type:'scenario.trigger.voice',value:'календарные напоминания из автоматики'}}],steps:[{type:'scenarios.steps.actions.v2',parameters:{items:[{id:credentials.deviceId,type:'step.action.item.device',value:{id:credentials.deviceId,item_type:'device',capabilities:[{type:'devices.capabilities.quasar',state:{instance:'volume',value:{value:5}}},{type:'devices.capabilities.quasar',state:{instance:'tts',value:{text,whisper:false,lang:'ru'}}}]}}]}}]};}
async function operation(credentials,{text='',check=false,forceRefresh=false,dedupKey='',signal,transport=fetch}={}){
 if(typeof credentials.xToken!=='string'||!credentials.xToken)throw new YandexError('MISSING_X_TOKEN');
 for(const field of ['deviceId','scenarioId'])if(!/^[a-zA-Z0-9_-]{1,128}$/.test(credentials[field]||''))throw new YandexError('INVALID_DEVICE_CONFIGURATION');
 if(!check&&(typeof text!=='string'||!text.trim()||text.length>2000))throw new YandexError('INVALID_ANNOUNCEMENT_TEXT');
 const key=createHash('sha256').update(credentials.xToken+'|'+credentials.deviceId+'|'+credentials.scenarioId).digest('hex');
 const previous=locks.get(key)||Promise.resolve();
 const run=previous.catch(()=>{}).then(async()=>{
  if(signal?.aborted)throw new YandexError('CANCELLED');
  const announcementKey=key+'|'+dedupKey;
  if(!check&&dedupKey&&announced.get(announcementKey)>Date.now()-48*60*60*1000)return {status:'ok',operation:'announce',alreadyAnnounced:true,sessionRefreshed:false};
  let session=sessions.get(key),refreshed=false;
  if(forceRefresh||!session||session.until<=Date.now()){session=await fresh(credentials,signal,transport);sessions.set(key,session);refreshed=true;}
  const put=()=>request('https://iot.quasar.yandex.ru/m/v4/user/scenarios/'+credentials.scenarioId,{method:'PUT',headers:{'x-csrf-token':session.csrf,'Content-Type':'application/json'},body:JSON.stringify(payload(credentials,check?'Напоминания календаря готовы.':text))},session.jar,signal,transport);
  let r=await put();
  if([401,403].includes(r.status)){
   sessions.delete(key);session=await fresh(credentials,signal,transport);sessions.set(key,session);refreshed=true;r=await put();
  }
  try{ok(r,'SCENARIO_UPDATE_FAILED');}catch(e){sessions.delete(key);throw e;}
  if(check)return {status:'ok',operation:'check',sessionRefreshed:refreshed};
  // Never retry execution: a lost response could mean the speech already played.
  const played=await request('https://iot.quasar.yandex.ru/m/user/scenarios/'+credentials.scenarioId+'/actions',{method:'POST',headers:{'x-csrf-token':session.csrf}},session.jar,signal,transport);
  if([401,403].includes(played.status))sessions.delete(key);
  ok(played,'ANNOUNCEMENT_NOT_CONFIRMED');
  if(dedupKey)announced.set(announcementKey,Date.now());
  for(const[k,when]of announced)if(when<Date.now()-48*60*60*1000)announced.delete(k);
  while(announced.size>10000)announced.delete(announced.keys().next().value);
  return {status:'ok',operation:'announce',sessionRefreshed:refreshed};
 });
 locks.set(key,run);
 try{return await run;}finally{if(locks.get(key)===run)locks.delete(key);for(const[k,s]of sessions)if(s.until<Date.now())sessions.delete(k);}
}
module.exports={operation,CookieJar,YandexError,payload};
