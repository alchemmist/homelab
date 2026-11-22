# NetBird: login via Authentik on the existing nodes

A narrow controller: `ansible/roles/identity_integrations/files/netbird_oidc.py`.
It prepares the Authentik OIDC provider for the already-running management
`netbird.socrat.alchemmist.xyz`. There are no new VMs, paid services or a separate IdP.
Do not run or import the full `configure.py`: it has someone else's side effects.

The live private stage3 was completed on 2026-11-02: a dedicated Authentik application and
a native NetBird connector were created and read back. See
[the actual report](../../../records/handoffs/netbird-stage3-record.md). This is **not** a personal OIDC login
of the owner, an ownership move or a public enablement; do not repeat the bootstrap.

## What the code pins

Verified against the NetBird **v0.82.0** tree (`idp/dex/connector.go`, SHA256
`3ef9df52d86ea9205055a8f44f7e4fa4cacb0d265c746474c506685a39f7ff34`) and Dex OIDC
(`39b2adbe048fbcbe2d2f531f33e0a2de867cbc0eb960eacc39297e5d64e63747`).

- `GetRedirectURI`: trim one trailing `/`, if there is no `/oauth2` suffix —
  append it, then `/callback`. The controller does not invent another callback.
  There is no `--callback` flag. There is no `server.auth.issuer` — `apply` is blocked.
- The connector types `oidc` and `authentik` request only `openid`, `profile`,
  `email`. The scope `groups` is not requested (`okta`/`pocketid` are different).
  `getUserInfo` and `userIDKey` are not set, `insecureEnableGroups=true`, so
  Dex reads the claim `groups` from the ID token, the default key is `groups`, the subject is `sub`.
- A separate profile-mapping `homelab-netbird-profile` returns `name`,
  `preferred_username`, `nickname` and a group allowlist. The stock profile and
  `homelab-groups` are not attached to the provider. Email only from the managed scope `email`.
  `sub_mode=user_uuid`: `sub` stays the Authentik UUID, not the email.

## Who it admits

Only two already-existing users, the UUIDs do not change:

- `alchemmist` `9e33877a-3eaa-4541-98eb-8cdc10088ef6`, group `homelab-owner`
- `antropophag` `6015c85b-82e9-49ce-a4e3-0270c676e26d`, group `homelab-observer`

Admission into the application `netbird-pilot` — a single binding on `netbird-pilot-login`.
The claim additionally has only `netbird-pilot-grafana` and `netbird-pilot-ssh-socrat-2`.
Both records are added to these three groups. A foreign member, a foreign object without a journal
PK and marker, a superuser group for Tim, inheritance or an RBAC role — a blocker before the write.

The controller does not PATCH `core/users/`. The UUID, email, `is_superuser`, former
groups and Authentik factors are not rewritten. The provider is not added to the
embedded outpost. The existing Grafana provider is not touched.

## Commands

By default `check`: only GET. `plan` is also only GET and prints a digest.
`apply` requires `--approve-sha256` of this digest. The client secret is written only into
`netbird-oidc-runtime.json` (0600). `netbird-oidc-journal.json` stores the PK, UUID,
marker and the SHA256 of the secret, not the secret itself and not the bootstrap token. A symlink is not
followed. A repeat apply with the same secret does not create a second group.

On the owner node, the directory 0700, already contains `credentials.json` with
`AUTHENTIK_BOOTSTRAP_TOKEN` inside. Take the issuer from the real management config
(`server.auth.issuer` as `https://netbird.socrat.alchemmist.xyz`).

```sh
python3 netbird_oidc.py "$ROOT" check --netbird-config "$NETBIRD_CONFIG"
python3 netbird_oidc.py "$ROOT" plan --netbird-config "$NETBIRD_CONFIG"
python3 netbird_oidc.py "$ROOT" apply --approve-sha256 "$DIGEST" --netbird-config "$NETBIRD_CONFIG"
```

`--mappings` defaults to `deploy/identity/account-mappings.json`.
`--public-edge 109.173.40.247|176.98.185.59` only substitutes the DNS of the existing
Authentik for an already-known address. This commit does not call the live API.

## What the parent does after review

1. `check` and `plan` from the live node, reconcile the callback and the operation set.
2. An explicit `apply`, then `check` again.
3. As a separate reviewed step, point the existing NetBird IdP issuer
   `https://auth.socrat.alchemmist.xyz/application/o/netbird-pilot/`, client id
   `socrat-netbird` and the secret from the runtime file. This script does not turn off
   the local NetBird password login: the Authentik requirement on the management
   appears only after this step, not from a single `apply`.
