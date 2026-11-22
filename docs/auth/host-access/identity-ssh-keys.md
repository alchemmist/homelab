# Authentik → public SSH keys: reviewed Ansible assignments only

## Status and boundaries

**The main chosen scenario is now simpler:**
[manual Ansible: username + public key](ssh-user.md), without Authentik/n8n.
This document describes the retained, disabled optional integration, not a
mandatory step for adding an SSH user.

The integration is **optional and currently off**: `deploy/identity/ssh-bindings.json`
and `ssh-assignments.json` contain empty lists. The existing `users.yml`, the
`users` role, the owner/root/automation accounts and both of Tim's current public
keys in `ansible/inventory/group_vars/Socrat.yml` are unchanged. There is no
live rollout.

Authentik stores **only the source of public keys**, not Linux authorization.
`username`, email, groups, `attributes.hosts`, `attributes.sudo` and similar
fields give no access and do not choose the Linux account. Adding a key in the
IdP by itself changes nothing on hosts: every new exact key set requires
plan → review → export → a separate guarded Ansible apply. This is not SSH SSO
and not an SSH CA. Private keys stay on people's devices; no Linux password is
created. App IAM `configure.py`, VPN/NetBird and topology are not managed by
this integration.

Sources:

- `scripts/identity-ssh-plan.py`: stdlib Python + the system `ssh-keygen`,
  HTTPS GET only; by default it prints a read-only plan without raw public
  keys/attributes.
- `deploy/identity/ssh-bindings.json`: an append-only UUID → Linux username
  ledger.
- `deploy/identity/ssh-assignments.json`: reviewed state, active and revoked
  hosts.
- `ansible/playbooks/authentik-ssh-users.yml`: by default **an intent check
  only**; a real apply uses the existing restricted `users` role and its
  verifier.
- `ansible/files/verify_authentik_ssh_binding.py`: a read-only root preflight
  that forbids automatically adopting an existing local account.

## Immutable identity and explicit scope

The **raw immutable `uuid` from the Authentik User API** is required, not the
integer `pk`, not `uid`, not email and not a custom UUID attribute. An API
without a `uuid` field or without a working UUID filter is rejected on purpose;
do not add a name-based fallback. Verify support in the installed version
before enrollment. The response must contain exactly one exact UUID record
and `pagination.next: null`; an incomplete/ambiguous selection is an error.
The active source must have `is_active: true`, `type: internal` (human user).
Service users are excluded; `root`, `alchemmist`, `ghactions` are forbidden
as managed Linux usernames. Privileged accounts are a separate procedure.

After independently verifying identity, add a **new** binding record rather
than replacing the old one. Example schema (the UUID below is fictional, not
Tim's enrollment):

```json
{
  "version": 1,
  "bindings": [
    {"uuid": "11111111-2222-4333-8444-555555555555", "name": "guest"}
  ]
}
```

Assignments for this binding:

```json
{
  "version": 1,
  "public_key_attribute": "ssh_public_keys",
  "assignments": [
    {
      "uuid": "11111111-2222-4333-8444-555555555555",
      "state": "present",
      "hosts": ["socrat-1"],
      "revoked_hosts": []
    }
  ]
}
```

`hosts` and `revoked_hosts` are mandatory and must not intersect; an active
assignment requires a non-empty `hosts`. There is no “absent hosts → all
machines” semantics. Bindings are not granted automatically: a UUID without an
assignment has no SSH scope. Extra fields like `sudo`, `groups` or shell in a
policy are rejected: this integration grants only bash/no-sudo, without
supplementary groups.

The **entire available Git history HEAD** of both pinned files is checked. A
UUID/name cannot be deleted or reused; old host scopes must remain in
active/revoked tombstones even after a revoke is applied. A shallow checkout
is rejected. Use a full trusted checkout and the usual review; Git history is
not a defense against an administrator rewriting the history/the code itself.
Do not change the ledger when restoring the IdP from a backup: a new UUID
means a different identity, not an automatic merge with the previous one.
Changing the Linux username is a separate migration, not a binding edit. A
freed historical username is not released for another identity.

For `ssh_public_keys` a **JSON list of individual OpenSSH public-key strings**
is supported, not one string with line breaks. A missing/empty/incorrect list
on an active assignment blocks the whole export. Every key is checked with a
real `ssh-keygen -l -E sha256`; a regex is not enough. The same set of types
as the users role is supported: ed25519, RSA, nistp256, OpenSSH security-key
variants. Private material, certificates, authorized_keys options, control
characters, multiline entries and duplicates are forbidden. Comments are
discarded. The plan shows SHA256 fingerprints; the export contains only
canonical public keys and reviewed metadata. There is no shell interpolation
of keys and no remote shell from IdP attributes.

## Plan, export and verification — without live writes

Required: a trusted Authentik HTTPS origin, CA trust, a separate read-only
token with minimal read permission on the needed users/attributes, confirmed
UUIDs, exact inventory aliases and verified fingerprints. No bootstrap/admin
token is needed. Do not obtain the token by printing a Kubernetes Secret and
do not commit it. Example in **bash**; the token is entered without echo and
never appears in process arguments:

```sh
read -r -s -p 'Authentik read-only token: ' AUTHENTIK_SSH_TOKEN; printf '\n'
export AUTHENTIK_SSH_TOKEN
python3 scripts/identity-ssh-plan.py --authentik-url https://sso.example.invalid
# For your own CA additionally: --ca-file /secure/trusted-ca.pem
```

There is no `--insecure`: hostname/chain verification is on; redirects are
forbidden, including redirects to another HTTPS host. The script does not
write to Authentik, run Ansible/SSH or save the raw API responses. On error it
does not print the server response, the token, raw attributes or the invalid
input. Do not enable shell tracing, HTTP debug logging or writing the
environment to a third-party CI artifact.

Review every person, all active/revoked hosts, the fingerprints and
`review_sha256`. Then a fresh GET and an **explicitly approved export** to a
new file outside the repository:

```sh
python3 scripts/identity-ssh-plan.py --authentik-url https://sso.example.invalid \
  --export /tmp/reviewed-ssh-users.json --approve-plan REVIEWED_SHA256
unset AUTHENTIK_SSH_TOKEN
```

If a key/policy/binding changed, the digest differs and the export refuses.
The file is created with `O_EXCL`, mode 0600, without overwrite. An empty
integration is not exported. The public export does not need to be stored in
Git. For fully offline tests a `--snapshot /secure/public-users.json` (a list
of API user records) is allowed, but **plan only**, never export. Do not store
passwords/tokens/other IdP attributes in a snapshot.

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml \
  playbooks/authentik-ssh-users.yml -e @/tmp/reviewed-ssh-users.json --check
# Without --check the behavior is also read-only until explicit apply flags.
```

This is a **local check of intent, digest, aliases, full scope and conflicts
with the manual inventory**, not a simulation of user creation and not a check
of the current host state. It opens no remote connections. Do not replace it
with a claim that remote SSH login already works. A `--limit` excluding at
least one required active/revoked host is forbidden. An unknown inventory
host also blocks the play. The export must not be edited after review: Ansible
recomputes the digest payload.

## A separate, explicitly authorized apply

Only after review and a fresh export (below is an instruction for a future
deployment, not a performed action):

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml \
  playbooks/authentik-ssh-users.yml -e @/tmp/reviewed-ssh-users.json \
  -e homelab_authentik_ssh_apply=true \
  -e homelab_authentik_ssh_approval=REVIEWED_SHA256 --ask-become-pass
```

**Both** apply/approval flags are required; `--check` still stays read-only.
Before any account/key change, the root preflight on all target hosts checks
the binding:

- an existing Linux account without the root enrollment marker → stop, no
  auto merge;
- a marker with a different UUID/name, a symlink or unsafe permissions → stop;
- for a new account, `/var/lib/homelab-authentik-ssh-bindings/<name>.json`
  (`root:root`, directory 0700/file 0600) is reserved first, then the users
  role is invoked;
- the marker is not overwritten and remains after disable; a partial apply can
  be repeated with the same binding. Delete nothing to bypass a mismatch;
- even with a correct marker the passwd home must be `/home/<name>`. Symlinks
  in `/home`, home, `.ssh` or `authorized_keys` are forbidden. A non-standard
  home is not migrated and old effective keys are not left outside the managed
  path;
- a real `sshd -T` is checked: the **single** AuthorizedKeysFile must be
  `.ssh/authorized_keys`, `%h/.ssh/authorized_keys` or exactly
  `/home/<name>/.ssh/authorized_keys`; a second file (including the default
  `authorized_keys2`), AuthorizedKeysCommand and TrustedUserCAKeys are
  forbidden. pubkey=yes, password/kbd-interactive/hostbased/GSSAPI/Kerberos=no
  is required. Missing required effective fields means refusal;
- all `Match` directives, including via recursive `Include`, are currently
  **unsupported**: a single `sshd -T -C` does not prove the absence of an
  alternate key source for other clients. The preflight rewrites nothing in
  sshd and does not change the auth policy of owner/Tim. If the live sshd runs
  with a different `-f`/CLI overrides, STOP: this mode is not supported;
  before the pilot confirm the standard `/etc/ssh/sshd_config` and the absence
  of overrides.

The whole host apply (preflight → marker reservation → users role → exact-key
postflight) is serialized by an exclusive `mkdir /run/homelab-authentik-ssh-apply.lock`
as root. A second writer **fails**, does not wait and does not reuse someone
else's lock; the marker/name/UUID are checked already under the lock. `always`
removes the lock only of a successfully started apply. A crash/unreachable host
or another host's error can leave a stale lock: first verify no apply is
running, the marker/account/effective keys, and only then separately agree on
removing the lock. Do not automate lock stealing/TTL. Manual user-management/
adoption outside this playbook also requires operational serialization; the
lock does not protect against an arbitrary other root writer.

`any_errors_fatal` stops the remaining hosts on a preflight error; Ansible is
not transactional: a late error can leave a partial result. Fix the cause,
repeat a fresh plan/apply and check **every** host. Do not claim a successful
revoke from one successfully processed node.

Automatic migration of existing accounts is **not implemented**. It needs
separately agreed proof of ownership, exact keys and local account review;
only then can an administrator separately reserve a verified root marker and
move the account out of the manual inventory. Do not create a marker from a
matching email/username. While Tim remains in the manual `homelab_users`,
importing the same Linux name is forbidden. Do not delete his manual record
and do not change both keys for the sake of testing the integration.

The apply manages **only the imported accounts**; it does not rebuild manual
users. The existing `users` role is used: exact authorized_keys replacement,
password_lock, no sudo/root-equivalent groups, private `.ssh` permissions,
removal of the legacy direct sudoers grant and the effective SSH/PAM/sudo/
kubeconfig verifier. The only scoped role extension is an explicit
`/home/<name>` when creating an imported account; default/manual users keep
their previous OS home behavior. After the role, a separate scoped verifier
repeats the binding/home/sshd checks, parses **every** effective key line with
a real `ssh-keygen`, and requires the exact fingerprints from the reviewed
export (no extra/duplicate/invalid keys). For a disabled state, **zero
effective keys** and nologin are required; nologin alone is not enough to
revoke forwarding. These checks were not added to the manual Tim/owner path.
Separately verify permissions, the effective forwarding policy, and log in
from your own device. The verifier does not prove that a person possesses the
private key. Do not promise this without a real apply/login acceptance.

## Revocation and the removed-host workflow

1. To remove a key, delete **only that public key** from the IdP attribute,
   get a new plan, independently verify the remaining fingerprints, export
   and apply the exact set. Deleting the attribute/the last key **does not
   mean a successful revoke**: the active plan will refuse. A full revocation
   requires an explicit `state: disabled`.
2. To revoke **one host**, move the alias from `hosts` to `revoked_hosts`.
   Keep `state: present` on the other hosts. The removed host gets an explicit
   disabled record; it does not disappear from scope. If the last active host
   is removed, set `state: disabled`; you may keep `hosts: []` and all aliases
   in revoked.
3. For a full revocation, keep the previous hosts/tombstones and set
   `state: disabled`. Disabled records do not require an available IdP or
   keys: access can be revoked even after the IdP user is deleted/when the
   IdP is down. The UUID binding is still mandatory.
4. Apply to **all** required hosts. Disabled means a preserved account/home,
   nologin shell, empty authorized_keys and no managed privileges. Check each
   host/effective verifier. Keep the ledger and host tombstones in Git and
   the host markers in place. Simply deleting an assignment/host is blocked
   by the history check and is not a revoke.
5. With a machine unreachable/decommissioned, access cannot be declared
   revoked. A separate verifiable decommission/isolation procedure is needed;
   do not delete a tombstone just to get a green result.

**Already established SSH sessions, port forwards and processes are not
guaranteed to terminate by this.** Separately arrange inspection/termination
of active sessions/jobs, check other SSH key providers/sshd overrides and the
user's available credentials. Do not delete the home or run a global
destructive account cleanup. Restoring access is a new reviewed decision, not
a rollback of an old export with revoked keys. Changing IdP groups or
disabling an IdP account by itself changes nothing on hosts; an inactive
active-assignment blocks the plan with a demand for an explicit disable.

## Offline acceptance

```sh
/tmp/homelab-iam-tests/bin/python -m unittest discover -s tests -p 'test_identity_ssh.py' -v
/tmp/homelab-iam-tests/bin/python -m unittest discover -s tests -p 'test_identity.py' -v
cd ansible
ansible-playbook -i inventory/hosts.yml \
  playbooks/authentik-ssh-users.yml --syntax-check
```

The tests use fake HTTPS, a real public-key parser, a temporary local inventory
and **only default/--check Ansible**, without remote writes, real tokens or
private key fixtures. An SSH CA is not implemented.

**Before production, disposable-Linux real-apply acceptance is still needed**,
not on Tim/owner: creation → login; rotation (old key denied/new key allowed);
disabled and removed-host (old keys denied, including `ssh -N`/new forwards);
a correct marker and refusal on a different UUID/unbound account; nonstandard
home/alternate key file/Match refusal **before** account/key writes; competing
writers and crash/stale-lock recovery. Also check the actually running sshd
command line, fresh logins from different client addresses, already
established sessions/forwards, an unreachable host and a repeated partial
apply. None of these actions were performed here. Without them revocation
cannot be declared working.

### The limited OpenSSH Include syntax

The importer deliberately accepts only simple `Include` paths/globs of letters,
digits, `_ . / - * ? [ ]`, without quotes, escape sequences, `#`, `~` and `%`.
Comments are supported as separate lines. Other forms may be valid for
OpenSSH, but the importer stops before changing accounts/keys: it must not
interpret the configuration differently from sshd. Any `Match` in the main or
an included file remains a blocking condition. Do not simplify the working SSH
policy to satisfy the importer; use the existing reviewed manual Ansible path
or separately extend the verifier with real OpenSSH regression tests.

The regression tests use a real `sshd -T` and `-T -C` with a temporary host
key: an Include filename with a literal `#` can hide a `Match` from the shell
parser, but is now rejected by the preflight. This is an offline test, not
SSH acceptance on the nodes.
