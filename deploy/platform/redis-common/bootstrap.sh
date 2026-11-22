#!/usr/bin/env bash
# First installation only. Never reset credentials or update an existing trust bundle.
set -euo pipefail
set +x
[[ $# == 1 && $1 == --create-missing ]] || { echo "usage: $0 --create-missing" >&2; exit 2; }
context=$(kubectl config current-context)
[[ ${context} == Socrat ]] || { echo 'wrong kube context' >&2; exit 1; }
k=(kubectl --context Socrat -n redis)
"${k[@]}" wait --for=condition=Ready certificate/redis-common-tls --timeout=120s
control=$("${k[@]}" get secret redis-common-control -o name --ignore-not-found)
if [[ -z ${control} ]]; then
  python3 - <<'PY' | "${k[@]}" create -f -
import json, secrets
print(json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':'redis-common-control'},
                  'stringData':{k:secrets.token_hex(32) for k in ('auth','sentinel-password')}}))
PY
fi
users=$("${k[@]}" get secret redis-common-users -o name --ignore-not-found)
if [[ -z ${users} ]]; then
  printf 'user litellm off\n' | "${k[@]}" create secret generic redis-common-users --from-file=client.conf=/dev/stdin
fi
# Read only the public certificate; pipe to a fresh Secret, never copy ca.key/tls.key.
ca=$("${k[@]}" get secret redis-common-ca -o jsonpath='{.data.tls\.crt}')
[[ -n ${ca} ]]
public=$("${k[@]}" get secret redis-common-public-ca -o name --ignore-not-found)
if [[ -z ${public} ]]; then
  printf '%s' "${ca}" | openssl base64 -d -A | "${k[@]}" create secret generic redis-common-public-ca --from-file=ca.crt=/dev/stdin
fi
bundle=$("${k[@]}" get secret redis-common-public-ca -o jsonpath='{.data.ca\.crt}')
[[ ${bundle} == "${ca}" ]] || { echo 'CA mismatch: use staged rotation, not bootstrap' >&2; exit 1; }
