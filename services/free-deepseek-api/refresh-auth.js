'use strict';

const fs = require('fs');
const http = require('http');

const cdpPort = Number(process.env.DEEPSEEK_CHROME_PORT || 9222);
const outPath = process.env.DEEPSEEK_AUTH_PATH || '/data/deepseek-auth.json';
const intervalMs = Number(process.env.AUTH_REFRESH_MS || 30000);
const wasmPattern = /https:\/\/fe-static\.deepseek\.com\/chat\/static\/sha3_wasm_bg\.[a-z0-9]+\.wasm/;

let cdpMisses = 0;

function getJson(urlPath) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: cdpPort, path: urlPath }, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(body)); }
        catch (error) { reject(error); }
      });
    }).on('error', reject);
  });
}

function normalizeToken(raw) {
  if (!raw) return '';
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      return parsed.value || parsed.token || parsed.access_token || parsed.accessToken || '';
    }
  } catch {}
  return String(raw).trim().replace(/^"|"$/g, '');
}

function readPrevious() {
  try { return JSON.parse(fs.readFileSync(outPath, 'utf8')); }
  catch { return {}; }
}

function writeAuth(auth) {
  const next = JSON.stringify(auth);
  const previous = fs.existsSync(outPath) ? fs.readFileSync(outPath, 'utf8') : '';
  if (previous === next) return false;
  const tmp = `${outPath}.tmp`;
  fs.writeFileSync(tmp, next);
  fs.renameSync(tmp, outPath);
  return true;
}

async function wasmAvailable(url) {
  if (!wasmPattern.test(url || '')) return false;
  const response = await fetch(url, { method: 'GET' });
  try { await response.body?.cancel(); } catch {}
  return response.ok;
}

async function resolveWasmUrl(send, previousUrl) {
  const evaluated = await send('Runtime.evaluate', {
    expression: 'performance.getEntriesByType("resource").map((entry) => entry.name).filter((name) => name.includes("sha3_wasm_bg")).join("\\n")',
    returnByValue: true,
  });
  const fromPage = String(evaluated.result?.value || '')
    .split('\n')
    .map((item) => item.trim())
    .filter((item) => wasmPattern.test(item));
  const candidate = fromPage[fromPage.length - 1] || '';
  if (candidate && await wasmAvailable(candidate)) return candidate;
  if (previousUrl && previousUrl !== candidate && await wasmAvailable(previousUrl)) return previousUrl;
  return '';
}

async function readCdpAuth(previousWasm) {
  const targets = await getJson('/json/list');
  const page = targets.find((target) => target.type === 'page' && /deepseek\.com/.test(target.url));
  if (!page?.webSocketDebuggerUrl) throw new Error('Chrome has no DeepSeek page');
  const browser = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    browser.addEventListener('open', resolve, { once: true });
    browser.addEventListener('error', reject, { once: true });
  });
  let id = 0;
  const pending = new Map();
  browser.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    const waiter = pending.get(message.id);
    if (!waiter) return;
    pending.delete(message.id);
    if (message.error) waiter.reject(new Error(message.error.message || 'cdp error'));
    else waiter.resolve(message.result || {});
  });
  const send = (method, params = {}) => {
    const messageId = ++id;
    browser.send(JSON.stringify({ id: messageId, method, params }));
    return new Promise((resolve, reject) => pending.set(messageId, { resolve, reject }));
  };
  try {
    await send('Runtime.enable');
    await send('Network.enable');
    const evaluated = await send('Runtime.evaluate', {
      expression: 'JSON.stringify({token: localStorage.getItem("userToken") || "", hif: localStorage.getItem("hif_leim_cached") || ""})',
      returnByValue: true,
    });
    const cookieResult = await send('Network.getCookies', { urls: ['https://chat.deepseek.com/'] });
    const pageState = JSON.parse(evaluated.result?.value || '{}');
    const cookies = (cookieResult.cookies || []).filter((cookie) => /deepseek\.com$/.test(cookie.domain));
    return {
      token: normalizeToken(pageState.token || ''),
      cookie: cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join('; '),
      hif_dliq: '',
      hif_leim: normalizeToken(pageState.hif),
      wasmUrl: await resolveWasmUrl(send, previousWasm),
      baseUrl: 'https://chat.deepseek.com',
    };
  } finally {
    browser.close();
  }
}

function clearAuth() {
  writeAuth({ token: '', cookie: '', hif_dliq: '', hif_leim: '', wasmUrl: '', baseUrl: 'https://chat.deepseek.com' });
}

async function once() {
  const previous = readPrevious();
  let auth;
  try {
    auth = await readCdpAuth(previous.wasmUrl || '');
    cdpMisses = 0;
  } catch (error) {
    cdpMisses += 1;
    console.log(`[auth-refresh] CDP unavailable (${cdpMisses}): ${error.message}`);
    if (cdpMisses >= 2) clearAuth();
    return;
  }
  if (!auth.token || !auth.cookie || !auth.wasmUrl) {
    console.log('[auth-refresh] Chrome has no live DeepSeek session');
    clearAuth();
    return;
  }
  if (writeAuth(auth)) console.log('[auth-refresh] updated DeepSeek session from CDP');
}

async function main() {
  for (;;) {
    try { await once(); }
    catch (error) { console.log(`[auth-refresh] ${error.message}`); }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

main();
