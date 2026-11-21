#!/usr/bin/env bash
# OpenSSH forced command, dedicated append-only sender. Never interpret remote shell input.
set -euo pipefail
umask 077
[[ ${SSH_ORIGINAL_COMMAND:-} =~ ^(pg-common|pg-critical)\.([0-9]{8}T[0-9]{6}Z)$ ]] || exit 64
tier=${BASH_REMATCH[1]}; run=${BASH_REMATCH[2]}; dir=$HOME/backups/pg-platform/$run
mkdir -p "$dir"; cd "$dir"
exec 9>"$tier.lock"; flock -n 9; test ! -e "$tier.cms"; test "$(df -Pk . | awk 'END{print $4}')" -gt 20971520
tmp=$(mktemp "./.$tier.XXXXXX"); trap 'rm -f "$tmp"' EXIT
# Size per archive capped at 8 GiB. Sender frames with digest so an interrupted
# upload can never be published merely because ssh closed its stdin.
IFS= read -r digest; [[ $digest =~ ^[0-9a-f]{64}$ ]]; ulimit -f 8388608; cat >"$tmp"
printf '%s  %s\n' "$digest" "$tmp" | sha256sum -c - >&2
ln "$tmp" "$tier.cms"; printf '%s  %s.cms\n' "$digest" "$tier" >"$tier.cms.sha256"
