#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /archive
mkdir -p spool sealed
# Avoid publishing bogus progress if disks fill. Keep the newest completed WAL
# as pg_receivewal's restart cursor; no slot can hold pg_wal hostage on primary.
export PGSSLKEY=/tmp/replication.key
install -m 0600 /tls/tls.key "$PGSSLKEY"
pg_receivewal --directory=spool --dbname="host=$TIER-rw.postgres.svc.cluster.local user=streaming_replica application_name=dr_wal_receiver sslmode=verify-full sslcert=/tls/tls.crt sslkey=$PGSSLKEY sslrootcert=/ca/ca.crt" --no-loop --verbose &
receiver=$!; trap 'kill "$receiver" 2>/dev/null || true; wait "$receiver" 2>/dev/null || true' EXIT
shopt -s nullglob
while kill -0 "$receiver" 2>/dev/null; do
  files=(spool/????????????????????????); newest=''
  if ((${#files[@]})); then newest=${files[${#files[@]}-1]}; fi
  for f in "${files[@]}" spool/????????.history; do
    n=${f#spool/}; [[ $n =~ ^([0-9A-F]{24}|[0-9A-F]{8}\.history)$ ]] || exit 65
    if [[ ! -f sealed/$n.cms ]]; then
      tmp=$(mktemp sealed/.tmp.XXXXXXXX)
      if ! gzip -1c "$f" | openssl cms -encrypt -binary -stream -outform DER -aes256 /config/recipient.crt >"$tmp"; then rm -f "$tmp"; exit 1; fi
      sync -f "$tmp"; mv -T "$tmp" "sealed/$n.cms"; sync -f sealed
      echo "archived $n"
    fi
    if [[ $f != "$newest" && $n != *.history ]]; then rm -f -- "$f"; fi
  done
  # Reconnect with the rotated client key, resuming from on-disk cursor.
  cmp -s /tls/tls.key "$PGSSLKEY" || exit 1
  sleep 3
done
wait "$receiver"; exit 1
