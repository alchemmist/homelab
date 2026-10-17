#!/usr/bin/python3
import argparse
import gzip
import lzma
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

DKMS_NAME = 'homelab-alx'
DKMS_VERSION = '6.12.111-1'
BOARD_PATH = Path('/sys/class/dmi/id/board_name')
LOADED_NOTE = Path('/sys/module/alx/notes/.note.gnu.build-id')
WIFI_PARAMETERS = Path('/sys/module/rtl8723ae/parameters')


def run(arguments):
    return subprocess.run(arguments, check=True, capture_output=True, timeout=30).stdout


def module_note(path):
    data = path.read_bytes()
    if path.suffix == '.xz':
        data = lzma.decompress(data)
    elif path.suffix == '.gz':
        data = gzip.decompress(data)
    elif path.suffix == '.zst':
        data = run(['zstd', '--decompress', '--stdout', str(path)])
    with tempfile.TemporaryDirectory(prefix='homelab-alx-identity-') as temporary:
        directory = Path(temporary)
        source = directory / 'alx.ko'
        note = directory / 'build-id'
        source.write_bytes(data)
        run(['objcopy', '--dump-section', f'.note.gnu.build-id={note}', str(source), str(directory / 'copy.ko')])
        value = note.read_bytes()
        if not value:
            raise RuntimeError('ALX module has no GNU build-id note')
        return value


def validate():
    if os.geteuid() != 0:
        raise RuntimeError('This guard must run as root')
    if BOARD_PATH.read_text().strip() != 'MS-16GP':
        raise RuntimeError('Unexpected motherboard')
    kernel = platform.release()
    status = run(['dkms', 'status', '-m', DKMS_NAME, '-v', DKMS_VERSION, '-k', kernel]).decode()
    expected = f'{DKMS_NAME}/{DKMS_VERSION}, {kernel}, {platform.machine()}: installed'
    accepted = {expected, expected + ' (Original modules exist)'}
    if not accepted.intersection(line.strip() for line in status.splitlines()):
        raise RuntimeError(f'Required ALX DKMS module is not installed for {kernel}')
    path = Path(run(['modinfo', '-n', 'alx']).decode().strip()).resolve(strict=True)
    directory = (Path('/lib/modules') / kernel / 'updates/dkms').resolve()
    if path.parent != directory or path.name not in ('alx.ko', 'alx.ko.xz', 'alx.ko.zst', 'alx.ko.gz'):
        raise RuntimeError('ALX resolves outside the current kernel DKMS directory')
    expected_note = module_note(path)
    run(['modprobe', 'alx'])
    if LOADED_NOTE.read_bytes() != expected_note:
        raise RuntimeError('Loaded ALX build-id differs from the guarded DKMS module; reboot required')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    arguments = parser.parse_args()
    try:
        validate()
        if not arguments.check:
            run(['modprobe', 'rtl8723ae', 'msi=1', 'ips=0', 'fwlps=0', 'swlps=0'])
            for name, expected in {'msi': 'Y', 'ips': 'N', 'fwlps': 'N', 'swlps': 'N'}.items():
                if (WIFI_PARAMETERS / name).read_text().strip() != expected:
                    raise RuntimeError(f'Loaded Wi-Fi parameter {name} differs from guarded configuration; no automatic reload attempted')
    except (OSError, RuntimeError, ValueError, EOFError, lzma.LZMAError, subprocess.SubprocessError) as error:
        print(f'Wi-Fi guard refused activation: {error}', file=sys.stderr)
        return 1
    print('Guarded ALX identity verified' if arguments.check else 'Guarded Wi-Fi module loaded')
    return 0


if __name__ == '__main__':
    sys.exit(main())
