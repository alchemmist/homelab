// Regression coverage for normal dashboard entry and stale copied links.
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const require = createRequire(resolve(process.env.LMS_CHECKOUT, 'tests/package.json'));
const { chromium } = require('playwright');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const outcomes = [];
  for (const suffix of ['', '?var-trace_id=00000000000000000000000000000001', '?from=now-5m&to=now']) {
    await page.goto('https://grafana.socrat.alchemmist.xyz/d/lms-performance' + suffix, { waitUntil: 'domcontentloaded' });
    const waterfall = page.getByRole('region').filter({ hasText: 'Distributed waterfall' }).first();
    await waterfall.waitFor({ state: 'visible', timeout: 45000 });
    if (await page.getByRole('combobox', { name: /^(tempo|loki)$/i }).count()) throw new Error('Redundant datasource selector is still visible');
    await waterfall.scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.body.innerText.includes('Service & Operation'), null, { timeout: 45000 });
    const id = (await waterfall.innerText()).match(/[0-9a-f]{32}/)?.[0];
    if (!id || id === '00000000000000000000000000000001') throw new Error('Invalid or empty trace selection');
    const logs = page.getByRole('region').filter({ hasText: 'Correlated Loki logs' }).first();
    await logs.scrollIntoViewIfNeeded();
    await logs.getByText('http trace_id=' + id, { exact: false }).first().waitFor({ state: 'visible', timeout: 45000 });
    outcomes.push({ entry: suffix || 'bare-dashboard', traceId: id, waterfallRendered: true, correlatedLogsRendered: true });
  }
  console.log(JSON.stringify({ success: true, scenarios: outcomes }, null, 2));
} finally { await browser.close(); }
