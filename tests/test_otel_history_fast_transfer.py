import importlib.util
from pathlib import Path
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('fast_transfer', ROOT / 'scripts/otel-history-fast-transfer.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class FastHistoryTransferTests(unittest.TestCase):
    def test_only_fixed_completed_history_inputs_allowed(self):
        helper = module()
        self.assertTrue(helper.allowed(tarfile.TarInfo(str(helper.WORK / 'restored' / helper.BLOCK / 'meta.json').lstrip('/'))))
        for name in ['etc/shadow', 'var/lib/homelab-otel/tls/client.key', '../etc/shadow', '/etc/shadow',
                     str(helper.FINAL / 'final-result.json').lstrip('/'), str(helper.TAIL / 'result.json').lstrip('/')]:
            self.assertFalse(helper.allowed(tarfile.TarInfo(name)))

    def test_archive_links_devices_and_traversal_rejected(self):
        helper = module()
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]:
            member = tarfile.TarInfo(str(helper.CURRENT / 'result.json').lstrip('/'))
            member.type = kind
            self.assertFalse(helper.allowed(member))
        self.assertFalse(helper.allowed(tarfile.TarInfo(str(helper.CURRENT).lstrip('/') + '/../other')))
