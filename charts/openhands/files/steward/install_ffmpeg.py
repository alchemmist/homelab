"""Extract one binary from a pinned wheel, no pip / postinstall or GitHub credential."""
import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

url="https://files.pythonhosted.org/packages/a0/2d/43c8522a2038e9d0e7dbdf3a61195ecc31ca576fb1527a528c877e87d973/imageio_ffmpeg-0.6.0-py3-none-manylinux2014_x86_64.whl"
p=Path(sys.argv[1])
p.parent.mkdir(parents=True,exist_ok=True)
# Restart-safe: the installed binary is read-only; replace it atomically.
tmp=p.with_name(p.name+".installing")
with urllib.request.urlopen(url,timeout=60) as r:data=r.read(30000000)
assert hashlib.sha256(data).hexdigest()=="c7e46fcec401dd990405049d2e2f475e2b397779df2519b544b8aab515195282"
with zipfile.ZipFile(io.BytesIO(data)) as z:
 names=[n for n in z.namelist() if n.startswith("imageio_ffmpeg/binaries/ffmpeg-linux")]
 assert len(names)==1
 with z.open(names[0]) as src,tmp.open("wb") as dst:
  shutil.copyfileobj(src,dst)
tmp.chmod(0o555)
tmp.replace(p)
