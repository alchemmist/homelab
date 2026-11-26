# n8n native OIDC (Authentik)

Owner-scoped native OIDC login for [n8n](https://n8n.socrat.alchemmist.xyz/).
Identity is owned by `scripts/provision-n8n-oidc.py` — a scoped twin of
`provision-openhands-oidc.py`; the iam rails, plan-hash approval and fresh
encrypted identity backup receipt are shared with `spi-queue-oidc.py`.

## Model

- Provider `homelab-n8n`, confidential client `socrat-n8n`,
  per-provider issuer `https://auth.socrat.alchemmist.xyz/application/o/n8n/`.
- Redirect: `https://n8n.socrat.alchemmist.xyz/rest/sso/oidc/callback`. Strict match.
- Scopes: `openid profile email`. No `groups` scope; n8n has no group roles here.
- Admission: single owner-only binding to `homelab-owner`.
- **No JIT.** n8n accounts must already exist (created by native invitation in
  n8n itself); OIDC only replaces the password form for those accounts. This
  preserves the reviewed decision that the app group does not create accounts.
- n8n is the fully open-source fork image
  (`ghcr.io/alchemmist/n8n@sha256:0ffba3a2…`), so SSO/OIDC is not license-gated.

## Provisioning / drift repair

Read-only plan (prints `plan_hash`):

```sh
python3 scripts/provision-n8n-oidc.py
```

Apply (fresh backup receipt required, see `identity-backup.py`):

```sh
python3 identity-backup.py --output ~/.config/homelab/n8n-oidc/authentik-before-…aesgcm  # → receipt
cp receipt ~/.config/homelab/n8n-oidc/oidc-backup-receipt.json
python3 scripts/provision-n8n-oidc.py --apply --approve-plan-hash <plan_hash>
```

The script writes the private journal to `~/.config/homelab/n8n-oidc/oidc/client.json`
and delivers credentials to Secret `automation/socrat-authentik-n8n`
(`client-id`, `client-secret`). It never prints the secret.
Existing provider/client drift is a STOP; never a reset or adoption.

## Kubernetes wiring

`charts/n8n` renders `N8N_SSO_OIDC_ISSUER_URL` / `_CLIENT_ID` / `_CLIENT_SECRET`
from `sso.oidc.*` values (see `charts/n8n/values.yaml`). Flip `sso.oidc.enabled`
to disable without removing the identity.
