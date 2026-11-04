'use strict';
// Deliberately no generic object spread: input/output bodies and IDs stay private.
function logEvent(component,event,fields={}) {
 const level=event.endsWith('_failed')?'error':'info';
 const record={ts:new Date().toISOString(),level,service:'n8n-extensions',component,event,msg:event};
 if(typeof fields.sessionRefreshed==='boolean')record.sessionRefreshed=fields.sessionRefreshed;
 if(typeof fields.code==='string' && /^[A-Z][A-Z0-9_]{0,79}$/.test(fields.code))record.code=fields.code;
 (level==='error'?console.error:console.log)(JSON.stringify(record));
}
module.exports={logEvent};
