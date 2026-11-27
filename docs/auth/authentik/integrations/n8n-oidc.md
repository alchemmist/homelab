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

## Activation (n8n side)

n8n 1.x does **not** read `N8N_SSO_OIDC_*` environment variables: the OIDC
client config lives in the n8n database (settings key `features.oidc`) and is
owned by the instance owner. Normal path is the owner UI
(Settings -> SSO -> OpenID Connect with the discovery endpoint
`.well-known/openid-configuration`, client ID `socrat-n8n`, client secret from
`kubectl -n automation get secret socrat-authentik-n8n`).

The operator equivalent is scripted:

```sh
python3 scripts/provision-n8n-oidc.py                    # plan
python3 scripts/activate-n8n-oidc.py                     # plan (rows both empty/dirift)
python3 scripts/activate-n8n-oidc.py --apply            # single transaction + private snapshot
kubectl -n automation rollout restart deployment/n8n   # pick up loadOnStartup settings
```

`activate-n8n-oidc.py` refuses a second apply once `features.oidc` exists — the
owner UI owns changes from there. It never prints secrets, snaps both touched
rows to `~/.config/homelab/n8n-oidc/activate/` and encrypts the client secret
with `N8N_ENCRYPTION_KEY` (n8n Cipher/CryptoJS format). It also requires the
chart's `authentikPublicAlias` hostAlias (node socrat-5 cannot reach the
split-horizon LAN VIP 192.168.0.250 for `auth.socrat.alchemmist.xyz`).

The stored secret is encrypted with `N8N_ENCRYPTION_KEY`. The password form
stays available to the instance owner; non-owner users need SSO or the
per-user allow-SSO-manual-login flag. Equivalently, an owner session can
`POST /rest/sso/oidc/config` with `{discoveryEndpoint, clientId, clientSecret, loginEnabled: true}`.

## Kubernetes wiring

No chart env is needed for OIDC; the values file only documents the recipe and
the credential Secret. `socrat-authentik-n8n` is the operator-visible copy of
provisioner credentials (chart mounts nothing).
