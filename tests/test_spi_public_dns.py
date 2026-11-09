"""Offline exact SPI-only DNS addition across all ingress health combinations."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class SPIOnlyDNSTests(unittest.TestCase):
    def test_only_spi_changes_for_all_four_health_states(self):
        new = load(ROOT/'scripts/public_dns_zone.py', 'spi_zone')
        old = load(ROOT/'scripts/public_dns_zone.py', 'previous_zone')
        old.FAILOVER.remove('spi.socrat')
        guard = load(ROOT/'scripts/spi-public-dns.py','spi_guard')
        guard.delta(old,new)
        for home,vps in ((True,True),(True,False),(False,True),(False,False)):
            with self.subTest(home=home,vps=vps):
                before=old.render(123,home,vps).splitlines()
                after=new.render(123,home,vps).splitlines()
                self.assertEqual([r for r in after if not r.startswith('spi.socrat IN A ')],before)
                self.assertEqual([r for r in after if r.startswith('spi.socrat IN A ')],
                                 ['spi.socrat IN A '+a for a in old.healthy_addresses(home,vps)])
                self.assertNotIn('*.socrat', '\n'.join(after))
        new.TTL += 1
        with self.assertRaisesRegex(RuntimeError,'Unrelated DNS record change'):
            guard.delta(old,new)
