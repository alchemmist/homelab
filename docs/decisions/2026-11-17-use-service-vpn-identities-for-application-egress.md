# Give application egress a dedicated service VPN identity

Date: 2026-11-17 · Status: Accepted · Scope: application foreign egress, initially n8n

## Context and decision

The owner rejected using an ad hoc SSH tunnel to NL for n8n. Keep `wg-socrat` for infrastructure transport. An application requiring foreign egress must have a distinct native 3x-ui service client and use its subscription with an official VPN client in the Pod.

## Rationale and operational consequences

Application access has its own identity, quota, expiry and revocation boundary. Do not reuse human VPN accounts, change inter-node routes or copy the old SSH tunnel for a new workload. This requires managing a subscription for each service. Venice's pre-existing SSH egress was recorded as a deviation, not as an approved pattern.

## Implementation and verification

Commit `5b722c5c` replaced n8n's tunnel. The [dated correction and acceptance record](../n8n/service-vpn-20261117.md) documents the owner's instruction, client provisioning, checks and cleanup. It does not establish that every application was migrated. Use the [current service VPN runbook](../network/service-vpn-egress.md) for operational steps.
