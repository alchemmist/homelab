// Verify real native Pyroscope frames AND flame-graph/table interactions.
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const require = createRequire(resolve(process.env.LMS_CHECKOUT, 'tests/package.json'));
const { chromium } = require('playwright');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  const exceptions = [], failures = [], frames = [];
  page.on('pageerror', error => exceptions.push(String(error)));
  page.on('response', async response => {
    if (!response.url().includes('/api/ds/query')) return;
    const request = response.request().postData() || '';
    if (!request.includes('pyroscope')) return;
    if (!response.ok()) { failures.push(response.status()); return; }
    const data = await response.json();
    for (const result of Object.values(data.results || {})) {
      if (result.error) failures.push(result.error);
      for (const frame of result.frames || []) frames.push(frame);
    }
  });
  await page.goto(process.env.LMS_CPU_DASHBOARD_URL || 'https://grafana.socrat.alchemmist.xyz/d/service-cpu-profiling', { waitUntil: 'domcontentloaded' });
  const graph = page.getByRole('region').filter({ hasText: 'CPU flame graph' }).first();
  await graph.waitFor({ state: 'visible', timeout: 45000 });
  await graph.getByText('Flame Graph', { exact: true }).waitFor({ timeout: 45000 });
  await page.waitForFunction(() => document.body.innerText.includes('lms-backend'), null, { timeout: 45000 });
  await graph.getByRole('radio', { name: 'Top Table', exact: true }).check();
  await graph.getByText('Self', { exact: true }).first().waitFor({ timeout: 45000 });
  await graph.getByText('render_navigation', { exact: false }).first().waitFor({ timeout: 45000 });
  const profile = frames.find(f => (f.schema.fields || []).some(field => field.name === 'level'));
  if (!profile) throw new Error('No native stack-profile dataframe received');
  const rows = profile.data.values[0].length;
  if (rows < 5 || exceptions.length || failures.length) throw new Error(JSON.stringify({ rows, exceptions, failures }));
  await graph.getByRole('radio', { name: 'Flame Graph', exact: true }).check();
  const timeline = page.getByRole('region').filter({ hasText: 'Sampled CPU usage' }).first();
  await timeline.scrollIntoViewIfNeeded();
  await timeline.locator('canvas').first().waitFor({ state: 'visible', timeout: 30000 });
  console.log(JSON.stringify({ success: true, selectedService: 'lms-backend', nativeProfileRows: rows,
    flameGraphRendered: true, topTableRendered: true, applicationFunctionVisible: 'render_navigation',
    cpuTimelineRendered: true, browserExceptions: exceptions, datasourceFailures: failures }, null, 2));
} finally { await browser.close(); }
