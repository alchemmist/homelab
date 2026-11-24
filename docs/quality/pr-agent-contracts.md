# PR Agent environment contracts

The pr-agent release (`charts/pr-agent`, namespace pr-agent) is a GitHub App and
webhook worker. Its pinned image reads credentials from environment variables;
there is no file-based alternative for these values:
- `pr-agent`: `OPENAI__KEY` (the litellm upstream key), `GITHUB__APP_ID`,
  `GITHUB__PRIVATE_KEY`, `GITHUB__WEBHOOK_SECRET` via `secretKeyRef` from the
  configured application Secret.
- `pr-agent-webhook-redelivery` CronJob: `GITHUB__APP_ID` and
  `GITHUB__PRIVATE_KEY` via the same application Secret, used to authenticate
  GitHub App webhook redelivery.

Secrets are managed out of band (externally-managed runtime secrets, same class
as litellm/harbor/grafana/monori/socrat-bot). NetworkPolicies added in this
pass restrict the deployment to traefik webhook ingress and litellm/GitHub
outbound HTTPS, and the CronJob to GitHub HTTPS + DNS.
