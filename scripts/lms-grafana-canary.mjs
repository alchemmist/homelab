// Validate the actual provisioned dashboard in Chromium, not just Tempo's API.
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const require = createRequire(resolve(process.env.LMS_CHECKOUT, 'tests/package.json'));
const { chromium } = require('playwright');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], queryFailures = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('response', response => {
    if (response.url().includes('/api/ds/query') && response.status() >= 400) queryFailures.push(response.status());
  });
  // Critical regression: opening the bare dashboard must not need a copied ID.
  const bareUrl = new URL(process.env.LMS_DASHBOARD_URL);
  bareUrl.search = '';
  await page.goto(bareUrl.href, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const automatic = page.getByRole('region').filter({ hasText: 'Distributed waterfall' }).first();
  await automatic.waitFor({ state: 'visible', timeout: 45000 });
  await automatic.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.body.innerText.includes('Service & Operation'), null, { timeout: 45000 });
  const selectedId = (await automatic.innerText()).match(/[0-9a-f]{32}/)?.[0];
  if (!selectedId) throw new Error('Default dashboard has no automatic trace selection');
  const automaticLogs = page.getByRole('region').filter({ hasText: 'Correlated Loki logs' }).first();
  await automaticLogs.scrollIntoViewIfNeeded();
  await page.waitForFunction(id => document.body.innerText.includes('http trace_id=' + id), selectedId, { timeout: 45000 });
  const recent = page.getByRole('region').filter({ hasText: 'Recent LMS application logs' }).first();
  await recent.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.body.innerText.includes('http trace_id='), null, { timeout: 45000 });
  await page.goto(process.env.LMS_DASHBOARD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const waterfall = page.getByRole('region').filter({ hasText: 'Distributed waterfall' }).first();
  await waterfall.waitFor({ state: 'visible', timeout: 45000 });
  await waterfall.scrollIntoViewIfNeeded();
  await page.waitForFunction(n => document.body.innerText.includes(n + ' spans'), Number(process.env.LMS_SPAN_COUNT), { timeout: 45000 });
  const waterfallText = await waterfall.innerText();
  if (!waterfallText.includes('browser.page') || !waterfallText.includes('db.transaction')) throw new Error('Waterfall operations missing');
  const logs = page.getByRole('region').filter({ hasText: 'Correlated Loki logs' }).first();
  await logs.scrollIntoViewIfNeeded();
  await page.waitForFunction(id => document.body.innerText.includes('http trace_id=' + id), process.env.LMS_TRACE_ID, { timeout: 45000 });
  if (errors.length || queryFailures.length) throw new Error(JSON.stringify({ errors, queryFailures }));
  console.log(JSON.stringify({ defaultDashboardAutoSelected: true, defaultTraceId: selectedId, defaultCorrelatedLogsRendered: true, recentLogsRendered: true, waterfallRendered: true, databaseAndBrowserOperationsVisible: true,
    correlatedLogsRendered: true, browserExceptions: errors, datasourceHttpFailures: queryFailures }));
} finally { await browser.close(); }
