#!/bin/sh
# Dedicated forced-command SSH key on the independent witness. No shell from client.
set -eu
exec /usr/bin/flock -n /var/lib/homelab-vpn-witness/transition.lock /bin/sh -ec 'printf "LOCKED\n"; cat >/dev/null'
