'use strict';
const {logEvent}=require('./event-log');
const {operation,YandexError}=require('./yandex-client');
class YandexStation {
 constructor(){this.description={displayName:'Yandex Calendar Voice',name:'yandexStation',group:['output'],version:1,description:'Dynamic calendar announcements with automatic session renewal',defaults:{name:'Announce via Yandex Station'},inputs:['main'],outputs:['main'],credentials:[{name:'yandexStationApi',required:true}],properties:[{displayName:'Operation',name:'operation',type:'options',options:[{name:'Announce',value:'announce'},{name:'Check and Refresh Session',value:'check'}],default:'announce'},{displayName:'Text',name:'text',type:'string',default:'={{ $json.text }}',displayOptions:{show:{operation:['announce']}}},{displayName:'Force Fresh Session',name:'forceRefresh',type:'boolean',default:false}]};}
 async execute(){
  const credentials=await this.getCredentials('yandexStationApi'),items=this.getInputData(),out=[];
  for(let i=0;i<items.length;i++){
   const check=this.getNodeParameter('operation',i)==='check';
   try{
    const result=await operation(credentials,{check,dedupKey:check?'':String(items[i].json.dedupKey||''),text:check?'':this.getNodeParameter('text',i),forceRefresh:this.getNodeParameter('forceRefresh',i),signal:this.getExecutionCancelSignal?.()});
    logEvent('yandex-calendar',check?'session_check_ok':'announcement_ok',{sessionRefreshed:result.sessionRefreshed});
    out.push({json:result,pairedItem:{item:i}});
   }catch(e){
    const code=e instanceof YandexError?e.code:'UNEXPECTED_FAILURE';logEvent('yandex-calendar',check?'session_check_failed':'announcement_failed',{code});
    throw new Error('Yandex Calendar: '+code+'; see docs/n8n/setup.md');
   }
  }
  return [out];
 }
}
module.exports={YandexStation};
