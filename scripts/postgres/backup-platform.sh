#!/usr/bin/env bash
# Run on the trusted administrator host. Only the public recipient cert is needed.
set -euo pipefail
umask 077
export K3S_CONFIG_FILE=/dev/null KUBECONFIG=/etc/rancher/k3s/k3s.yaml
base=$HOME/.config/homelab/pg-platform-dr
cert=$base/recipient.crt
run=$(date -u +%Y%m%dT%H%M%SZ)
tmp=$(mktemp -d); trap 'rm -rf -- "$tmp"' EXIT
exec 9>"$base/backup.lock"; flock -n 9
for tier in pg-critical pg-common; do
  pod=$(kubectl -n postgres get cluster.postgresql.cnpg.io "$tier" -o jsonpath='{.status.currentPrimary}')
  [[ $pod =~ ^$tier-[0-9]+$ ]]
  kubectl -n postgres exec -i "$pod" -c postgres -- bash -se -- "$tier" <<'REMOTE' | openssl cms -encrypt -binary -stream -outform DER -aes256 "$cert" >"$tmp/$tier.cms"
set -euo pipefail
umask 077
d=$(mktemp -d); trap 'rm -rf -- "$d"' EXIT
c=/controller/certificates
export PGSSLMODE=verify-full PGSSLROOTCERT=$c/server-ca.crt PGSSLCERT=$c/streaming_replica.crt PGSSLKEY=$c/streaming_replica.key
pg_basebackup -w -h "$1-rw.postgres.svc.cluster.local" -U streaming_replica -D "$d/base" -X stream --checkpoint=fast --max-rate=32M
pg_verifybackup "$d/base" >&2
tar -C "$d/base" -czf - .
REMOTE
  hash=$(sha256sum "$tmp/$tier.cms"); { printf '%s\n' "${hash%% *}"; cat "$tmp/$tier.cms"; } | ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=8 -i "$base/sender" alchemmist@10.250.0.5 "$tier.$run"
  printf '%s snapshot %s verified and received\n' "$tier" "$run"
done
