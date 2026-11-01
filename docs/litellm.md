# LiteLLM gateway

The official `oci://ghcr.io/berriai/litellm-helm` chart is pinned to 1.105.1. A single CPU-only proxy on socrat-0 forwards `qwen3.8-27b` through the internal `llm-switcher` service to one vLLM engine. See [model switching](model-switching.md). Open WebUI connects through a dedicated `open-webui` virtual key restricted to Qwen. The credential is stored in Secret `llm/open-webui-litellm`. A NetworkPolicy permits vLLM ingress only from LiteLLM pods; node traffic remains governed by Kubernetes host networking semantics.

- Admin UI: https://llm.alchemmist.xyz/ui/
- OpenAI API base: https://llm.alchemmist.xyz/v1
- Internal API base: http://litellm.llm.svc.cluster.local:4000/v1
- Models: `qwen3.8-27b`
- Access: public HTTPS; normal human administration uses Authentik MFA + native Generic OIDC/PKCE. Machine API access continues to require a virtual key. Owner-only database password recovery is retained at `/fallback/login`.

The sole regular account is `anton.ingrish@gmail.com`, with role `proxy_admin` (full administrative access). Passwords are stored in the database and can be changed through the UI. `disable_env_credential_login: true` disables the shared environment/master-key UI login; `UI_USERNAME` and `UI_PASSWORD` are absent. The master key remains an administrative API credential. Create client keys in Virtual Keys, choose their allowed models, and set RPM/TPM limits as needed. Do not distribute the master key. Model costs are zero for local inference, so monetary budgets do not limit GPU usage.

PostgreSQL 18.6 uses a retained 10Gi local-path PVC on socrat-0. This is a single-node database, not HA; local-path capacity is nominal. No backup schedule is configured yet. Redis is disabled for this single-replica deployment; revisit coordination before scaling replicas. Database credentials, master key and salt are generated once and retained in Kubernetes Secrets. Preserve the salt with the database when backing up or restoring.

Deploy from `ansible/`:

```sh
ansible-playbook playbooks/litellm.yml
ansible-playbook playbooks/litellm-https.yml --ask-become-pass
```

The second playbook waits for the certificate, updates the existing WireGuard HTTPS gateway while verifying Syncthing identity/pause state, and installs private DNS records on all three resolvers. The WireGuard client role installs the matching macOS split resolver. HTTPS forwarding trusts only loopback and the cluster/WireGuard CIDRs, so redirects retain HTTPS.

Validation on 2026-10-15: migration completed, both pods Ready, unauthenticated models request rejected with 401, temporary restricted virtual key generated, model listing and real completion passed, temporary key revoked, HTTPS redirect and browser admin login passed, public route returned 404. The vLLM pod was not restarted. `scripts/check-litellm.py` repeats the API check from a controller with kubectl access without printing credentials.

Upstream reference: https://docs.litellm.ai/docs/proxy/deploy

The local Qwen deployment uses 7200-second request and streaming timeouts to accommodate long single-GPU requests and queueing. vLLM still has one active sequence; queue saturation can still exceed that deadline.

## Socrat branding

The admin dashboard uses the supplied Socrat portrait with a vector wordmark in light/dark variants and the supplied circular image as the favicon. Assets are versioned under `deploy/litellm/branding/` and served over HTTPS at `/branding/` by a small nginx deployment in the infrastructure chart, backed by a dedicated PVC. No external image host is required. Original raster images remain unchanged.

`ansible/files/configure_litellm_branding.py` verifies public image URLs, enables database-backed management through `/config/update`, and persists the three theme URLs through `/update/ui_theme_settings`, with readback. The LiteLLM playbook uploads assets and applies settings. Theme updates require no restart of LiteLLM or vLLM. Use a new asset filename when replacing an image to avoid stale browser caches.

## Authentik native SSO — 2026-11-01

Normal entry: **https://llm.alchemmist.xyz/sso/key/generate**, also the owner-only **LiteLLM** tile in the Authentik application dashboard. An already valid Authentik MFA session may make this appear as an immediate login; an existing LiteLLM password session is not forcibly revoked.

This is native Generic OIDC with authorization code + PKCE, not an authentication proxy in front of `/v1`. Provider `homelab-litellm` has one exact callback, `https://llm.alchemmist.xyz/sso/callback`, and normal mandatory Authentik MFA. The installed 1.105.1 supports free SSO for up to five billable users; the reconciler conservatively refuses more than five total user rows. No license checks were bypassed. Current baseline has two user rows.

Identity is selected by the reviewed **Authentik user UUID**, persisted in `deploy/identity/account-mappings.json`, and mapped to the existing owner ID **`socrat-admin`**, role `proxy_admin`. The dedicated `litellm_identity` scope supplies the ID, role and existing database email; arbitrary IdP email/name claims cannot select the owner. Other subjects map only to unique UUID-based read-only IDs and synthetic addresses under `sso.socrat.alchemmist.xyz`; production application admission is nevertheless **owner-only**. The read-only branch is exercised by the temporary smoke fixture, not a new grant to Tim/observers.

Secret `llm/socrat-authentik-litellm` holds client credentials and Generic SSO environment settings. Helm values retain optional Secret references, so replay preserves SSO while a fresh deployment without this Secret can still bootstrap local recovery. The explicit integration controller creates the provider/scope/application and starts a normal graceful LiteLLM rolling update only when mounting or changing SSO environment. It does not restart vLLM, change OTel settings, reset a password, rotate master/salt/database keys or put browser redirects on machine APIs.

`litellm.yml` and `llm-vision.yml` import an activation-gated post-Helm reconciliation playbook. It preserves an existing integration but does not activate SSO on a fresh install merely because Helm was run.

Reconcile from `ansible/`:

```sh
ansible-playbook playbooks/identity-integrations.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e '{"identity_oidc_services":["litellm"]}'
```

The foundation catalog does not invent a placeholder LiteLLM SSO app when its reviewed custom scope is missing; run the explicit integration after foundation/DB initialization. Account UUID changes require manual review, not automatic email linking.

### Acceptance and recovery

- Real browser roundtrip: password → temporary TOTP enrollment → native consent → LiteLLM callback `303` → server-verified `internal_user_viewer` identity. No browser JS errors. The temporary UUID-specific admission binding, Authentik identity, LiteLLM user and UI keys were removed; owner privileges were never granted to a fixture.
- Original two user IDs, roles, emails, password hashes and SSO-ID fields compared unchanged. Existing Open WebUI key still lists models; missing key remains `401`. Original master/salt/database Secrets, explicit environment (including OTel) and config bytes compared unchanged against the encrypted pre-change snapshot.
- The real owner's SSO/fallback password acceptance is still an owner action. No owner password or MFA secret was read, reset or fabricated. `/fallback/login` remains HTTP 200; only the existing owner had a stored local password at preflight.
- Encrypted pre-change backup: `~/.config/homelab/litellm-before-oidc-20261101.aesgcm`; authenticated decryption and PostgreSQL archive listing checked, **not a full restore drill**. Private server snapshots are under `~/.cache/homelab-authentik/litellm-*-before-oidc.json` and `litellm-owner-binding.json`.
- To disable SSO, remove only its dedicated Secret reference / Generic environment entries using the protected pre-change deployment snapshot as a reference. Preserve current unrelated deployment edits; do not blindly replace the whole Deployment or force-delete draining pods. Keep the database, passwords, master/salt and existing client keys intact. Remove/disable the LiteLLM portal application only after deciding the desired recovery mode.

Live acceptance (owner Mac with Playwright/Chromium and SSH): `python3 scripts/identity-litellm-smoke.py --run`. It temporarily admits **one random non-admin UUID** to the application for an end-to-end read-only test, then removes that binding in `finally`. No screenshots, credentials, callback query strings or session traces are saved.
