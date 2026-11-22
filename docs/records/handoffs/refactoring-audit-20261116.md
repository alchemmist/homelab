# Initial Homelab technical-debt audit — November 16, 2026

Status: research, **not a plan of approved production changes**.
Base: Git `6a94a88d`. Sources, configurations, documentation and CI were
examined. Within this audit the cluster and the published wiki were not
queried and not changed. Information about the accepted migration comes from
its handoff, not a new runtime acceptance. The presence of technical debt
does not prove the presence of an exploitable vulnerability.

## Key findings

### R1. Two Argo CD installation sources — high priority

**Confirmed:** `deploy/argocd/apps/argo-cd.yaml` uses
`deploy/platform/argo-cd/values.yaml`, where application-controller is pinned
to `socrat-5`. But `ansible/playbooks/argocd.yml:12` reads a different file:
`deploy/argocd/values.yaml`, and runs `helm upgrade --install` into the same
release. The old values only have the global selector `socrat-0`, without a
controller override. `docs/platform/delivery/cluster-deploy.md:114` also
points the operator to this old path.

**Risk:** repeating bootstrap could move the controller back to `socrat-0` and
apply a different set of settings. This is a code risk, not a claim about a
run that already happened.

**Direction:** separate install-on-empty from maintenance of the existing
Git-owned release; for the latter remove the competing Helm upgrade. Either
one set of values for bootstrap and Argo, or a verifiable minimal bootstrap
layer. Check: renders must agree on security/config/resources; the existing
release must not be quietly reinstalled by the old playbook. The native
SSO/TLS must be preserved.

### R2. Shared issuer transport duplicated per application — high priority

**Confirmed:** the IP `10.43.218.222` is repeated in active hostAliases:
`charts/open-webui/values.yaml`, `deploy/{lms,wishlist,wiki-runtime,spi-triage}/values.yaml`,
`deploy/platform/{litellm,rancher}/values.yaml`; separately in the Rancher role
defaults. This is the scoped path to Authentik via an existing Service, not a
random IP.

**Risk:** recreating the Service requires updating several files in sync;
some applications may stay Ready while losing native login.

**Direction:** first register the owner, purpose, source of the address and
consumers; add an offline consistency check plus a bounded runtime check that
the address matches the Service. Then choose generation of small values
overlays or another shared configuration. Do not introduce a runtime
generator as a new SPOF. Simply replacing the IP with DNS without examining
the previous network failure does not solve the problem. TLS verification must
not be disabled, issuer/callback changed, or the NetworkPolicy widened.

### R3. Topology duplicated across several layers — medium/high priority

Examples: `ansible/inventory/hosts.yml`,
`ansible/inventory/group_vars/Socrat.yml` (`wg_socrat_nodes`), Helm values,
network policies, operational scripts. `10.250.0.3` appears in 56 files across
ansible/charts/deploy/scripts categories; `10.250.0.1` — in 47. This is a file
count, not a count of independent errors; some are fixtures/historical tools.
Loopbacks, bind-addresses, CIDRs and samples need separate exclusions from
alerts.

The clearest example: `ansible/scripts/wg-peer15-relay.py:12–15` contains
FRONT/CLIENT/BACK/TARGET; `scripts/wg-peer15-endpoint.py:17` stores the
endpoint separately; the playbook repeats the prerequisite addresses. The
association of the working relay with `socrat-0`, `socrat-1` and `socrat-5`
must be verifiable, not guessed from several files.

**Direction:** a small typed registry of nodes/network endpoints with address
roles (mesh/LAN/SSH/egress), then checks for consumers. Do not rewrite
everything with one templating engine and do not change a working network for
code cleanliness. In particular, do not touch the `socrat-2` VPN workloads
and AllowedIPs within ordinary refactoring.

### R4. Current-state and migration journals mixed — high priority

**Confirmed contradictions:**

- `docs/platform/system-overview.md` — 1255 lines; the section on the
  stateless move describes the Monori backend on `socrat-0`, the SPI worker on
  `socrat-1`, although a newer section of the same file records them running on
  `socrat-5`.
- `docs/README.md:42` still calls the SPI runtime migration pending.
- `ansible/inventory/host_vars/socrat-5.yml:3` claims the applications stay on
  `socrat-1`; this is a stale comment, not the setting value.
- `wiki/README.md:15` and `docs/applications/wiki/README.md:15` name
  `wiki-runtime-data` as the active claim, whereas
  `deploy/wiki-runtime/values.yaml` says `wiki-runtime-socrat5`.
- `docs/platform/delivery/cluster-deploy.md:114` does not reflect the split
  Argo CD placement and references the old bootstrap values.

**Direction:** a short current map of components/owners/storage/constraints,
with dated handoffs kept separate. Historical facts must not be rewritten into
the present: add a superseded status and a link instead. Verify file
references, active claims and canonical values automatically. Old incident
receipts should not be required to always match current placement.

### R5. The ordinary wiki source is not identical to the published state

`wiki/README.md` correctly warns: the runtime volume is authoritative, the Git
sync may lag. There is also outdated technical text in
`wiki/content/platform/rustfs.md` next to the newer user-facing
`s3-storage.md`. These are candidates for reconciliation, not grounds to
automatically delete the old page or overwrite the runtime.

**Direction:** separately inventory the pages and the publication queue,
verify the published version by reading it, then update via the supported
editor/import/Git workflow. Do not edit the managed tree of the active
writer, do not publish private operational details; keep URLs/aliases.

### R6. The authoritative data → backup/restore matrix is not yet proven

**Confirmed:** active paths/PVCs changed; e.g., the wiki is now
`wiki-runtime-socrat5` / `/mnt/files/homelab/wiki-runtime/data`, n8n —
`n8n-socrat5` with a bind mount in the `socrat-5` host_vars. The old n8n
recoveryStorage on `socrat-1` was kept explicitly and deliberately — it is not
a defect to be “cleaned up”.

**Not proven by this research:** which active schedules cover all new
authoritative datasets, where the latest independent copy is, whether a
restore was ever performed. The presence of Syncthing or a Retain policy proves
none of this by itself.

**Direction:** a registry of dataset / writer / PVC / path / backup owner /
consistency method / independent destination / retention / last restore. This
is the next read-only runtime check due to the risk of silently losing current
coverage. Old volumes must not be deleted or declared rollback-ready after
new writes.

### R7. Migration utilities and tests are not organized as a lifecycle

`scripts/` still contains `vm105-stateless-handoff.py`,
`vm105-spi-idle-handoff.py` and other narrow-transition tools. The SPI helper
already has a proper refusal for the migrated worker. The SSH→kubectl
transport, timeout/error handling are duplicated. The standard `unittest
discover` cannot be considered safe without first classifying fixtures,
external dependencies and possible side effects.

**Direction:** an active / maintenance / one-shot / retired catalog with
prerequisites, safe defaults and explicit write permission. Only then factor
out the shared transport. Do not break deliberately fail-closed one-shot tools
for the sake of universality.

### R8. New protective tests are not wired into the main Quality Graph

`qg.yaml` currently defines freshness, workflow policy, alert graph delivery
and SPI execution links. There is no node for `test_vm105_management.py` and
`test_socrat5_app_placement.py`. Their local success is not a mandatory CI
check. `pyproject.toml` dev dependencies include the Quality Graph but not
PyYAML; the new tests import yaml and some checks require Helm.

**Direction:** a separate reproducible offline infrastructure-contract suite,
explicit Python/Helm dependencies, schema/render/owner/endpoint/storage
assertions. Do not edit the generated workflow by hand: change qg.yaml and the
generation. Baseline the chosen suite first; do not hide previous errors with
expanded skips/allowlists.

## Proposed order of small changes

1. Fix current state/owners and run a bounded backup coverage audit.
2. Remove the second controlling Argo CD configuration with a
   render-equivalence test.
3. Wire in a small offline CI contract, including a ban on new drift.
4. Introduce a verifiable endpoint catalog, starting with the issuer
   transport; then topology.
5. Reduce docs/context, split out history; reconcile wiki publication
   separately.
6. Sort out the lifecycle of utilities and vendored exceptions; do not mass
   delete recovery data.

A mass IP replacement, PVC renames, a network restart, moving new services,
version upgrades or “fixing” native auth by weakening protections are not
proposed. The research is not a full security audit or proof of DR.
