#!/bin/sh
# The parent is the previously verified Generic OIDC fork. Requires crane v0.20.6.
set -eu
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT; cd "${d}"
rev=eb6e7f61e4fa0fa1425461e4e92145c8eab73bef
repo=harbor.socrat.alchemmist.xyz/homelab/litellm
base=sha256:21245d86b352d55f42404dfc7be5bcdb53028aa0be10077e9bb606c5e534e5f3
root=app/.venv/lib/python3.13/site-packages
fetch() {
  mkdir -p "$(dirname "${root}/$1")"
  git -C "${FORK_CHECKOUT:?set absolute path to verified fork checkout}" show "${rev}:$1" > "${root}/$1"
  echo "$2  ${root}/$1" | shasum -a 256 -c -
}
fetch litellm/proxy/management_endpoints/key_management_endpoints.py bd920df312de3095037d25f65c068539fa32460c23f86402f8f301cbeadcc189
python3 - <<'PYTAR'
import io,tarfile,pathlib
with tarfile.open('layer.tar','w',format=tarfile.USTAR_FORMAT) as archive:
    for p in sorted(pathlib.Path('app').rglob('*')):
        if p.is_file():
            b=p.read_bytes(); t=tarfile.TarInfo(str(p)); t.size=len(b); t.mode=0o644
            archive.addfile(t,io.BytesIO(b))
PYTAR
crane append --base "${repo}@${base}" --new_layer layer.tar --new_tag "${repo}:${rev}" --platform linux/amd64
crane digest "${repo}:${rev}"
