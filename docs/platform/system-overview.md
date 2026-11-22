# Socrat system overview

[Unexpected loss of `socrat-1`, 21 November 2026](../records/incidents/socrat-1-loss-20261121.md): do not extrapolate the results to the loss of `socrat-0` (NFS) or two nodes. The [second outage that day](../records/incidents/socrat-1-loss-20261121-run2.md) tested a separate Alertmanager on node `0` without changing the PostgreSQL primary.

This guide reflects the migrations accepted on 16 November 2026. Git describes intent; each handoff records when the running system was last verified. This file does not authorize new production operations. Dated results are not continuous monitoring.

## Sources of truth

- Applications: `deploy/argocd/apps/`. Follow each Application to its values file.
- Ansible inventory: `ansible/inventory/hosts.yml`. Mesh registry: `wg_socrat_nodes` in `ansible/inventory/group_vars/Socrat/cluster.yml`.
- Shared issuer transport and its consumers: `deploy/contracts/infrastructure.json`. `ci/check_infrastructure_contracts.py` checks it offline by default; `--write` updates repository files only.
- Argo CD: `deploy/platform/argo-cd/values.yaml` is canonical; `deploy/argocd/values.yaml` is a compatibility symlink. Use `ansible/playbooks/argocd.yml` only for an explicitly authorized installation in an empty environment. The Git Application manages the existing release.
- See the [topic index](../README.md) for runbooks. The [archived chronology](../records/handoffs/cluster-chronology-20261116.md) is not a reference for current placement.

## Choose the next question

- [Placement and data ownership](workload-placement.md): where a workload was verified and where to check now.
- [Safety constraints](operational-boundaries.md): operational boundaries and outstanding risks.
- [Implementation history](../records/handoffs/infrastructure-refactoring-history.md): dated changes and acceptance limits, not current rollout instructions.
