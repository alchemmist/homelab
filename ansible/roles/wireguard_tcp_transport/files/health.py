import json
import subprocess
import time
from pathlib import Path


STATE = Path('/run/wireguard-tcp-transport-health/state.json')


def next_state(state, now, healthy):
    if healthy:
        return {'failures': 0, 'restarted': state.get('restarted', 0)}, False
    failures = state.get('failures', 0) + 1
    restarted = state.get('restarted', 0)
    restart = failures >= 3 and now - restarted >= 60 and now >= 60
    return {'failures': 0 if restart else failures, 'restarted': now if restart else restarted}, restart


def main():
    now = time.clock_gettime(time.CLOCK_BOOTTIME)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    try:
        result = subprocess.run(['ping', '-n', '-c', '1', '-W', '2', '10.250.0.2'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        healthy = result.returncode == 0
    except subprocess.TimeoutExpired:
        healthy = False
    state, restart = next_state(state, now, healthy)
    STATE.write_text(json.dumps(state))
    if restart:
        subprocess.run(['systemctl', 'restart', 'wireguard-tcp-transport.service'], check=True, timeout=20)


if __name__ == '__main__':
    main()
