import json,pathlib,unittest
import yaml
from jinja2 import Environment,StrictUndefined
ROOT=pathlib.Path(__file__).resolve().parents[1]
class BootstrapTests(unittest.TestCase):
 def test_manifest_matches_inventory_and_scoped_template(self):
  m=json.loads((ROOT/'deploy/network/socrat-5-bootstrap.json').read_text())
  v={}
  for f in ['ansible/roles/wireguard_socrat/defaults/main.yml','ansible/inventory/group_vars/Socrat.yml','ansible/inventory/host_vars/socrat-4.yml']:v.update(yaml.safe_load((ROOT/f).read_text()))
  self.assertEqual(v['wg_socrat_bootstrap_peers'][m['name']],{'address':m['address'],'public_key':m['public_key']})
  v.update(inventory_hostname='socrat-4',wg_socrat_private_key='TEST_ONLY_NOT_A_KEY')
  rendered=Environment(undefined=StrictUndefined).from_string((ROOT/'ansible/roles/wireguard_socrat/templates/wg-socrat.conf.j2').read_text()).render(v)
  self.assertEqual(rendered.count(m['public_key']),1)
  self.assertIn('AllowedIPs = 10.250.0.41/32',rendered)
  self.assertNotIn('0.0.0.0/0',rendered)
  for name,p in v['wg_socrat_nodes'].items():
   if name!='socrat-4':self.assertIn(p['public_key'],rendered)
 def test_guard_is_pre_dnat_and_source_scoped(self):
  s=(ROOT/'scripts/testing-class-wg-guard.sh').read_text()
  self.assertIn('-t mangle -I PREROUTING 1 -i wg-socrat -s 10.250.0.41/32',s)
  self.assertIn('--sport 22 -m conntrack --ctstate ESTABLISHED',s)
  self.assertIn('-d 10.250.0.40/32',s)
  self.assertIn('-A "$CHAIN" -j DROP',s)
  for bad in ['iptables-restore',' -F ',' -P ','MASQUERADE','--dport 6443']:self.assertNotIn(bad,s)
 def test_peer_admission_is_cas_and_no_transport_restart(self):
  s=(ROOT/'scripts/wg-testing-class-admit.py').read_text()
  self.assertIn('==EXPECTED',s)
  self.assertIn("'peer',KEY,'allowed-ips',IP",s)
  self.assertIn('current==original',s)
  for bad in ["'syncconf'","'restart'","'down'","'up'"]:self.assertNotIn(bad,s)
 def test_guard_declared_before_transport_on_boot(self):
  s=(ROOT/'ansible/playbooks/testing-class-bootstrap-guard.yml').read_text()
  self.assertIn('Requires=testing-class-wg-guard.service',s)
  self.assertIn('Before=wg-quick@wg-socrat.service',s)
  self.assertNotIn('state: restarted',s)
if __name__=='__main__':unittest.main()
