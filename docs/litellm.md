# LiteLLM gateway

The official `oci://ghcr.io/berriai/litellm-helm` chart is pinned to 1.105.1. A single CPU-only proxy on socrat-0 forwards `qwen3.8-27b` to the existing vLLM service. Open WebUI connects through a dedicated `open-webui` virtual key restricted to `qwen3.8-27b`. The credential is stored in Secret `llm/open-webui-litellm`. A NetworkPolicy permits vLLM ingress only from LiteLLM pods; node traffic remains governed by Kubernetes host networking semantics.

- Admin UI: https://llm.alchemmist.xyz/ui/
- OpenAI API base: https://llm.alchemmist.xyz/v1
- Internal API base: http://litellm.llm.svc.cluster.local:4000/v1
- Model: `qwen3.8-27b`
- Access: public HTTPS; UI requires a database account, API requires a key. Public DNS and trusted TLS were verified on 2026-10-15.

The sole regular account is `anton.ingrish@gmail.com`, with role `proxy_admin` (full administrative access). Passwords are stored in the database and can be changed through the UI. `disable_env_credential_login: true` disables the shared environment/master-key UI login; `UI_USERNAME` and `UI_PASSWORD` are absent. The master key remains an administrative API credential. Create client keys in Virtual Keys, restrict them to `qwen3.8-27b`, and set RPM/TPM limits as needed. Do not distribute the master key. Model costs are zero for local inference, so monetary budgets do not limit GPU usage.

PostgreSQL 18.6 uses a retained 10Gi local-path PVC on socrat-0. This is a single-node database, not HA; local-path capacity is nominal. No backup schedule is configured yet. Redis is disabled for this single-replica deployment; revisit coordination before scaling replicas. Database credentials, master key and salt are generated once and retained in Kubernetes Secrets. Preserve the salt with the database when backing up or restoring.

Deploy from `ansible/`:

```sh
ansible-playbook playbooks/litellm.yml
ansible-playbook playbooks/litellm-https.yml --ask-become-pass
```

The second playbook waits for the certificate, updates the existing WireGuard HTTPS gateway while verifying Syncthing identity/pause state, and installs private DNS records on all three resolvers. The WireGuard client role installs the matching macOS split resolver. HTTPS forwarding trusts only loopback and the cluster/WireGuard CIDRs, so redirects retain HTTPS.

Validation on 2026-10-15: migration completed, both pods Ready, unauthenticated models request rejected with 401, temporary restricted virtual key generated, model listing and real completion passed, temporary key revoked, HTTPS redirect and browser admin login passed, public route returned 404. The vLLM pod was not restarted. `scripts/check-litellm.py` repeats the API check from a controller with kubectl access without printing credentials.

Upstream reference: https://docs.litellm.ai/docs/proxy/deploy
