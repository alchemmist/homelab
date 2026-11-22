#!/usr/bin/env bash
set -euo pipefail
d=$1 name=$2 redis=$3
# Disposable topology, using actual rendered server, Sentinel and HAProxy configs.
root=../..; platform=${root}/deploy/platform/redis-common
chart=${REDIS_HA_CHART:-redis-ha}
args=()
if [[ ${chart} == redis-ha ]]; then args=(--repo https://dandydeveloper.github.io/charts --version 4.39.0); fi
helm template redis-common "${chart}" ${args[@]+"${args[@]}"} -n redis -f "${platform}/values.yaml" >"${d}/render"
"${PYTHON:-${root}/.venv/bin/python}" - "${d}" <<'PY'
import pathlib, sys, yaml
p = pathlib.Path(sys.argv[1]); docs = yaml.safe_load_all((p/'render').read_text())
cfg = next(x['data'] for x in docs if x and x['metadata']['name']=='redis-common-configmap')
for k in ('redis.conf','sentinel.conf','haproxy.cfg'):
    (p/'server'/k).write_text(cfg[k].replace('replace-default-auth','control').replace('replace-default-sentinel-auth','voter'))
PY
cp "${d}/server/cert" "${d}/server/tls.crt"; cp "${d}/server/key" "${d}/server/tls.key"
printf 'user litellm on >fixture ~* &* +@all -@admin -@dangerous\n' >"${d}/server/client.conf"
for i in 0 1 2; do
  docker run -d --user 0 --network "${name}" --network-alias "redis-common-announce-${i}" --name "${name}-r${i}" \
    -v "${d}/server:/tls-certs:ro" -v "${d}/server:/users:ro" "${redis}" sleep infinity >/dev/null
  ip=$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${name}-r${i}")
  if [[ ${i} == 0 ]]; then first_ip=${ip}; fi
  sed "s/REPLACE_ANNOUNCE${i}/${ip}/g" "${d}/server/haproxy.cfg" >"${d}/tmp" && cat "${d}/tmp" >"${d}/server/haproxy.cfg"
  docker exec "${name}-r${i}" sh -ec 'cp /tls-certs/redis.conf /data/redis.conf; if [ "$1" != 0 ]; then echo "replicaof $2 6379" >>/data/redis.conf; fi
    { echo "sentinel monitor redis-common $2 6379 2"; cat /tls-certs/sentinel.conf; } >/data/sentinel.conf' sh "${i}" "${first_ip}"
  docker exec -d "${name}-r${i}" redis-server /data/redis.conf
  docker exec -d "${name}-r${i}" redis-sentinel /data/sentinel.conf
done
ha=docker.io/library/haproxy@sha256:7816a9801a6846b912bc37e48529808e2fa87c3c47992441940f68e393ebcfeb
docker run -d --name "${name}-gw" --network "${name}" --network-alias redis-common -e AUTH=control -e SENTINELAUTH=voter \
  -v "${d}/server/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" -v "${d}/client:/trust:ro" "${ha}" >/dev/null
