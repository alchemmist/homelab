#!/usr/bin/env bash
set -euo pipefail
d=$1 name=$2 proxy=$3 mode=$4
writer=(docker exec -e REDISCLI_AUTH=fixture "${name}-r1" redis-cli --tls --cacert /tls-certs/ca.crt -h redis-common --user litellm)
if [[ ${mode} == failover ]]; then
  start=${SECONDS}
  until reply=$("${writer[@]}" SET probe:before preserved 2>/dev/null) && [[ ${reply} == OK ]]; do
    (( SECONDS - start < 75 )) || { docker logs --tail 20 "${name}-gw" >&2; exit 1; }; sleep 1
  done
fi
pg=docker.io/library/postgres@sha256:266d3c257594e195b309ae9d1805e54c788f1d7b375f56bf6c367aac6c917e7b
docker run -d --name "${name}-db" --network "${name}" --network-alias fixture-db -e POSTGRES_PASSWORD=fixture "${pg}" >/dev/null
for _ in {1..60}; do docker exec "${name}-db" pg_isready -U postgres >/dev/null && break; sleep 1; done
for worker in a b; do
  docker run -d --platform linux/amd64 --network "${name}" --name "${name}-${worker}" \
    -v "${d}/client:/probe:ro" -e MASTER_KEY=sk-fixture-master -e LITELLM_LOCAL_MODEL_COST_MAP=True -e LITELLM_TELEMETRY=False \
    -e DATABASE_URL=postgresql://postgres:fixture@fixture-db:5432/postgres \
    -e 'TEST_REDIS_URL=rediss://litellm:fixture@redis-common:6379/0?ssl_ca_certs=/probe/ca.crt&ssl_check_hostname=true&ssl_cert_reqs=required' \
    "${proxy}" --config /probe/proxy.yaml --port 4000 --num_workers 1 >/dev/null
  ready=false
  for _ in {1..180}; do
    docker exec "${name}-${worker}" /app/.venv/bin/python -c 'from urllib.request import urlopen; urlopen("http://localhost:4000/health/readiness",timeout=3)' 2>/dev/null && { ready=true; break; }
    running=$(docker inspect -f '{{.State.Running}}' "${name}-${worker}")
    [[ ${running} == true ]] || break
    sleep 2
  done
  if [[ ${ready} != true ]]; then docker logs --tail 40 "${name}-${worker}" >&2; exit 1; fi
done
call() { docker exec -i "${name}-$1" /app/.venv/bin/python /probe/request.py "$2"; }
key=$(call a key </dev/null)
a=$(call a chat <<<"${key}"); b=$(call b chat <<<"${key}")
printf 'RPM=1 across two proxies: A=%s B=%s\n' "${a}" "${b}"
[[ ${a} == 200 && ${b} == 429 ]]
if [[ ${mode} == failover ]]; then
  value=$("${writer[@]}" GET probe:before 2>/dev/null)
  [[ ${value} == preserved ]]
  docker stop -t 1 "${name}-r0" >/dev/null  # removes primary AND one voter
  start=${SECONDS}
  until reply=$("${writer[@]}" SET probe:after recovered 2>/dev/null) && [[ ${reply} == OK ]]; do
    (( SECONDS - start < 120 )) || { echo 'No new writer in 120s' >&2; exit 1; }
    sleep 1
  done
  echo "Writer accepting writes after $((SECONDS-start)) s"
  value=$("${writer[@]}" GET probe:before 2>/dev/null)
  [[ ${value} == preserved ]]
  key=$(call a key </dev/null)
  a=$(call a chat <<<"${key}"); b=$(call b chat <<<"${key}")
  printf 'Same running proxies, new primary: A=%s B=%s\n' "${a}" "${b}"
  [[ ${a} == 200 && ${b} == 429 ]]
  exit
fi
# Same worker boundary and quota, but drop Redis between the two requests.
key=$(call a key </dev/null)
status=$(call a chat <<<"${key}")
[[ ${status} == 200 ]]
docker stop -t 1 "${name}" >/dev/null
b=$(call b chat <<<"${key}")
printf 'Redis stopped mid-window: B=%s\n' "${b}"
case "${b}" in 200) echo 'FAIL OPEN: second completion admitted';; 429) echo 'Second request rejected by limiter';; *) echo 'Request unavailable during Redis outage';; esac
