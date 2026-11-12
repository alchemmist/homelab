'use strict';
// Preload before n8n imports HTTP clients; only two exact hosts are affected.
const dns=require('node:dns');
const {createLookup}=require('./google-dns');
dns.lookup=createLookup(dns.lookup.bind(dns),undefined,record=>{
 console.warn(JSON.stringify({level:'warning',service:'n8n',component:'google-dns',...record}));
});
require('node:module').syncBuiltinESMExports();
