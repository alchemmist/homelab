"""TV-only presentation: do not trust raw overlapping gridPos or enable org anonymous."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'deploy/platform/grafana/public-entry/files/traffic-light-inset.js'

@pytest.mark.skipif(not shutil.which('node'), reason='Node is needed for JS runtime contract')
@pytest.mark.parametrize('mode', ['unrelated', 'not_opted_in', 'legacy', 'legacy_kiosk', 'legacy_edit', 'legacy_overlap', 'wrong_uid', 'public'])
def test_inset_runtime_scope_and_compacted_layout(mode):
    script = r'''
const fs=require('fs'),vm=require('vm'),mode=process.argv[1];
const token='a'.repeat(32), styles={}, calls=[];
const grid={style:{height:'106px'},parentElement:{style:{width:'400px'}},clientWidth:400,classList:{add(){}}};
const items=[{style:{transform:'translate(0px, 0px)',width:'26px',height:'68px'},parentElement:grid,getAttribute(){return 'grid-item-3'}},
 {style:{transform:'translate(0px, 76px)',width:'26px',height:'30px'},parentElement:grid,getAttribute(){return 'grid-item-4'}}];
const page={querySelectorAll(){return items}};
const model={uid:mode==='wrong_uid'?'another-dashboard':'socrat-traffic-light',panels:[{id:3,gridPos:{x:0,y:0,w:2,h:2}},{id:4,gridPos:{x:0,y:mode==='legacy_kiosk'?2:1,w:2,h:1}}]};
const location={pathname:mode.startsWith('legacy')?'/d/socrat-traffic-light':mode==='unrelated'?'/login':'/public-dashboards/'+token,
 search:mode==='legacy_kiosk'||mode==='legacy_overlap'?'?kiosk=1&autofitpanels=true':mode==='legacy_edit'?'?kiosk=1&autofitpanels=true&editPanel=3':mode==='not_opted_in'?'?kiosk=1':'?kiosk=1&socratTv=1'};
const document={getElementById:id=>styles[id],createElement:()=>({textContent:''}),head:{appendChild(s){styles[s.id]=s}},documentElement:{},
 querySelector:()=>page,querySelectorAll:selector=>selector.includes('react-grid-item')?items:[]};
const context={location,document,window:{addEventListener(){}},MutationObserver:function(){this.observe=()=>{}},
 XMLHttpRequest:function(){this.open=(m,p)=>calls.push([m,p]);this.send=()=>{this.status=200;this.responseText=JSON.stringify({dashboard:model});this.onload()}}};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
console.log(JSON.stringify({css:styles['socrat-tv-inset']?.textContent||'',calls}));
'''
    r = subprocess.run(['node', '-e', script, mode, str(JS)], check=True, capture_output=True, text=True)
    result = json.loads(r.stdout)
    if mode in ['unrelated', 'not_opted_in']:
        assert result == {'css': '', 'calls': []}
    else:
        assert 'padding:5px' in result['css']
        assert len(result['calls']) == (0 if mode in ['legacy', 'legacy_edit'] else 1)
        if mode == 'public':
            assert 'grid-template-rows:repeat(3,' in result['css']
            assert '[data-griditem-key="grid-item-4"]{grid-column:1 / span 2!important;grid-row:3 / span 1!important;}' in result['css']
            assert 'public-dashboard-footer' in result['css']
            assert 'pointer-events:none' in result['css']
        elif mode == 'legacy_kiosk':
            assert 'grid-template-rows:repeat(3,' in result['css']
            assert 'socrat-tv-auth-grid' in result['css']
            assert 'pointer-events:none' not in result['css']
            assert result['calls'] == [['GET', '/api/dashboards/uid/socrat-traffic-light']]
        else:
            assert 'grid-template-rows' not in result['css']

def test_only_one_dashboard_and_no_anonymous_org_fallback():
    s = (ROOT / 'scripts/grafana-tv-public.py').read_text()
    assert "UID='socrat-traffic-light'" in s
    assert "'annotationsEnabled':False" in s
    assert "'timeSelectionEnabled':False" in s
    assert 'Dashboard content changed during publication' in s
    assert 'Fresh exact plan approval required' in s
    assert "api('POST',endpoint,desired)" in s
    assert "api('POST','/api/dashboards/db'" not in s
    assert 'GF_AUTH_ANONYMOUS_ENABLED' not in s

def test_live_update_is_url_only_and_does_not_reprovision_tv():
    s = (ROOT / 'ansible/playbooks/tv-public-dashboard.yml').read_text()
    assert "{'startURL':tv_start_url}" in s
    assert 'tv_public_hash == tv_plan_hash' in s
    assert 'tv_network_after.stdout == tv_network_before.stdout' in s
    assert 'tv-uncertain.json' in s
    assert 'import_role' not in s and 'include_role' not in s
    assert 'adb install' not in s and 'settings put' not in s
    assert 'am force-stop de.ozerov.fully; am start -n de.ozerov.fully/.FullyActivity' in s
    assert 'initialScale' not in s and 'fontSize' not in s and 'injectJsCode' not in s

def test_no_dedicated_tv_alias_or_internal_vpn_in_helpers():
    import yaml
    from public_entry_contract import CHARTS, values
    assert not any(r['host']=='tv.alchemmist.xyz' for owner in CHARTS for r in values(owner)['routes'])
    for app in ['tv-mode','tv-grafana']:
        s=(ROOT/'android'/app/'smali/xyz/alchemmist/tvmode/SwitchVpn.smali').read_text()
        assert 'xiaomi-tv' not in s
        assert 'setWireguardAlwaysOn' not in s
        assert '"alchemmist-tv"' in s
        assert ':open_public' in s and '->launchDestination()V' in s

@pytest.mark.skipif(not shutil.which('node'), reason='Node is needed for JS runtime contract')
@pytest.mark.parametrize('mode', ['public', 'normal', 'auth_kiosk', 'wrong_uid', 'horizontal', 'missing_fill', 'duplicate_name'])
def test_compact_argo_is_guarded_public_tv_only_and_preserves_native_data(mode):
    script = r'''
const fs=require('fs'),vm=require('vm'),mode=process.argv[1],styles={};
const node=(style={})=>({style,children:[],classes:new Set(),classList:{add(c){this.owner.classes.add(c)}}});
const wire=n=>{n.classList.owner=n;return n};
const content=wire(node()),layout=wire(node()),row=wire(node({flexDirection:'row'}));
const fills=[],cells=[];
for(let i=0;i<3;i++){
 const fill=wire(node({background:'rgb(38, 120, 61)',width:'0.1px',height:'2px'}));fills.push(fill);
 const cell=wire(node());cell.querySelectorAll=s=>s==='a[title]'?[{title:mode==='duplicate_name'?'same':'app-'+i}]:mode==='missing_fill'?[]:[fill];cells.push(cell);
}
row.children=cells;layout.firstElementChild=row;
const root={querySelector:s=>s.includes('panel content')?content:layout};
const grid={style:{width:'503px'},parentElement:{style:{}},clientWidth:503,classList:{add(){}}};
const item={style:{transform:'translate(0px, 0px)',width:'503px',height:'30px'},parentElement:grid,getAttribute(){return 'grid-item-909'}};
const page={querySelectorAll:()=>[item]};
const model={uid:mode==='wrong_uid'?'other':'socrat-traffic-light',panels:[{id:909,type:'bargauge',gridPos:{x:0,y:0,w:12,h:1},options:{orientation:mode==='horizontal'?'horizontal':'vertical',displayMode:'gradient',namePlacement:'hidden',valueMode:'hidden'}}]};
const document={getElementById:id=>styles[id],createElement:()=>({textContent:''}),head:{appendChild(s){styles[s.id]=s}},documentElement:{},querySelector:s=>s.includes('panel-909')?root:page,querySelectorAll:s=>s.includes('react-grid-item')?[item]:[]};
const context={location:{pathname:['normal','auth_kiosk'].includes(mode)?'/d/socrat-traffic-light':'/public-dashboards/'+'a'.repeat(32),search:mode==='normal'?'':mode==='auth_kiosk'?'?kiosk=1&autofitpanels=true':'?socratTv=1'},document,window:{addEventListener(){}},MutationObserver:function(){this.observe=()=>{}},XMLHttpRequest:function(){this.open=()=>{};this.send=()=>{this.status=200;this.responseText=JSON.stringify({dashboard:model});this.onload()}}};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
console.log(JSON.stringify({css:styles['socrat-tv-inset']?.textContent||'',marked:row.classes.has('socrat-tv-argo-row'),fills:fills.map(n=>n.style),saved:model.panels[0].gridPos}));
'''
    r = subprocess.run(['node', '-e', script, mode, str(JS)], check=True, capture_output=True, text=True)
    result = json.loads(r.stdout)
    assert result['marked'] == (mode == 'public')
    assert ('gap:2px!important' in result['css']) == (mode == 'public')
    assert result['fills'] == [{'background': 'rgb(38, 120, 61)', 'width': '0.1px', 'height': '2px'}] * 3
    assert result['saved'] == {'x': 0, 'y': 0, 'w': 12, 'h': 1}
    if mode == 'public':
        assert '.socrat-tv-public-grid [data-viz-panel-id="panel-909"] ' in result['css']
        assert 'padding:3px!important' in result['css']
        assert 'flex:1 1 0!important' in result['css']
        assert 'socrat-tv-argo-cell a[data-testid="data-testid Data link"]' in result['css']
