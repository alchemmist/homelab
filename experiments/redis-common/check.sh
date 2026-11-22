#!/usr/bin/env bash
# Disposable transport contract. No published port, kubeconfig or production credentials.
set -euo pipefail
cd "$(dirname "$0")"
mode=${1:-transport}
case "$mode" in transport|proxy|failover) ;; *) echo "usage: $0 [transport|proxy|failover]" >&2; exit 2;; esac
proxy=harbor.socrat.alchemmist.xyz/homelab/litellm@sha256:21245d86b352d55f42404dfc7be5bcdb53028aa0be10077e9bb606c5e534e5f3
redis=docker.io/library/redis@sha256:52d1ea8a654b10f06af3ecda4e9dbcd035c7868b5c49ee7975de917f81de13db
d=$(mktemp -d); name=redis-probe-${d##*.}
cleanup() { docker rm -fv "$name-a" "$name-b" "$name-db" "$name-gw" "$name-r0" "$name-r1" "$name-r2" "$name" >/dev/null 2>&1 || :; docker network rm "$name" >/dev/null 2>&1 || :; rm -rf "$d"; }
trap cleanup EXIT
mkdir "$d/server" "$d/client"
for ca in ca other; do
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign -subj "/CN=$ca" -keyout "$d/$ca.key" -out "$d/client/$ca.crt" 2>/dev/null
done
openssl req -new -newkey rsa:2048 -nodes -subj /CN=redis-common -keyout "$d/server/key" -out "$d/server.csr" 2>/dev/null
printf 'subjectAltName=DNS:redis-common,DNS:redis-common-haproxy.redis.svc.cluster.local\nauthorityKeyIdentifier=keyid,issuer\nsubjectKeyIdentifier=hash\nextendedKeyUsage=serverAuth\n' >"$d/ext"
openssl x509 -req -in "$d/server.csr" -CA "$d/client/ca.crt" -CAkey "$d/ca.key" -CAcreateserial -days 1 -extfile "$d/ext" -out "$d/server/cert" 2>/dev/null
cp "$d/client/ca.crt" "$d/server/"; cp probe.py "$d/client/"
printf 'user default off\nuser litellm on >fixture ~probe:* +ping +incrby\n' >"$d/server/users"
if [[ $mode != transport ]]; then
  # Disposable private Redis, not the proposed production ACL.
  printf 'user default off\nuser litellm on >fixture ~* &* +@all -@admin -@dangerous\n' >"$d/server/users"
  cp proxy.yaml request.py "$d/client/"
fi
docker network create --internal "$name" >/dev/null
if [[ $mode == failover ]]; then
  source ./failover.sh
  source ./proxy-check.sh
  exit
fi
docker run -d --name "$name" --network "$name" --network-alias redis-common --network-alias wrong-name --user 0 -v "$d/server:/tls:ro" "$redis" redis-server --port 0 --tls-port 6379 --tls-cert-file /tls/cert --tls-key-file /tls/key --tls-ca-cert-file /tls/ca.crt --tls-auth-clients no --aclfile /tls/users >/dev/null
if [[ $mode == proxy ]]; then
  source ./proxy-check.sh
  exit
fi
for modes in first second,wrong-ca,wrong-name,bad-auth; do
  docker run --rm --platform linux/amd64 --network "$name" -e MODES="$modes" -e LITELLM_LOCAL_MODEL_COST_MAP=True -v "$d/client:/probe:ro" --entrypoint /app/.venv/bin/python "$proxy" /probe/probe.py
done
