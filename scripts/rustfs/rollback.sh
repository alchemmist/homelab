#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 && $1 == --apply ]] || { echo 'Usage: rollback.sh --apply' >&2; exit 2; }
# Remove browser admission first; retain private data and machine-key recovery.
kubectl -n identity delete ingress rustfs-authentik-browser --ignore-not-found
kubectl -n rustfs delete ingress rustfs-evidence-browser --ignore-not-found
# List Deployments only, never Secrets; absent disabled components are harmless.
deployments=$(kubectl -n rustfs get deployments -o name)
for deployment in $deployments; do
  case "$deployment" in
    deployment.apps/rustfs|deployment.apps/rustfs-gateway)
      kubectl -n rustfs scale "$deployment" --replicas=0 ;;
  esac
done
# Deliberately NEVER delete PVC/PV/StorageClass, revoke existing identities or edit SPI state.
