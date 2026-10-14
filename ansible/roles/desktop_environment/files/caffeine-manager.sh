#!/usr/bin/env bash
set -euo pipefail

readonly SERVICE="hypridle.service"
readonly LID_SERVICE="caffeine-lid-inhibit.service"
readonly WAYBAR_SIGNAL=7
readonly STATUS_ENABLED='{"text":"Hypridle enabled","class":"enabled","alt":"enabled","tooltip":"Обычный режим: таймеры hypridle и реакция на крышку включены"}'
readonly STATUS_DISABLED='{"text":"Caffeine enabled","class":"disabled","alt":"disabled","tooltip":"Режим молнии: таймеры hypridle отключены, закрытие крышки игнорируется"}'
readonly STATUS_PARTIAL='{"text":"Hypridle disabled","class":"disabled","alt":"disabled","tooltip":"Hypridle остановлен, но блокировка крышки не активна"}'

is_enabled() {
    pgrep -u "$UID" -x hypridle >/dev/null
}

lid_is_inhibited() {
    systemctl --user is-active --quiet "$LID_SERVICE" &&
        systemd-inhibit --list --no-pager --no-legend | grep -q '^waybar-caffeine[[:space:]].*handle-lid-switch'
}

print_status() {
    if is_enabled; then
        printf '%s\n' "$STATUS_ENABLED"
    elif lid_is_inhibited; then
        printf '%s\n' "$STATUS_DISABLED"
    else
        printf '%s\n' "$STATUS_PARTIAL"
    fi
}

notify_waybar() {
    pkill -u "$UID" -SIGRTMIN+"$WAYBAR_SIGNAL" waybar 2>/dev/null || true
}

start_hypridle() {
    systemctl --user start "$SERVICE"
    systemctl --user stop "$LID_SERVICE"
}

stop_hypridle() {
    systemctl --user start "$LID_SERVICE"
    local ready=false i
    for ((i=0; i<30; i++)); do
        if lid_is_inhibited; then
            ready=true
            break
        fi
        sleep 0.1
    done
    if [[ "$ready" != true ]]; then
        systemctl --user stop "$LID_SERVICE"
        printf 'Could not inhibit lid events\n' >&2
        return 1
    fi
    if ! systemctl --user stop "$SERVICE"; then
        systemctl --user stop "$LID_SERVICE"
        return 1
    fi
    pkill -u "$UID" -x hypridle 2>/dev/null || true
}

toggle() {
    if is_enabled; then
        stop_hypridle
    else
        start_hypridle
    fi
    notify_waybar
}

case "${1:-}" in
    --enable) stop_hypridle; notify_waybar ;;
    --disable) start_hypridle; notify_waybar ;;
    -t|--toggle) toggle ;;
    -s|--status|"") print_status ;;
    *) printf 'Usage: %s [--status|--toggle]\n' "$0" >&2; exit 2 ;;
esac
