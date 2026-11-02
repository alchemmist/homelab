# Socrat bot

Release contract matches [cluster-deploy.md](cluster-deploy.md): the image lives in Harbor, the version lives in Git, and Argo CD syncs on its own. CI does not call `helm upgrade` and does not write Helm parameters.

## Layers

Three layers. Secrets do not go through Git.

1. **Bot repository** `alchemmist/socrat-bot` builds one image, `harbor.socrat.alchemmist.xyz/homelab/socrat-bot`. Three processes share it: `python -m socrat_bot`, `python -m socrat_bot.updater`, and `python -m socrat_bot.broker`. The Telegram token, Postgres password, and `INTERNAL_TOKEN` live only in the cluster Secret `socrat-bot-env`. The chart does not render that Secret.
2. **Homelab** holds the chart, values, and Application. `deploy-to-socrat` changes only root `image.tag` and `image.digest`. Postgres stays under `postgres.image` (`postgres:17`).
3. **n8n** receives the Alertmanager webhook and calls internal `POST /v1/messages`. The bot token is not stored in Grafana. `X-Internal-Token` is the n8n credential `Socrat bot internal`.

## Addresses

- Public Telegram webhook: `https://bot.socrat.alchemmist.xyz/telegram/webhook`. Ingress exposes only `/telegram`.
- Internal API: `http://socrat-bot.socrat-bot.svc:8080`.
- The bot and sudo-broker use the host network on `socrat-2` (host ports 8082 and 8081) because pod egress from `socrat-3` cannot reach `api.telegram.org`. Services still publish port 8080.
- xui-updater stays on the pod network and probes the 3X-UI Service on port 2053.

## Where it lives

| What | Path |
| --- | --- |
| Chart | `charts/socrat-bot` |
| Release values | `deploy/socrat-bot/values.yaml` |
| Application | `deploy/argocd/apps/socrat-bot.yaml` |
| Alertmanager receiver | `deploy/platform/kube-prometheus-stack/values.yaml` |
| Workflow | `docs/n8n/socrat-bot/workflow.json` |
| Import notes | `docs/n8n/socrat-bot/setup.md` |
| sudo client | `ansible/files/socrat-sudo`, `ansible/files/socrat_sudo`, `ansible/playbooks/socrat-sudo.yml` |

Application: project `default`, namespace `socrat-bot`, `parameters: []`, `prune: false`, `selfHeal: true`. Pull secret `socrat-bot-harbor-pull` is created by the operator.

## sudo-broker

The broker stores a request and does not run the command. `socrat-sudo` posts `user`, `node`, and `argv` with `X-Internal-Token`. After Allow, the client runs `sudo` with that argv once. Deny and timeout do not exec. `/etc/socrat-sudo.env` on `socrat-2` is mode `0640`. The playbook does not write the token and does not change sudoers.

`TELEGRAM_OWNER_ID` has to be set before buttons, broadcasts, and sudo approvals work.
