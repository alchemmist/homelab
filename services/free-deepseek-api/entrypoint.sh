#!/bin/bash
set -euo pipefail

export DISPLAY=:99
mkdir -p /data/profile /tmp/runtime
export XDG_RUNTIME_DIR=/tmp/runtime

if [[ ! -s /data/deepseek-auth.json ]]; then
  printf '%s\n' '{"token":"","cookie":""}' > /data/deepseek-auth.json
fi

if ! grep -q reloadDeepSeekAuthIfChanged /app/server.js; then
  python3 - <<'PY'
from pathlib import Path
path = Path('/app/server.js')
text = path.read_text()
needle = 'const server = http.createServer(async (req, res) => {\n'
fn = '''
let deepSeekAuthMtime = 0;
function reloadDeepSeekAuthIfChanged() {
    try {
        const st = fs.statSync(DS_CONFIG_PATH);
        if (st.mtimeMs !== deepSeekAuthMtime) {
            deepSeekAuthMtime = st.mtimeMs;
            loadDeepSeekConfig({ fatal: false });
        }
    } catch {}
}
'''
if needle not in text:
    raise SystemExit('server.js request handler not found')
path.write_text(text.replace(needle, fn + needle + '    reloadDeepSeekAuthIfChanged();\n', 1))
PY
fi

Xvfb :99 -screen 0 1366x768x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
for _ in $(seq 1 50); do
  [[ -S /tmp/.X11-unix/X99 ]] && break
  sleep 0.1
done

x11vnc -display :99 -forever -shared -rfbport 5900 -passwdfile /run/secrets/vnc-password -localhost \
  >/tmp/x11vnc.log 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &

google-chrome-stable \
  --user-data-dir=/data/profile \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --password-store=basic \
  --no-first-run \
  --no-default-browser-check \
  --window-size=1366,768 \
  --start-maximized \
  about:blank \
  >/tmp/chrome.log 2>&1 &

node /app/refresh-auth.js >/tmp/auth-refresh.log 2>&1 &
exec node /app/server.js
