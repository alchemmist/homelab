#!/usr/bin/env bash
# Run with a private directory containing <tier>.cms, .sha256, sealed WAL tar
# and markers (target UTC on first line). Only use authenticated archive inputs.
set -euo pipefail
umask 077
work=${1:?drill tier directory}; tier=${2:?tier}; [[ $tier =~ ^pg-(common|critical)$ ]]
cd "$work"; target=$(head -1 markers); [[ $target =~ ^[0-9:.+\ -]+$ ]]
key=${PG_DR_KEY:-$HOME/.config/homelab/pg-platform-dr/recipient.key}
image=ghcr.io/cloudnative-pg/postgresql:18.7-system-trixie@sha256:13f5dc1b42c5d96233724be976740df031136ca013f98a56a2877a62b362b453
shasum -a 256 -c "$tier.cms.sha256"
c=$(docker run -d --network none --user 26 --entrypoint sleep "$image" 3600)
trap 'docker rm -f "$c" >/dev/null' EXIT
docker exec "$c" sh -ec 'umask 077; mkdir /tmp/base /tmp/wal'
openssl cms -decrypt -binary -inform DER -in "$tier.cms" -inkey "$key" | docker exec -i "$c" tar -xzf - -C /tmp/base
docker exec "$c" /usr/lib/postgresql/18/bin/pg_verifybackup /tmp/base
while read -r item; do
  n=${item#./}; [[ $n == '' ]] && continue; [[ $n =~ ^([0-9A-F]{24}|[0-9A-F]{8}\.history)\.cms$ ]] || exit 1
  tar -xOf wal.tar "$item" | openssl cms -decrypt -binary -inform DER -inkey "$key" | gzip -dc | docker exec -i "$c" bash -c 'cat >"/tmp/wal/$1"' _ "${n%.cms}"
done < <(tar -tf wal.tar)
docker exec -i "$c" bash -se -- "$target" <<'PG'
set -eu
cd /tmp/base; chmod 700 .; rm -f standby.signal; touch recovery.signal; : >postgresql.auto.conf
printf 'local all all trust\n' >pg_hba.conf
cat >postgresql.conf <<CFG
listen_addresses=''
unix_socket_directories='/tmp'
ssl=off
archive_mode=off
hot_standby=on
max_connections=1000
max_worker_processes=64
max_wal_senders=32
max_prepared_transactions=200
max_locks_per_transaction=256
restore_command='cp /tmp/wal/%f %p'
recovery_target_time='$1'
recovery_target_timeline='current'
recovery_target_action='pause'
CFG
pg_ctl -D "$PWD" -l /tmp/dr-log -w start || { tail -18 /tmp/dr-log; exit 1; }
for i in $(seq 1 60); do
  [[ $(psql -h /tmp -d postgres -XAtqc 'select pg_get_wal_replay_pause_state()') == paused ]] && break
  sleep 1
done
out=$(psql -h /tmp -d postgres -XAtqc "select pg_is_in_recovery(),pg_get_wal_replay_pause_state(),array_agg(marker order by marker) from public.dr_accept_20261121_0912")
[[ $out == 't|paused|{1}' ]] || { echo "Unexpected result: $out"; exit 1; }
echo "PITR target $1: paused; marker 1 present, marker 2 absent"
pg_ctl -D "$PWD" -m immediate stop
PG
