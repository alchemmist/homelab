// Read-only operator browser regression. Requires Playwright and an existing
// private native Editor/Admin session; never creates users or changes permissions.
const {chromium}=require('playwright');
const fs=require('fs'),assert=require('assert');const dir=process.env.SPI_GRAFANA_CHECK_DIR;
if(!dir)throw new Error('SPI_GRAFANA_CHECK_DIR must contain links.json and private browser-state.json');
const upstream=process.env.SPI_GRAFANA_TEST_UPSTREAM;
if(upstream&&!/^http:\/\/127\.0\.0\.1:\d+$/.test(upstream))throw new Error('Test transport must be a loopback SSH tunnel');
(async()=>{
 const browser=await chromium.launch({headless:true});const context=await browser.newContext({storageState:dir+'/browser-state.json',timezoneId:'UTC'});
 if(upstream)await context.route('https://grafana.socrat.alchemmist.xyz/**',async route=>{const r=route.request(),u=new URL(r.url());const response=await route.fetch({url:upstream+u.pathname+u.search,headers:{...r.headers(),host:u.hostname,'x-forwarded-proto':'https'},maxRedirects:0});await route.fulfill({response});});
 const page=await context.newPage();const requests=[];
 page.on('request',r=>{if(new URL(r.url()).pathname==='/api/ds/query'){try{requests.push(JSON.parse(r.postData()));}catch{}}});
 const results=[];
 for(const [title,original] of JSON.parse(fs.readFileSync(dir+'/links.json'))){
  const u=new URL(original);assert.equal(u.origin,'https://grafana.socrat.alchemmist.xyz');assert.equal(u.pathname,'/explore');u.searchParams.set('forceLogin','true');const pane=JSON.parse(u.searchParams.get('panes')).spi;const begin=requests.length;
  await page.goto(u.href,{waitUntil:'domcontentloaded'});await page.waitForLoadState('networkidle');
  assert.equal(new URL(page.url()).pathname,'/explore',title+' must not redirect home');
  const active=JSON.parse(new URL(page.url()).searchParams.get('panes'));const current=Object.values(active)[0];
  assert.deepEqual(current.range,pane.range,title+' range preserved');assert.equal(current.datasource,pane.datasource);
  const times=await page.locator('button[aria-label^="Time range selected:"]').getAttribute('aria-label');
  for(const field of ['from','to'])assert(times.includes(new Date(Number(pane.range[field])).toISOString().slice(0,19).replace('T',' ')),title+' actual time picker '+field);
  const expected=pane.queries[0].expr||pane.queries[0].query;
  const editors=await page.locator('textarea, [role="textbox"]').evaluateAll(xs=>xs.map(x=>x.value||x.innerText));
  const sent=requests.slice(begin).some(r=>r.queries?.some(q=>(q.expr||q.query)===expected)&&String(r.from)===pane.range.from&&String(r.to)===pane.range.to);
  const texts=(await page.locator('body').innerText());
  const r={title,datasource:current.datasource,timePicker:times,queryInEditor:editors.includes(expected),exactQueryAndWindowSent:sent,queryError:/Query error|parse error|invalid TraceQL|Invalid query/.test(texts)};
  results.push(r);console.log(JSON.stringify(r));
  assert(!r.queryError,title+' invalid query');assert(r.queryInEditor||r.exactQueryAndWindowSent,title+' query retained in editor or executed');
 }
 fs.writeFileSync(dir+'/browser-all.json',JSON.stringify(results,null,2),{mode:0o600});await browser.close();
})().catch(e=>{console.error(e.message);process.exit(1)});
