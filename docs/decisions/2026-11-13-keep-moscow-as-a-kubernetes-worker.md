# Keep Moscow as a Kubernetes worker

Date: 2026-11-13 · Status: Accepted · Scope: `socrat-4` worker membership and VPN relay placement

## Context and decision

The owner rejected removing `socrat-4` from Kubernetes to reduce resource use. Keep its worker membership and run the Kubernetes relay as the normal path. Native systemd forwarding is a local fallback. This superseded the [previous native-primary target](../records/handoffs/moscow-native-primary-20261112.md).

## Rationale and operational consequences

Prefer increasing capacity to retiring the worker. Preserve the existing worker identity and state. A successful native fallback does not make it the new desired architecture or authorize an uninstall and reenrollment.

## Implementation and verification

Commit `30091cb7` restored the relay replica and added the return-worker playbook. The [owner-directed correction and handoff](../records/handoffs/moscow-worker-return-20261113.md) records the bounded operation, rollback and checks. Consult that record for what was actually observed; do not infer continuous relay availability from it.
