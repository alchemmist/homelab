#!/bin/sh
# Only the isolated HA target is overwritten; legacy production is read-only.
set -eu
umask 077
: "${BACKUP_ID:?}" "${SOURCE_PASSWORD:?}" "${TARGET_PASSWORD:?}"
case "$BACKUP_ID" in *[!a-zA-Z0-9_-]*|'') exit 64;; esac
mkdir -p /backups/lms
file="/backups/lms/$BACKUP_ID.dump.gpg"
export GNUPGHOME=/tmp/gnupg
mkdir -m 700 "$GNUPGHOME"
test ! -e "$file"
export PGUSER=lms PGDATABASE=lms PGCONNECT_TIMEOUT=5
export PGPASSWORD="$SOURCE_PASSWORD" PGHOST=lms-postgres.lms.svc.cluster.local PGSSLMODE=prefer
pg_dump --format=custom --no-owner --no-acl --file=/tmp/source.dump
pg_restore --list /tmp/source.dump >/dev/null
gpg --batch --no-tty --pinentry-mode loopback --passphrase-file /backup-key/passphrase --symmetric --cipher-algo AES256 --output "$file.partial" /tmp/source.dump
mv "$file.partial" "$file"
gpg --batch --no-tty --pinentry-mode loopback --passphrase-file /backup-key/passphrase --decrypt --output /tmp/recovered.dump "$file"
cmp /tmp/source.dump /tmp/recovered.dump
rm /tmp/source.dump
sha256sum "$file" | awk '{print "backupSHA256=" $1}'
cat > /tmp/fingerprint.sql <<'SQL'
SELECT format('SELECT %L,count(*)::text,md5(coalesce(string_agg(to_jsonb(t)::text,E''\n'' ORDER BY to_jsonb(t)::text),'''')) FROM %I.%I t;',table_name,table_schema,table_name)
FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name;
\gexec
SQL
# -q suppresses query command tags; no row values leave the database except digests.
psql -X -qAt -f /tmp/fingerprint.sql > /tmp/source.fingerprint
export PGPASSWORD="$TARGET_PASSWORD" PGHOST=lms-ha-rw.lms.svc.cluster.local PGSSLMODE=verify-full PGSSLROOTCERT=/etc/postgres-ca/ca.crt
pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --single-transaction --dbname=lms /tmp/recovered.dump 2>/tmp/restore.stderr || { echo restoreFailed=true; exit 1; }
psql -X -qAt -f /tmp/fingerprint.sql > /tmp/target.fingerprint
# The final copy requires a write freeze. Staging may have concurrent source writes.
if [ "${REQUIRE_EXACT_MATCH:-1}" = 1 ]; then
  cmp /tmp/source.fingerprint /tmp/target.fingerprint >/dev/null
  echo logicalDataFingerprintMatched=true
else
  echo rehearsalRestoreCompleted=true
fi
sha256sum /tmp/target.fingerprint | awk '{print "targetFingerprintSHA256=" $1}'
echo tlsVerified=true
