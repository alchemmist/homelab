# NetBird private stage2 recovery — 2026-11-02

## Applied and read back

- Recovered from source `669b572`; no namespace or deployment recreation.
  Namespace UID remains `0933b181-1409-4394-a2c6-87d90cb97949` and server
  deployment UID remains `5acdd79c-9e12-48cd-86cb-9fa924212509`.
- Exact runtime config: `~/.local/state/netbird-internal-stage/config.yaml`
  on the workstation and socrat-0. Auth credential root remains
  `~/.cache/homelab-authentik/credentials.json` on socrat-0.
- Before mutations: fresh Authentik custom-format PostgreSQL dump plus Kubernetes
  recovery inputs, and NetBird quiesced sole-writer PVC tar plus runtime/key
  recovery inputs. AES256 GPG encryption and in-memory decrypt/hash equality
  verification succeeded for each. Recovery keys are private local files, **not
  an off-host disaster-recovery copy**. Archives and evidence live under remote
  `~/.local/state/netbird-internal-stage/journal/`; no backup contents in Git.
- Private loopback pod-forward `/api/instance` initially returned setup required.
  Native `/api/setup` created a technical local bootstrap owner (not a human
  identity/password), with random password and one-day PAT. Credentials were
  captured only in 0600 files under the 0700 journal.
- Temporarily enabled `NB_SETUP_PAT_ENABLED` on the private server deployment;
  restored **false** in a finally block and read back false afterward.
- Native authenticated API confirmed zero peers and setup keys. Verified the
  only policy was native Default, enabled, accept/all, bidirectional, All to All;
  deleted that exact policy ID and read back an empty policy collection.
- Applied/read back schema-exact account settings: JWT groups enabled, `groups`
  claim, allow `netbird-pilot-login`, group propagation enabled, login expiration
  enabled at 28800 seconds, regular-user view blocked. Local auth remains enabled
  **private only**, pending actual owner login and native ownership transfer.
- Final `/api/instance`: setup no longer required. Final counts: peers 0,
  setup keys 0, policies 0, identity providers 0, Services 0, Ingresses 0.

## Exact stop gates / not accepted

The Authentik GET-only plan failed before API inventory or any Authentik write:
`Account mapping does not match the pinned pilot UUID` for the existing remote
`~/.cache/homelab-authentik/account-mappings.json`. Do not rewrite/substitute that
mapping, modify user UUIDs, or blindly retry apply. Review its provenance against
`deploy/identity/account-mappings.json` and obtain the required baseline (exact
providers/outposts/MFA stage configuration) before a separately authorized apply.
No dedicated Authentik provider/groups/memberships and no NetBird connector were
created in this recovery. A copy of the controller script was staged remotely.

Server pod was Running but not Ready before bootstrap, and final server deployment
still reports zero available replicas. Private API succeeds; readiness is an
additional unresolved gate, not claimed healthy or repaired by this task.

There has been **no actual owner OIDC login**, ownership transfer, local-auth
shutdown, public DNS/Ingress, host peer enrollment, setup key, or live traffic
acceptance. Existing WireGuard/SSH, MFA and unrelated applications were not changed.

## Reproducibility / no replay

`scripts/netbird-private-stage2.py` is the focused one-shot owner-host operation.
It checks fresh verified backup evidence, refuses existing bootstrap journals,
never retries a mutation, uses loopback forwarding, and restores PAT issuance off.
The already-completed bootstrap **must not be rerun**. Its separate configure-idp
operation is gated on an already-reconciled dedicated Authentik journal.

Offline checks: `tests/test_netbird_private_stage2.py`,
`tests/test_netbird_control_plane.py` and `tests/test_netbird_oidc.py`:
**29 passed, 4 subtests passed**. Private final readback is stored at
remote `~/.local/state/netbird-internal-stage/journal/stage2-readback.json`.
