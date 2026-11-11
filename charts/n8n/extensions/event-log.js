'use strict';
// Deliberately no generic object spread: input/output bodies and IDs stay private.
function logEvent(component,event,fields={}) {
 const level=event.endsWith('_failed')?'error':'info';
 const record={ts:new Date().toISOString(),level,service:'n8n-extensions',component,event,msg:event};
 if(typeof fields.sessionRefreshed==='boolean')record.sessionRefreshed=fields.sessionRefreshed;
 if(typeof fields.code==='string' && /^[A-Z][A-Z0-9_]{0,79}$/.test(fields.code))record.code=fields.code;
 if(typeof fields.phase==='string'&&/^(X_TOKEN|SESSION_LOGIN|SESSION_STATE|CSRF_PAGE|SCENARIO_UPDATE|SCENARIO_EXECUTE|UNKNOWN)$/.test(fields.phase))record.phase=fields.phase;
 if(typeof fields.transportCode==='string'&&/^(EAI_AGAIN|ETIMEOUT|ENOTFOUND|ENODATA|ECONNREFUSED|ECONNRESET|ETIMEDOUT|CERT_HAS_EXPIRED|ERR_TLS_CERT_ALTNAME_INVALID|ABORT_ERR)$/.test(fields.transportCode))record.transportCode=fields.transportCode;
 (level==='error'?console.error:console.log)(JSON.stringify(record));
}
module.exports={logEvent};
