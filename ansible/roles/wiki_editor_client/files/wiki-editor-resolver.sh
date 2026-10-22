#!/bin/sh
set -eu

resolver=/etc/resolver/wiki.socrat.alchemmist.xyz
marker=/var/db/socrat-wiki-resolver-owned
server=''
for candidate in 10.250.0.1 10.250.0.3 10.250.0.2; do
    interface=$(/sbin/route -n get "$candidate" 2>/dev/null | /usr/bin/awk '/interface:/ { print $2 }')
    case "$interface" in
        utun*) ;;
        *) continue ;;
    esac
    answer=$(/usr/bin/dig +time=1 +tries=1 +short "@$candidate" wiki.socrat.alchemmist.xyz A 2>/dev/null || true)
    if printf '%s\n' "$answer" | /usr/bin/grep -Eq '^10\.250\.0\.(1|3)$'; then
        server=$candidate
        break
    fi
done
if [ -e "$resolver" ] && [ ! -e "$marker" ]; then
    exit 1
fi
changed=0
if [ -n "$server" ]; then
    /bin/mkdir -p /etc/resolver
    tmp=$(/usr/bin/mktemp /etc/resolver/.socrat-wiki.XXXXXX)
    trap '/bin/rm -f "$tmp"' EXIT
    printf 'nameserver %s\ntimeout 1\noptions attempts:1\n' "$server" >"$tmp"
    /bin/chmod 644 "$tmp"
    if ! /usr/bin/cmp -s "$tmp" "$resolver"; then
        /usr/bin/touch "$marker"
        /bin/mv "$tmp" "$resolver"
        changed=1
    fi
elif [ -e "$marker" ]; then
    /bin/rm -f "$resolver" "$marker"
    changed=1
fi
if [ "$changed" -eq 1 ]; then
    /usr/bin/dscacheutil -flushcache
    /usr/bin/killall -HUP mDNSResponder || true
fi
