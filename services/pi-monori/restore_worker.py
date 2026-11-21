"""Rehydrate only the empty worker pod's scratch volume. Never import worker files on host."""
import hashlib, subprocess, types
PIN='5446e880afaaf2e640fa4e1f7fac54b3100aa67e20adc8327e744fd8fd7aa46e'

def ensure(c: types.ModuleType) -> None:
 for role in ('judge','author'):
  args=['kubectl','-n','openhands','exec','-i','deploy/pi-monori-'+role,'-c','sandbox','--'];p=c.K(role,['test','-x','/scratch/monori/.venv/bin/python'],ok=False)
  if p.returncode:
   if p.returncode!=1 or 'command terminated with exit code 1' not in p.stderr:raise RuntimeError('worker transport unavailable')
   archive=c.R/'deps.tar.gz';h=hashlib.sha256()
   with archive.open('rb') as src:
    for block in iter(lambda:src.read(2**20),b''):h.update(block)
   if h.hexdigest()!=PIN:raise RuntimeError('Offline dependency checksum mismatch')
   c.K(role,['sh','-ec','mkdir -p /scratch/monori /scratch/home;: >/scratch/rehydrate.tmp'])
   with archive.open('rb') as src:
    for block in iter(lambda:src.read(2**21),b''):subprocess.run(args+['sh','-ec','cat >> /scratch/rehydrate.tmp'],input=block,check=True,timeout=60)
   c.K(role,['sh','-ec','echo "$1  /scratch/rehydrate.tmp"|sha256sum -c -;tar xzf /scratch/rehydrate.tmp -C /scratch/monori;rm /scratch/rehydrate.tmp','sh',PIN]);
 c.K('author',['sh','-ec','mkdir -p /scratch/home/.pi/agent; cp /code/models.json /scratch/home/.pi/agent/models.json; test -d /scratch/base.git || git clone --bare --depth=1 https://github.com/alchemmist/monori.git /scratch/base.git; test -x /scratch/tools/ruff/bin/ruff || UV_TOOL_DIR=/scratch/tools UV_TOOL_BIN_DIR=/scratch/toolbin uv tool install ruff==0.17.5;test "$(/scratch/tools/ruff/bin/ruff --version)" = "ruff 0.17.5"'],timeout=180)
