import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('egress',ROOT/'scripts/vpn-home-transit-egress.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_only_home0_local_probe_uid_tcp443_is_exempt():
    with patch.object(m.socket,'gethostname',return_value='socrat-0'):new=m.rules()
    with patch.object(m.socket,'gethostname',return_value='socrat-1'):legacy=m.rules()
    bypass=' ip daddr 109.120.141.60 tcp dport 443 meta skuid 19091 counter return comment "homelab-direct-ip-probe"\n'
    assert new.replace(bypass,'')==legacy==m.rules(direct_probe=False)
    assert new.count(bypass)==1
    assert new.index('chain output') < new.index(bypass) < new.index('tcp dport 53',new.index('chain output'))
    assert 'skuid' not in new.split('chain output')[0]

def test_cas_migration_preserves_receipts_and_rejects_unreviewed_drift():
    source=(ROOT/'scripts/vpn-home-transit-egress.py').read_text()
    assert 'assert without == before' in source
    assert 'assert not receipt.exists()' in source
    assert "assert output_rules[0]['comment']" in source
    assert "assert (ROOT / 'rules.nft').read_text() == old" in source
    assert "assert added[0]['rule']['expr'] == expected_expr" in source
    assert 'delete table' not in source and 'flush ruleset' not in source
