#!/bin/sh
# crane v0.20.6; GNU tar. Caller supplies registry login.
set -eu
d=$(mktemp -d); trap 'rm -rf "${d}"' EXIT
cd "${d}"
rev=6675023dfafac962781c33f7bf57743e57e80e19
p=app/.venv/lib/python3.13/site-packages/litellm/proxy/management_endpoints/ui_sso.py
mkdir -p "$(dirname "${p}")"
gh api -H "Accept: application/vnd.github.raw+json" "repos/alchemmist/litellm/contents/litellm/proxy/management_endpoints/ui_sso.py?ref=${rev}" > "${p}"
echo "93dd4fc3621c18a535401113f3764ed54d4e924b306bbc99a5a43698f4225fe7  ${p}"|sha256sum -c -
tar --owner=0 --group=0 --mode=0644 --mtime=@0 -cf layer.tar "${p}"
crane append --base ghcr.io/berriai/litellm@sha256:b4239fbb9be0d915c312632ccdcccea441db9994a341536fdbf32cae82e15f9c --new_layer layer.tar --new_tag "harbor.socrat.alchemmist.xyz/homelab/litellm:${rev}" --platform linux/amd64
crane digest "harbor.socrat.alchemmist.xyz/homelab/litellm:${rev}"
