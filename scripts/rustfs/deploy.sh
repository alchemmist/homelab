#!/usr/bin/env bash
set -euo pipefail
# This explicit operator script is NEVER invoked by source tests/Argo automation.
# An operator must independently review source and record the approved commit.
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
chart="$repo/charts/rustfs"
if [[ -n $(git -C "$repo" status --porcelain --untracked-files=no) ]]; then
  echo 'Refusing dirty tracked source' >&2; exit 2
fi
if [[ -n $(git -C "$repo" ls-files --others --exclude-standard -- charts/rustfs) ||
      -n $(git -C "$repo" ls-files --others --ignored --exclude-standard -- charts/rustfs) ]]; then
  echo 'Refusing untracked or ignored chart inputs' >&2; exit 2
fi
if [[ $# != 3 || $1 != --apply || $2 != "$(git -C "$repo" rev-parse HEAD)" ]]; then
  echo 'Usage: deploy.sh --apply <independently-approved-HEAD> <private-runtime-values.yaml>' >&2; exit 2
fi
values=$3
[[ -f $values && ! -L $values ]] || exit 2
# Values contain Secret NAMES only, no credentials.
helm lint "$chart" -f "$values"
helm template rustfs "$chart" -n rustfs -f "$values" >/dev/null
# Secrets must already be provisioned privately. No broad Secret read/list RBAC.
helm upgrade --install rustfs "$chart" -n rustfs --create-namespace -f "$values" --wait --timeout 10m
