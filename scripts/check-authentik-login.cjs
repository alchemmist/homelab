// Anonymous production smoke test. No credentials, submissions or server-side writes.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = 'https://auth.socrat.alchemmist.xyz';

(async () => {
  const browser = await chromium.launch({ channel: process.env.CHROME_CHANNEL || 'chrome' });
  try {
    for (const width of [1440, 390]) {
      const ctx = await browser.newContext({ locale: 'ru-RU', viewport: { width, height: 850 } });
      const page = await ctx.newPage();
      await ctx.addCookies([{ name: 'authentik_language', value: 'ru', url: base }]);
      await page.addInitScript(() => sessionStorage.setItem('authentik:locale', 'ru'));
      await page.route('**/authwall/scene.css', r => r.abort());
      // Hold the initial challenge until we have actually measured the placeholder.
      let release;
      const gate = new Promise(resolve => { release = resolve; });
      await page.route('**/api/v3/flows/executor/**', async r => { await gate; await r.continue(); });
      const photo = page.waitForResponse(r => r.ok() && r.url().endsWith(width < 700 ? 'lake-960.webp' : 'lake-1920.webp'));
      await page.goto(base + '/if/flow/default-authentication-flow/?locale=ru', { waitUntil: 'domcontentloaded' });
      const card = page.locator('ak-flow-executor [part="main"]');
      let cold;
      try {
        await card.locator('ak-flow-card').waitFor({ state: 'attached' });
        cold = await card.evaluate(el => el.offsetHeight);
      } finally { release(); }
      const pwd = page.locator('input[type=password]').first();
      await pwd.waitFor();
      await photo;
      assert.equal(await page.locator('html').getAttribute('lang'), 'en');
      assert.equal(new URL(page.url()).searchParams.get('locale'), 'en');
      await page.getByRole('button', { name: 'Log in', exact: true }).waitFor();
      assert.equal(await card.evaluate(el => el.offsetHeight), cold);
      await page.keyboard.press('Tab');
      await pwd.focus();
      assert.equal(await pwd.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
      if (width < 700) assert.equal(await pwd.evaluate(el => getComputedStyle(el).fontSize), '16px');
      const host = page.locator('ak-flow-executor');
      await host.evaluate(async el => { el.loading = true; await el.updateComplete; });
      await card.locator('ak-loading-overlay ak-empty-state[loading]').waitFor();
      assert.equal(await pwd.isVisible(), false);
      assert.equal(await card.evaluate(el => el.offsetHeight), cold);
      await host.evaluate(async el => { el.loading = false; await el.updateComplete; });
      await pwd.waitFor();
      await ctx.close();
      console.log(`Login UI OK at ${width}px`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
