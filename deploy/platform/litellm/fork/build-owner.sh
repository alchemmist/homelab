#!/bin/sh
# The parent is the previously verified Generic OIDC fork. Requires crane v0.20.6.
set -eu
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT; cd "$d"
rev=fbbf40f35bd1e871f4f4a994f9be30d7ea225a25
repo=harbor.socrat.alchemmist.xyz/homelab/litellm
base=sha256:f1bc742715223bf9a16236670493c7d6b75b4e7f995764f7c678cb6ca60ad174
root=app/.venv/lib/python3.13/site-packages
fetch() {
  mkdir -p "$(dirname "$root/$1")"
  gh api -H "Accept: application/vnd.github.raw+json" "repos/alchemmist/litellm/contents/$1?ref=$rev" > "$root/$1"
  echo "$2  $root/$1" | shasum -a 256 -c -
}
fetch litellm/proxy/management_endpoints/key_management_endpoints.py e8a4e7bddc095af840b439ecb3edc14c512759ab31328c0cdb618f6350621a02
fetch litellm/proxy/_experimental/out/_next/static/chunks/28ytusy1jm5e9.js 29a8cf2754a874fb1beb80d457425f51e6bf73c90156137f52b362b1d1b1df9c
python3 - <<'PYTAR'
import io,tarfile,pathlib
with tarfile.open('layer.tar','w',format=tarfile.USTAR_FORMAT) as archive:
    for p in sorted(pathlib.Path('app').rglob('*')):
        if p.is_file():
            b=p.read_bytes(); t=tarfile.TarInfo(str(p)); t.size=len(b); t.mode=0o644
            archive.addfile(t,io.BytesIO(b))
PYTAR
crane append --base "$repo@$base" --new_layer layer.tar --new_tag "$repo:$rev" --platform linux/amd64
crane digest "$repo:$rev"
