import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def prepare(image, destination):
    destination = Path(destination)
    marker = destination / '.homelab-image'
    if marker.exists() and marker.read_text().strip() == image:
        return False
    if destination.exists():
        raise RuntimeError('Existing recovery image differs; replace it only during explicit maintenance')
    with tempfile.TemporaryDirectory(prefix='vpn-image-', dir='/run') as mount:
        subprocess.run(['k3s', 'ctr', '--namespace', 'k8s.io', 'images', 'mount', image, mount], check=True, stdout=subprocess.DEVNULL)
        try:
            staging = Path(tempfile.mkdtemp(prefix='.runtime-', dir=destination.parent))
            try:
                subprocess.run(['cp', '-a', mount + '/.', str(staging)], check=True, stdout=subprocess.DEVNULL)
                if not (staging / 'app/x-ui').is_file():
                    raise RuntimeError('Recovery image has no /app/x-ui')
                (staging / '.homelab-image').write_text(image + '\n')
                os.rename(staging, destination)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        finally:
            subprocess.run(['k3s', 'ctr', 'images', 'unmount', mount], check=True, stdout=subprocess.DEVNULL)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('image')
    parser.add_argument('destination')
    args = parser.parse_args()
    print(json.dumps({'changed': prepare(args.image, args.destination)}))
