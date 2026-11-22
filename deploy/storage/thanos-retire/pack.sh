#!/bin/bash
set -euo pipefail
umask 077
script_dir=$(dirname "$0")
cd "${script_dir}"
root=/var/lib/socrat-thanos
host=$(hostname -s)
test "${host}" = socrat-0
source_id=$(stat -c %d:%i "${root}")
test "${source_id}" = 66306:5507292
test ! -e raw.tar.zst
test ! -e raw.tar.zst.partial
python3 -c 'from pathlib import Path; from tree import *; f,d=shape(Path("/var/lib/socrat-thanos")); assert 45*2**30<sum(f.values())<60*2**30;print("source inventory",len(f),sum(f.values()),flush=True)'
available=$(df --output=avail -B1 . | tail -1)
test "${available}" -gt 150000000000
nice -n 12 ionice -c2 -n7 tar --one-file-system --numeric-owner -C "${root}" -cf - . | nice -n 12 zstd -q -3 -T3 -c >raw.tar.zst.partial
zstd -tq raw.tar.zst.partial
mkdir restore-check
zstd -qdc raw.tar.zst.partial | tar --no-same-owner -xf - -C restore-check
python3 - <<'PY'
from pathlib import Path
from tree import *
root=Path('/var/lib/socrat-thanos'); src=manifest(root); assert manifest(Path('restore-check'))==src
Path('manifest.json').write_text(json.dumps(src,sort_keys=True)); print('restored and independently verified',len(src['files']),'files',sum(n for n,h in src['files'].values()),'bytes manifest',digest(src),flush=True)
PY
mv raw.tar.zst.partial raw.tar.zst
sha256sum raw.tar.zst >archive.sha256
sync -f raw.tar.zst
# Remove only this run's scratch restore, using the exact verified manifest.
python3 - <<'PY'
from pathlib import Path
from tree import *
root=Path('restore-check');m=json.loads(Path('manifest.json').read_text());assert set(shape(root)[0])==set(m['files'])
for f in m['files']:(root/f).unlink()
for d in sorted(m['dirs'],key=lambda x:x.count('/'),reverse=True):(root/d).rmdir()
root.rmdir();Path('verified.sha256').write_text(digest(m)+'\n')
PY
sync -f .
date -u
