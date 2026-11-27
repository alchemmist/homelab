// Anonymous layout checks: no accounts, submissions, simulated MFA success or screenshots.
const assert = require('node:assert/strict');
const { chromium, webkit } = require('playwright');
const base = 'https://auth.socrat.alchemmist.xyz';
async function reachable(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  const rect = await locator.boundingBox();
  const { width, height } = page.viewportSize();
  assert(rect && rect.x >= -1 && rect.x + rect.width <= width + 1 && rect.y >= -1 && rect.y + rect.height <= height + 1, `Unreachable control: ${JSON.stringify(rect)} in ${width}x${height}`);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Horizontal page scroll');
}
(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch(engine === chromium ? { channel: 'chrome' } : {});
    try {
      for (const [width, height] of [[320,568],[360,340],[390,844],[844,320]]) {
        const page = await browser.newPage({ viewport:{width,height}, isMobile:true, hasTouch:true, locale:'ru-RU' });
        try {
          await page.goto(base + '/if/flow/default-authentication-flow/?locale=ru');
          const uid = page.locator('input[name=uidField]');
          await uid.waitFor();
          for (const loc of [uid, page.locator('input[type=password]').first(),page.getByRole('button',{name:/^Log in\b/i})]) await reachable(page, loc);
          const response = await page.goto(base+'/application/o/authorize/?client_id=quiet-mono-ui-probe&response_type=code');
          assert.equal(response.status(),400);
          await reachable(page,page.locator('#ak-back-home'));
          console.log('PASS login + server error:',engine.name(),width,height);
        } finally { await page.close(); }
      }
    } finally { await browser.close(); }
  }
})().catch(e => {console.error(e);process.exitCode=1;});
