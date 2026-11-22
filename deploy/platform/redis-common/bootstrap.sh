#!/usr/bin/env bash
# First installation only. Never reset credentials or update an existing trust bundle.
set -euo pipefail
set +x
[[ $# == 1 && $1 == --create-missing ]] || { echo "usage: $0 --create-missing" >&2; exit 2; }
[[ $(kubectl config current-context) == Socrat ]] || { echo 'wrong kube context' >&2; exit 1; }
k=(kubectl --context Socrat -n redis)
"${k[@]}" wait --for=condition=Ready certificate/redis-common-tls --timeout=120s
missing() { local obj; obj=$("${k[@]}" get secret "$1" -o name --ignore-not-found) || exit 1; [[ -z $obj ]]; }
if missing redis-common-control; then
  python3 - <<'PY' | "${k[@]}" create -f -
import json, secrets
print(json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':'redis-common-control'},
                  'stringData':{k:secrets.token_hex(32) for k in ('auth','sentinel-password')}}))
PY
fi
if missing redis-common-users; then
  printf 'user litellm off\n' | "${k[@]}" create secret generic redis-common-users --from-file=client.conf=/dev/stdin
fi
# Read only the public certificate; pipe to a fresh Secret, never copy ca.key/tls.key.
ca=$("${k[@]}" get secret redis-common-ca -o jsonpath='{.data.tls\.crt}')
[[ -n $ca ]]
if missing redis-common-public-ca; then
  printf '%s' "$ca" | openssl base64 -d -A | "${k[@]}" create secret generic redis-common-public-ca --from-file=ca.crt=/dev/stdin
fi
[[ $("${k[@]}" get secret redis-common-public-ca -o jsonpath='{.data.ca\.crt}') == "$ca" ]] || { echo 'CA mismatch: use staged rotation, not bootstrap' >&2; exit 1; }
