'use strict';
class YandexStationApi {
 constructor(){this.name='yandexStationApi';this.displayName='Yandex Station Auto Session';this.documentationUrl='https://github.com/alchemmist/homelab/blob/main/docs/n8n/setup.md';this.properties=[{displayName:'X-Token',name:'xToken',type:'string',typeOptions:{password:true},default:'',required:true},{displayName:'Cloud Device ID',name:'deviceId',type:'string',default:'',required:true},{displayName:'Calendar Scenario ID',name:'scenarioId',type:'string',default:'',required:true}];}
}
module.exports={YandexStationApi};
