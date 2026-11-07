#!/usr/bin/env node
// Verify the real anonymous TV scene, not a mocked model or /d/ editor scene.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const flag = process.argv.indexOf('--url-file');
assert(flag >= 0 && process.argv[flag + 1], '--url-file must name a private fully-url.json');
const url = JSON.parse(fs.readFileSync(process.argv[flag + 1], 'utf8')).startURL;
const parsed = new URL(url);
assert.equal(parsed.hostname, 'grafana.socrat.alchemmist.xyz');
assert(/^\/public-dashboards\/[a-f0-9]{32}\/?$/.test(parsed.pathname));
assert.equal(parsed.searchParams.get('socratTv'), '1');
const expected = JSON.parse(fs.readFileSync(path.join(__dirname, '../charts/monitoring-k3s/dashboards/traffic-light.json')));
const authFlag = process.argv.indexOf('--auth-state-file');
const authState = authFlag >= 0 ? process.argv[authFlag + 1] : undefined;
const activity = [909, 920, 923, 924, 925];
for (const id of activity) {
  const panel = expected.panels.find(p => p.id === id);
  assert(!panel.title && !panel.description, `Unexpected panel chrome: ${id}`);
  assert(!panel.options?.legend?.showLegend, `Unexpected legend: ${id}`);
  if (panel.timeFrom) assert(panel.hideTimeOverride, `Visible time badge: ${id}`);
}
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    const cases = ['shared'];
    if (authState) cases.push('authenticated');
    for (const mode of cases) for (const [width, height] of [[1920, 1080], [1440, 900]]) {
      const page = await browser.newPage({ viewport: { width, height }, ...(mode === 'authenticated' ? { storageState: authState } : {}) });
      const failures = [];
      page.on('pageerror', e => failures.push(e.message));
      page.on('response', r => {
        // Grafana's anonymous discovery probe can return 401; panel queries cannot.
        if ((/\/panels\/\d+\/query/.test(r.url()) || r.url().includes('/api/ds/query')) && r.status() >= 400) failures.push(`panel query HTTP ${r.status()}`);
      });
      const visit = mode === 'shared' ? url : parsed.origin + '/d/socrat-traffic-light?kiosk=1&hideLogo=1&autofitpanels=true';
      await page.goto(visit, { waitUntil: 'networkidle', timeout: 60000 });
      await page.waitForFunction(() => {
        const s = document.querySelector('.socrat-tv-public-grid,.socrat-tv-auth-grid');
        return s && s.getBoundingClientRect().height > 0;
      });
      await page.waitForTimeout(6000);
      assert.deepEqual(failures, [], 'Panel request / JS errors');
      const panels = await page.locator('.react-grid-item[data-griditem-key]').evaluateAll(els => els.map(el => {
        const r = el.getBoundingClientRect();
        return { id: Number(el.dataset.griditemKey.replace('grid-item-', '')), x: r.x, y: r.y, w: r.width, h: r.height };
      }));
      assert.equal(panels.length, expected.panels.length, 'Unexpected served panel count');
      const byId = Object.fromEntries(panels.map(p => [p.id, p]));
      for (const p of panels) {
        assert(p.x >= 4 && p.y >= 4 && p.x + p.w <= width - 4 && p.y + p.h <= height - 4, `Panel ${p.id} outside viewport`);
        for (const q of panels) {
          if (p.id >= q.id) continue;
          const overlapX = Math.min(p.x + p.w, q.x + q.w) - Math.max(p.x, q.x);
          const overlapY = Math.min(p.y + p.h, q.y + q.h) - Math.max(p.y, q.y);
          assert(overlapX <= 1 || overlapY <= 1, `Panels ${p.id}/${q.id} overlap`);
        }
      }
      const close = (a, b) => assert(Math.abs(a - b) <= 1, `Geometry mismatch: ${a}/${b}`);
      close(byId[21].h, byId[22].h);
      close(byId[21].h, byId[23].h);
      close(byId[23].y + byId[23].h, byId[907].y + byId[907].h);
      close(byId[334].y, byId[920].y);
      close(byId[334].w, byId[920].w);
      close(byId[334].h, byId[920].h);
      for (const id of [923, 924, 925]) {
        close(byId[id].y, byId[923].y);
        const el = page.locator(`[data-griditem-key="grid-item-${id}"]`);
        const text = await el.innerText();
        assert(/n8n/.test(text) && /\d/.test(text) && !/No telemetry/.test(text), `Missing activity readout: ${id}`);
        const clipped = await el.evaluate(el => {
          const box = el.getBoundingClientRect(), walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
          const bad = [];
          while (walk.nextNode()) {
            if (!walk.currentNode.textContent.trim()) continue;
            const range = document.createRange(); range.selectNodeContents(walk.currentNode);
            for (const r of range.getClientRects()) {
              if (r.width && r.height && (r.left < box.left - 1 || r.right > box.right + 1 || r.top < box.top - 1 || r.bottom > box.bottom + 1)) bad.push('text outside panel');
            }
          }
          return bad;
        });
        assert.deepEqual(clipped, [], `Clipped activity text: ${id}`);
      }
      const text = await page.locator('body').innerText();
      assert(!/Last 1 hour|Last 30 minutes|Delivery · one segment|Git drift|n8n · activity/.test(text), 'Unexpected header / period chrome');
      if (process.env.TV_SCREENSHOT_DIR) {
        fs.mkdirSync(process.env.TV_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.TV_SCREENSHOT_DIR, `tv-${mode}-${width}x${height}.png`) });
      }
      console.log(`PASS ${mode} TV ${width}x${height}: ${panels.length} panels; resource height ${byId[23].h}px; no overlap/clipping; headerless activity`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(String(e.message).replace(/[a-f0-9]{32}/g, '<share>')); process.exitCode = 1; });
