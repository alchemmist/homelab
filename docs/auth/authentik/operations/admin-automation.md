# Authentik: a machine admin API instead of akadmin

Cut: 2 November 2026. This is a separate owner-admin migration, not part of the ordinary reconcile.

## Identities and boundaries

- `alchemmist` — a personal superuser with the existing UUID/password/MFA; `tim` — a personal user with the former limited rights.
- `ak-outpost-…` — the **internal** service-account of the embedded outpost. Do not delete/move its token: it serves the n8n/3x-ui gateways.
- `homelab-identity-automation` — a separate **service_account** for the identity management scripts. Its password is unusable for login (`has_usable_password=False` verified). It is the only member of `homelab-identity-automation-admin`.
- `akadmin` — the former Default Admin/owner of the bootstrap API token. After the verified migration it is removed by a separate guarded action, together with the attached old token.

**The automation administrative rights are broad**, not least-privilege per-resource: the current controllers manage users/groups/flows/policies/providers. This is a move of an existing admin API access onto a machine identity, not a claim of a completed RBAC decomposition. There is no membership in `homelab-owner`, the people's immutable links and the app-role mappings were not changed.

The API token has the former deployment-credential class: a non-expiring admin secret. This is **not** an OIDC access token; the applications' five-minute bearer lifetimes were not increased. The next separate step is a decomposition of rights/consumers and a managed rotation.

## Secrets and compatibility

The private root on socrat-0: `~/.cache/homelab-authentik/`,0700; files0600.

- `automation-api.json`: a journal with the exact user PK/UUID, group PK, nonce, new token, recovery evidence and retirement state. Do not print/publish.
- `credentials.json.AUTHENTIK_BOOTSTRAP_TOKEN` — a **historical compatibility name**, after the migration it contains the new machine token. Therefore existing consumers require no mass code replacement. This is no longer the akadmin token.
- `credentials-before-automation-*.json`, a runtime Secret snapshot — the guarded pre-change state; after retirement the old key is invalid. Do not restore this credential over a working new DB.
- The bootstrap password is removed from the active credentials after retirement. Old encrypted/protected snapshots may contain it; this is not an active login.

The new machine token is **not delivered into the pod runtime**: with an active journal, bootstrap.py excludes both bootstrap variables from the runtime Secret. During the migration only these fields and their last-applied copies are removed, the other Secret fields are kept. Existing processes may keep the old env until the next launch, but the old key becomes invalid when its user is deleted. The IdP was not restarted specifically to clean the env. After a restart the bootstrap env will no longer come from the Secret.

## Managed actions

`ansible/roles/authentik/files/automation.py` is placed by the operator into the private root, not invoked automatically by the routine playbook. Run it on socrat-0 with the existing owner-admin API and kubeconfig; do not pass secrets in argv/extra-vars.

```sh
python3 ~/.cache/homelab-authentik/automation.py ~/.cache/homelab-authentik --action check
# Explicit creation of the service user/group/token and an atomic switch of the credential alias:
python3 ~/.cache/homelab-authentik/automation.py ~/.cache/homelab-authentik --action apply
```

On a collision of others' names/nonce/UUID/groups, a change of the owner UUID or an incomplete journal — stop, no adoption and no bypassing of the checks. The native API forbids creating an `internal_service_account`; for our automation the supported `service_account` is used. The first rejected create left only an empty journal-owned group; the repeat continued under the same nonce without changing the people.

A separate removal of the Default Admin requires: the exact reviewed UUID/PK, an active service token, a personal owner admin, the absence of unexpected token dependencies, a migration-aware bootstrap.py, the absence of bootstrap env in the Secret/explicit pod env, journal evidence of a real recovery drill and the digest of a new off-node encrypted backup.

```sh
python3 ~/.cache/homelab-authentik/automation.py ~/.cache/homelab-authentik \
  --action retire-akadmin --confirm-delete-akadmin
```

This is a **deletion**, not a routine check. Do not copy recovery evidence from the example or someone else's journal to bypass the real test. After the deletion the old token/password do not serve as a rollback. Recovery goes through the existing node-admin channel/official recovery or a reviewed full backup restore.

## Independent recovery

The owner node/kube access is a separate trust boundary from the IdP. The official command inside the Authentik worker:

```sh
# Through a trusted kubeconfig, on the identity worker; the output contains a SECRET link!
ak create_recovery_key 2 <reviewed-username>
```

The resulting link is a bearer credential, do not paste it into chat/Git/log. The relative URL is opened on a verified public Authentik HTTPS hostname, not on an arbitrary domain. Do not run the command for the real owner in an ordinary smoke.

Verified on a disposable admin: a temporary separate group/user, an official two-minute recovery key from the node-admin channel, a fresh Chromium, a native browser session and `/core/users/me/` with the exact fixture PK/username and superuser=true; then an exact cleanup of user/group/tokens. The diagnosis initially expected a UUID in the trimmed `/me/` serializer; it was fixed to PK/username with a separate API UUID guard. One interrupted diagnostic fixture was found and exactly removed; the final drill passed, the leftovers were checked separately.

This is a check of an independent mechanism, **not a personal owner recovery acceptance and not a full DR**. Access to the node/kube API and working Authentik/DB are required. The loss of the cluster/backup key/off-site escrow remains a separate task.

## Acceptance and backup

- 12 unit tests of migration/retirement +14 foundation tests; no-adoption, wrong UUID, Secret guard, idempotence, fail-closed incomplete journal, fresh-install bootstrap and runtime exclusion.
- The new token passed API user/group/provider/app/flow/outpost reads; the existing xui controller `--action check` without changes; a live gateway fixture/native MFA on both edges.
- n8n both edges: root302, health200, keyless API401. This does not close the previously opened owner login/session message.
- Owner/Tim/Outpost immutable IDs/groups, the provider/app/binding configuration are kept; native x-ui/VPN/Traefik are not changed. The IdP pods are not restarted by this procedure.
- An AES-GCM backup before the migration and with the active new machine identity. `backup.py` includes the private automation journal and the pre-migration credentials. A full restore of the new snapshot is not claimed.

After any step, first `--action check`; on a failure, do not delete users/groups by a single name. Keep the private journal to restore the exact state.
