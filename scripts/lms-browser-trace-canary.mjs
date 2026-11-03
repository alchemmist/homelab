// Called by lms-observability-verify.py; session exists only in process memory.
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const require = createRequire(resolve(process.env.LMS_CHECKOUT, 'tests/package.json'));
const { chromium } = require('playwright');
const base = process.env.LMS_CANARY_URL;
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext();
  await context.addCookies([{ name: '__Host-lms_session', value: process.env.LMS_CANARY_SESSION,
    url: base, httpOnly: true, secure: true, sameSite: 'Lax' }]);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const response = await page.goto(base + '/basics/znakomstvo-so-sredoi/textbook/', { waitUntil: 'load', timeout: 60000 });
  if (response.status() !== 200 || !page.url().startsWith(base + '/basics/')) throw new Error('Canary session did not open the real lesson');
  const pageTrace = response.headers()['traceparent'];
  const upload = page.waitForResponse(r => r.url() === base + '/api/telemetry' && r.request().method() === 'POST', { timeout: 20000 });
  // A read-only, deliberately missing API route makes one ERROR browser span;
  // the existing global error-tail policy retains this diagnostic trace.
  const api = await page.evaluate(async () => {
    const r = await fetch('/api/telemetry-canary-not-found');
    return { status: r.status, context: r.headers.get('traceparent') };
  });
  const telemetry = await upload;
  if (telemetry.status() !== 204 || api.status !== 404 || errors.length) throw new Error(JSON.stringify({ telemetry: telemetry.status(), apiStatus: api.status, errors }));
  await page.waitForTimeout(1800);
  console.log(JSON.stringify({ pageStatus: response.status(), pageTrace, apiContext: api.context,
    apiStatus: api.status, intakeStatus: telemetry.status(), browserErrors: errors }));
} finally { await browser.close(); }
