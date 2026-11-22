# n8n manifest findings from PR #494

This is a residual-decision record, not a waiver or an assertion that the n8n
findings are fixed. PR #494 reports 13 n8n findings: `env-value-from` (4),
`read-secret-from-env-var` (3), `no-liveness-probe` (2), `no-readiness-probe`
(1), `no-read-only-root-fs` (1), and `non-isolated-pod` (2). The chart already
renders the release namespace explicitly for its Deployment, backup CronJob,
Ingress, and Service; those namespace declarations do not resolve the remaining
findings.

## Decisions needed before changing runtime contracts

- **Credential delivery and rotation:** establish, separately for n8n's
  PostgreSQL username/password, encryption key, service-VPN subscription
  identity, and backup SSH identity, whether each consuming program supports a
  mounted file and reload/rotation without losing workflow decryption, database
  access, VPN egress, or backup access. Until that is established, retain the
  current Secret keys and delivery contracts; do not rename keys, replace them
  with guessed file paths, or remove backup credentials. Tests need to exercise
  successful rotation and rejection/failure behavior in an isolated fixture.
- **Service-VPN health:** the VPN sidecar's readiness test currently verifies
  both expected loopback listeners. Decide whether a supported local liveness
  signal exists that distinguishes a dead/stuck process from temporary remote
  subscription/transport failure. Do not add a dummy HTTP endpoint or make
  remote Google availability a liveness condition; restart loops could interrupt
  active workflows. Preserve the existing readiness gate and the VPN-only
  Google path.
- **Filesystem:** identify the exact writable paths required by the pinned n8n
  image and its extensions, and test startup, workflow execution, and recovery
  with those paths writable while the image root remains read-only. No
  read-only-root setting is safe until that contract is verified; the existing
  persistent workflow data and backup/recovery behavior must remain intact.
- **Network isolation:** provide the actual permitted ingress and egress peers
  for the n8n application, service-VPN sidecar, and backup job, including DNS,
  PostgreSQL/TLS, webhook ingress, subscription retrieval, and backup destination
  paths. Validate both allowed and denied connections against a composed offline
  workload inventory before creating policies. Do not guess selectors or disrupt
  the established backup route or the VPN-only external connectivity.

No production workflow replay, secret mutation, deployment, network change, or
backup operation is authorized by this record. These decisions remain open; the
PR's aggregate count is preserved as-is until actual behavior and both positive
and negative tests support a fix.
