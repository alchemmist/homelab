"""Upload pinned local service icons; users' browsers do not contact a third-party CDN."""
import hashlib,json,sys,urllib.request,uuid
from pathlib import Path
root=Path(sys.argv[1]);assets=root/'service-icons'
credentials=json.loads((root/'credentials.json').read_text());services=json.loads((root/'services.json').read_text())
headers={'Authorization':'Bearer '+credentials['AUTHENTIK_BOOTSTRAP_TOKEN']}
base='https://auth.socrat.alchemmist.xyz/api/v3/'
req=urllib.request.Request(base+'admin/file/?usage=media',headers=headers)
with urllib.request.urlopen(req,timeout=60) as r:existing=json.load(r)
existing_names={f['name'] for f in existing}
for slug,service in services.items():
    if 'icon' not in service:continue
    content=(assets/(slug+'.svg')).read_bytes()
    expected=json.loads((assets/'sources.json').read_text())['files'][slug+'.svg']['sha256']
    if hashlib.sha256(content).hexdigest()!=expected:raise RuntimeError('Icon checksum mismatch')
    name=service['icon']
    if name in existing_names:continue
    boundary='socrat-'+uuid.uuid4().hex
    parts=[]
    for key,value in [('name',name),('usage','media')]:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{slug}.svg"\r\nContent-Type: image/svg+xml\r\n\r\n'.encode()+content+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    req=urllib.request.Request(base+'admin/file/',method='POST',data=b''.join(parts),
        headers={**headers,'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(req,timeout=60) as r:r.read()
print('Pinned service icons uploaded to local Authentik media storage')
