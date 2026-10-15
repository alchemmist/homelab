import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import urllib.request
import xml.etree.ElementTree as ET


SYNCTHING_CONFIG = Path('/srv/syncthing/config/config.xml')
KUBELET_CONFIG = Path('/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/99-homelab-disk-reserve.conf')
RESULT = Path('/var/lib/homelab/node-disk-reserve-result.json')


def atomic_write(path, content, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.homelab-tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def pause_folder(config_path, folder_id):
    tree = ET.fromstring(config_path.read_bytes())
    folder = next((f for f in tree.findall('folder') if f.get('id') == folder_id), None)
    if folder is None:
        raise RuntimeError(f'Missing Syncthing folder: {folder_id}')
    paused = folder.find('paused')
    if paused is not None and paused.text == 'true':
        return False
    running = subprocess.run(['pgrep', '-x', 'syncthing'], capture_output=True).returncode == 0
    if running:
        key = tree.findtext('gui/apikey')
        if not key:
            raise RuntimeError('Syncthing API key is missing')
        endpoint = 'http://127.0.0.1:8384/rest/config/folders/' + folder_id
        request = urllib.request.Request(endpoint, data=b'{"paused":true}', method='PATCH',
                                         headers={'X-API-Key': key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        request = urllib.request.Request(endpoint, headers={'X-API-Key': key})
        with urllib.request.urlopen(request, timeout=10) as response:
            if not json.load(response)['paused']:
                raise RuntimeError('Syncthing did not confirm folder pause')
    else:
        if paused is None:
            paused = ET.SubElement(folder, 'paused')
        paused.text = 'true'
        atomic_write(config_path, ET.tostring(tree, encoding='utf-8', xml_declaration=True),
                     stat.S_IMODE(config_path.stat().st_mode))
    return True


def apply(policy):
    if os.geteuid() != 0:
        raise RuntimeError('Root authentication is required')
    if socket.gethostname().split('.')[0] != policy['node']:
        raise RuntimeError('Policy belongs to another node')
    service = policy.get('service', 'k3s-agent.service')
    config = policy['kubelet']
    if config['kind'] != 'KubeletConfiguration' or config['apiVersion'] != 'kubelet.config.k8s.io/v1beta1':
        raise RuntimeError('Invalid kubelet configuration type')
    if not 0 < config['imageGCLowThresholdPercent'] < config['imageGCHighThresholdPercent'] < 100:
        raise RuntimeError('Invalid image garbage collection thresholds')
    if not KUBELET_CONFIG.parent.is_dir():
        raise RuntimeError('K3s kubelet configuration directory does not exist')
    backup = Path('/var/backups/homelab-node-disk-reserve') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(SYNCTHING_CONFIG, backup / 'syncthing-config.xml')
    previous = KUBELET_CONFIG.read_bytes() if KUBELET_CONFIG.exists() else None
    if previous is not None:
        shutil.copy2(KUBELET_CONFIG, backup / 'kubelet.conf')
    paused_changed = pause_folder(SYNCTHING_CONFIG, policy['folder'])
    content = (json.dumps(config, indent=2) + '\n').encode()
    changed = previous != content
    if changed:
        atomic_write(KUBELET_CONFIG, content, 0o600)
        try:
            subprocess.run(['systemctl', 'restart', service], check=True, timeout=90)
            subprocess.run(['systemctl', 'is-active', '--quiet', service], check=True)
        except (subprocess.SubprocessError, OSError):
            if previous is None:
                KUBELET_CONFIG.unlink(missing_ok=True)
            else:
                atomic_write(KUBELET_CONFIG, previous, 0o600)
            subprocess.run(['systemctl', 'restart', service], timeout=90)
            raise
    disk = os.statvfs('/srv/syncthing')
    return {'node': policy['node'], 'changed': changed or paused_changed, 'folder': policy['folder'],
            'paused': True, 'free_gib': round(disk.f_bavail * disk.f_frsize / 2**30, 2),
            'kubelet_config': str(KUBELET_CONFIG), 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = apply(json.loads(args.policy.read_text()))
        result['status'] = 'ok'
    except Exception as error:
        result = {'status': 'error', 'error': str(error)}
    if os.geteuid() == 0:
        atomic_write(RESULT, (json.dumps(result, indent=2) + '\n').encode(), 0o644)
    print(json.dumps(result))
    if result['status'] != 'ok':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
