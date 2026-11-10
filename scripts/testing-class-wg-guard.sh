#!/bin/sh
# Only this new bootstrap source; do not flush any existing table/chain.
set -eu
IPT=/usr/sbin/iptables
CHAIN=HL_TEST_CLASS_BOOT
if ! "$IPT" -w 10 -t mangle -S "$CHAIN" >/dev/null 2>&1; then
    "$IPT" -w 10 -t mangle -N "$CHAIN"
    "$IPT" -w 10 -t mangle -A "$CHAIN" -d 10.250.0.40/32 -p icmp --icmp-type echo-request -j RETURN
    "$IPT" -w 10 -t mangle -A "$CHAIN" -d 10.250.0.40/32 -p icmp --icmp-type echo-reply -j RETURN
    "$IPT" -w 10 -t mangle -A "$CHAIN" -d 10.250.0.40/32 -p tcp --sport 22 -m conntrack --ctstate ESTABLISHED -j RETURN
    "$IPT" -w 10 -t mangle -A "$CHAIN" -j DROP
fi
# Validate exact owned chain; stop on partial/unknown state, never flush/rebuild.
actual=$("$IPT" -w 10 -t mangle -S "$CHAIN")
expected='-N HL_TEST_CLASS_BOOT
-A HL_TEST_CLASS_BOOT -d 10.250.0.40/32 -p icmp -m icmp --icmp-type 8 -j RETURN
-A HL_TEST_CLASS_BOOT -d 10.250.0.40/32 -p icmp -m icmp --icmp-type 0 -j RETURN
-A HL_TEST_CLASS_BOOT -d 10.250.0.40/32 -p tcp -m tcp --sport 22 -m conntrack --ctstate ESTABLISHED -j RETURN
-A HL_TEST_CLASS_BOOT -j DROP'
[ "$actual" = "$expected" ] || { echo 'STOP: bootstrap guard differs from owned rules' >&2; exit 1; }
if ! "$IPT" -w 10 -t mangle -C PREROUTING -i wg-socrat -s 10.250.0.41/32 -j "$CHAIN" 2>/dev/null; then
    "$IPT" -w 10 -t mangle -I PREROUTING 1 -i wg-socrat -s 10.250.0.41/32 -j "$CHAIN"
fi
