'use strict';
require('./google-transport').install(record=>{
 console.warn(JSON.stringify({level:'warning',service:'n8n',component:'google-transport',...record}));
});
