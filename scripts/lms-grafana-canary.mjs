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
  console.log(JSON.stringify({ waterfallRendered: true, databaseAndBrowserOperationsVisible: true,
    correlatedLogsRendered: true, browserExceptions: errors, datasourceHttpFailures: queryFailures }));
} finally { await browser.close(); }
