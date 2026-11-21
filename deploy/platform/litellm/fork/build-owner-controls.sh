#!/bin/sh
# The parent is the previously verified Generic OIDC fork. Requires crane v0.20.6.
set -eu
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT; cd "$d"
rev=a691e23abfac6dd0f2b69f9f5b4f714241f39ac4
repo=harbor.socrat.alchemmist.xyz/homelab/litellm
base=sha256:e982dddf6a3da10ea76fa4c9b5f05ab166a128b83f653cd0e07e96493e6506d9
root=app/.venv/lib/python3.13/site-packages
fetch() {
  mkdir -p "$(dirname "$root/$1")"
  gh api -H "Accept: application/vnd.github.raw+json" "repos/alchemmist/litellm/contents/$1?ref=$rev" > "$root/$1"
  echo "$2  $root/$1" | shasum -a 256 -c -
}
fetch litellm/proxy/socrat_owner.py b1d6665d916395b20c7bde2cf4bf1b848cda990b7d403cc53b6f01ddbb9edbbe
fetch litellm/proxy/management_endpoints/key_management_endpoints.py 75fa3822dfc16ec8003760b63500e8086994e232adfed88fdd4d59872b3e9c6f
fetch litellm/proxy/spend_tracking/spend_management_endpoints.py 738977e682a463b870792477cdc2b33b9eb7c1fc336c99b850068de79f27203b
fetch litellm/proxy/_experimental/out/_next/static/chunks/28ytusy1jm5e9.js 15092eea542127503bf78f6f8b8f0d16d89084b21c00e67e09b16df2012f9837
fetch litellm/proxy/_experimental/out/_next/static/chunks/33aje6ne5gt1-.js 92dfc1217f3ce287cbd68a606017ed5ea660b732281a0016ae73349a63bcc46c
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
