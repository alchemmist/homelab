#!/bin/sh
# Narrow, reversible TCP option adjustment; does not ACCEPT traffic or change
# filter/NAT/marks, routes, WireGuard identities/AllowedIPs, interface MTU or DNS.
# Existing node1 OpenVZ WG/flannel advertise ~65KiB MTUs; node5 is native1370.
# Apply only on the original node5 identity, only forwarded VXLAN Pod TCP SYNs.
set -eu
[ "$(hostname -s)" = socrat-5 ] || { echo 'Wrong host; refusing' >&2; exit 1; }
ip -o -4 address show dev wg-socrat | grep -q '10\.250\.0\.41/' || { echo 'Wrong mesh identity; refusing' >&2; exit 1; }
action=${1:-apply}
rule() {
  direction=$1
  case "$direction" in
    incoming) set -- -i flannel.1 -s 10.42.0.0/16 -d 10.42.6.0/24 ;;
    outgoing) set -- -o flannel.1 -s 10.42.6.0/24 -d 10.42.0.0/16 ;;
    *) exit 2 ;;
  esac
  set -- "$@" -p tcp --tcp-flags SYN,RST SYN -m tcpmss --mss 1241:65535 \
    -m comment --comment homelab-vm105-overlay-mss-20261116 \
    -j TCPMSS --set-mss 1240
  case "$action" in
    apply)
      iptables -w 10 -t mangle -C FORWARD "$@" 2>/dev/null || \
        iptables -w 10 -t mangle -I FORWARD 1 "$@"
      ;;
    remove)
      if iptables -w 10 -t mangle -C FORWARD "$@" 2>/dev/null; then
        iptables -w 10 -t mangle -D FORWARD "$@"
      fi
      ;;
    *) echo 'Expected apply or remove' >&2; exit 2 ;;
  esac
}
rule incoming
rule outgoing
