#!/usr/bin/env bash
# Idempotent service deployment on the trusted node from reviewed, tracked source.
# No SSH session/tmux is needed for dispatch, retries, updates or subsequent issues.
set -euo pipefail
umask 077
src=$(cd "$(dirname "$0")" && pwd); dest=${HOME}/pi-monori-509-v1
for f in base.git catalog-full.json.gz backlog.json catalog.json deps.tar.gz;do test -e "${dest}/${f}" || { echo "Missing enrolled adapter asset ${f}" >&2;exit 1; };done
for f in lifecycle_worker.py artifact.py dispatcher.py campaign.py restore_worker.py index_catalog.py worker_adapter.json report_dispatch.py;do install -m600 "${src}/${f}" "${dest}/${f}.install";mv "${dest}/${f}.install" "${dest}/${f}";done
mkdir -p "${HOME}/.config/systemd/user";install -m644 "${src}/mutation-report-consumer.service" "${HOME}/.config/systemd/user/"
install -m644 "${src}/mutation-pr-lifecycle.service" "${HOME}/.config/systemd/user/"
systemctl --user daemon-reload;systemctl --user enable --now mutation-pr-lifecycle.service;systemctl --user enable --now mutation-report-consumer.service
