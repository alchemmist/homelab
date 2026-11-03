#!/bin/sh
set -eu
umask 077
export PGUSER=lms PGDATABASE=lms PGHOST=lms-ha-rw.lms.svc.cluster.local PGSSLMODE=verify-full PGSSLROOTCERT=/etc/postgres-ca/ca.crt PGCONNECT_TIMEOUT=5
export GNUPGHOME=/tmp/gnupg
mkdir -m 700 "$GNUPGHOME"
mkdir -p /backups/lms
file="/backups/lms/scheduled-$(date -u +%Y%m%dT%H%M%SZ).dump.gpg"
test ! -e "$file"
pg_dump --format=custom --no-owner --no-acl --file=/tmp/database.dump
pg_restore --list /tmp/database.dump >/dev/null
gpg --batch --no-tty --pinentry-mode loopback --passphrase-file /backup-key/passphrase --symmetric --cipher-algo AES256 --output "$file.partial" /tmp/database.dump
mv "$file.partial" "$file"
gpg --batch --no-tty --pinentry-mode loopback --passphrase-file /backup-key/passphrase --decrypt --output /tmp/checked.dump "$file"
cmp /tmp/database.dump /tmp/checked.dump
sha256sum "$file" | awk '{print "encryptedBackupSHA256=" $1}'
# Only this job's scheduled backup prefix; preserve migration/rollback archives.
find /backups/lms -maxdepth 1 -type f -name 'scheduled-*.dump.gpg' -mtime +7 -delete
echo encryptedBackupVerified=true
