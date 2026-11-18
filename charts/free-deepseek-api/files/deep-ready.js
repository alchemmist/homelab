const DEEP_READY_TTL_MS = 10 * 60 * 1000;
let deepReadyCache = { at: 0, ok: false, reason: 'unchecked' };
async function probeAccountDeep(account) {
    const signal = AbortSignal.timeout(20000);
    await createPowHeader(account, signal, '/api/v0/chat/completion');
    const response = await dsFetch(dsUrl('/api/v0/users/current'), { method: 'GET', headers: account.headers, signal });
    const text = await response.text();
    let json = null;
    try { json = JSON.parse(text); } catch {}
    const biz = json && json.data ? json.data.biz_data : null;
    const code = json ? (json.code != null ? json.code : (json.data ? json.data.biz_code : undefined)) : undefined;
    if (response.status === 401 || code === 40001 || code === 40003 || code === 40012 || biz == null || (code && code !== 0) || !response.ok) {
        return { ok: false, reason: 'session rejected' };
    }
    return { ok: true, reason: 'pow+users/current' };
}
async function deepReady() {
    const now = Date.now();
    if (now - deepReadyCache.at < DEEP_READY_TTL_MS) return deepReadyCache;
    const account = accounts.find((item) => item.config.token && item.config.cookie && item.cooldownUntil <= now);
    if (!account) {
        deepReadyCache = { at: now, ok: false, reason: 'no local session' };
        return deepReadyCache;
    }
    try {
        const result = await probeAccountDeep(account);
        deepReadyCache = { at: now, ok: result.ok, reason: result.reason };
    } catch (error) {
        deepReadyCache = { at: now, ok: false, reason: 'probe failed' };
    }
    return deepReadyCache;
}
