# OpenHands runtime contracts

## Runtime pod selectors behind policies

- `automation-postgres-egress` and `monori-publisher-canvas-out` select the
  OpenHands runtime pod by `statefulset.kubernetes.io/pod-name: openhands-0`.
  That label is attached by the StatefulSet controller at runtime and is not a
  label on the chart's pod template, so it cannot resolve in the offline
  renderer. `monori-publisher-canvas-in` references the same runtime pod as its
  ingress peer. These policies intentionally guard exactly the OpenHands pod.
- `openhands-backup-pre142` covers the same-named PreSync backup Job's runtime
  pod. It is a one-shot backup, not a steady-state workload, so the offline
  policy validator cannot show a running pod for the selector.

## Environment-only credentials

- `openhands-oidc`: `client-id` from Secret openhands-oidc and `password` from
  Secret openhands-oidc-sessions are consumed by the OAuth2 Proxy environment
  interface. There is no file-based configuration channel for those values.
- `openhands` (agent-canvas StatefulSet): `AUTOMATION_DB_URL` from Secret
  automations-postgres, `OH_SECRET_KEY` and `OH_SESSION_API_KEYS_0` from the
  configured existing Secrets are supplied through environment variables by the
  upstream application. Secrets are managed out of band.

## Hardening evidence

The pinned `ghcr.io/openhands/agent-canvas:1.43.0` image defaults to the
`openhands` user. A Docker run with uid 10001, read-only root filesystem,
writable `/tmp` and the existing persistent OpenHands directories successfully
generated/persisted its secret keys and started the agent and automation
services. `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` and `XDG_DATA_HOME` are directed
into the existing PVC to avoid writes to the image home directory. The chart
now sets `readOnlyRootFilesystem: true` and the /tmp emptyDir.
The monori-publisher liveness probe now matches its existing :8081 readiness
check.
