#!/usr/bin/env bash
# arc_metrics.sh — добавленные/удалённые строки рабочей копии vs HEAD (замена git_metrics).
# Источник — сводка `arc diff HEAD --stat`: "N files changed, X insertions(+), Y deletions(-)".
# Формат как в оригинале: "+X " зелёным, "-Y " красным; пусто, если нет изменений.

arc info >/dev/null 2>&1 || exit 0
diff_out=$(arc diff HEAD --stat 2>/dev/null)
line=$(printf '%s\n' "${diff_out}" | grep 'changed')
[[ -z "${line}" ]] && exit 0
insertion=$(printf '%s\n' "${line}" | grep -oE '[0-9]+ insertion')
added=$(printf '%s\n' "${insertion}" | grep -oE '[0-9]+')
added=${added:-0}
deletion=$(printf '%s\n' "${line}" | grep -oE '[0-9]+ deletion')
deleted=$(printf '%s\n' "${deletion}" | grep -oE '[0-9]+')
deleted=${deleted:-0}

G=$'\033[32m'; R=$'\033[31m'; Z=$'\033[0m'
out=""
[[ "${added}" -gt 0 ]] && out+="${G}+${added}${Z} "
[[ "${deleted}" -gt 0 ]] && out+="${R}-${deleted}${Z} "
printf '%s' "${out}"
