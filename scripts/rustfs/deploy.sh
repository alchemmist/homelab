#!/usr/bin/env bash
set -euo pipefail
# This explicit operator script is NEVER invoked by source tests/Argo automation.
# An operator must independently review source and record the approved commit.
script_dir=$(dirname -- "${BASH_SOURCE[0]}") || true
repo=$(cd -- "${script_dir}/../.." && pwd)
chart="${repo}/charts/rustfs"
tracked=$(git -C "${repo}" status --porcelain --untracked-files=no) || true
if [[ -n ${tracked} ]]; then
  echo 'Refusing dirty tracked source' >&2; exit 2
fi
untracked=$(git -C "${repo}" ls-files --others --exclude-standard -- charts/rustfs) || true
if [[ -n ${untracked} ]]; then
  echo 'Refusing untracked or ignored chart inputs' >&2; exit 2
fi
ignored=$(git -C "${repo}" ls-files --others --ignored --exclude-standard -- charts/rustfs) || true
if [[ -n ${ignored} ]]; then
  echo 'Refusing untracked or ignored chart inputs' >&2; exit 2
fi
if [[ $# != 3 || $1 != --apply ]]; then
  echo 'Usage: deploy.sh --apply <independently-approved-HEAD> <private-runtime-values.yaml>' >&2; exit 2
fi
approved=$(git -C "${repo}" rev-parse HEAD) || true
if [[ $2 != "${approved}" ]]; then
  echo 'Usage: deploy.sh --apply <independently-approved-HEAD> <private-runtime-values.yaml>' >&2; exit 2
fi
values=$3
[[ -f ${values} && ! -L ${values} ]] || exit 2
# Values contain Secret NAMES only, no credentials.
helm lint "${chart}" -f "${values}"
helm template rustfs "${chart}" -n rustfs -f "${values}" >/dev/null
# Secrets must already be provisioned privately. No broad Secret read/list RBAC.
helm upgrade --install rustfs "${chart}" -n rustfs --create-namespace -f "${values}" --wait --timeout 10m
