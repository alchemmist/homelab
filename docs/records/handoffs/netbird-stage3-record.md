# NetBird private stage3 — 2026-11-02

Historical stage3 snapshot. [Stage4](netbird-stage4-record.md) subsequently
investigated the pinned combined health defect, established actual management
readiness and disabled local auth after connector/PAT proof **before** publishing
the OIDC-only TLS entry. Actual personal owner login/transfer is still separate.

## Actual result

The dedicated Authentik application **and the native NetBird identity-provider
connector now exist**. This is private configuration acceptance only, **not an
actual personal owner OIDC login or ownership transfer**.

- NetBird connector: `authentik-dbkcr0p119kc73917k1g`, type `authentik`.
- Issuer: `https://auth.socrat.alchemmist.xyz/application/o/netbird-pilot/`.
- Strict callback: `https://netbird.socrat.alchemmist.xyz/oauth2/callback`.
- Authentik provider `homelab-netbird`, PK **11**, application `netbird-pilot`.
- Local auth remains enabled **private only**; `NB_SETUP_PAT_ENABLED=false`.
- Peers, setup keys, policies, Services and Ingresses: **all zero**.
- No bootstrap replay, full identity configure, user API writes, factor resets,
  email merging, database editing, owner impersonation, DNS or public exposure.

Sanitized object IDs and comparison results: `deploy/netbird/private-stage3.json`.

## Guarded sequence and exact changes

The previous account-mapping gate was resolved by the parent before this task:
only Tim's missing `idpUserUuid` was appended after matching both live users to
the repository; the previous mapping was saved privately. This task did not
rewrite that mapping or any identity.

Before Authentik writes, GET snapshots captured all existing OAuth2/all-provider
records, applications, outposts, groups, users, scopes, policy bindings/policies,
flows, certificates, all stages, MFA validation stages and every admin factor
collection (duo, email, endpoint, sms, static, totp, webauthn). The only existing
factor was one TOTP device. Dedicated application and operation journal were
absent. Existing encrypted backup evidence was fresh and decrypt/hash verified;
no unnecessary second backup/quiesce or bootstrap was performed.

The dedicated controller's approved digest
`a151d8e3e53b823a592fb2b81ec5d420bb8062e49f2f178d01664667361d4264`
created exactly:

1. Three unprivileged, non-inherited groups: `netbird-pilot-login`,
   `netbird-pilot-grafana`, `netbird-pilot-ssh-socrat-2`.
2. One `homelab-netbird-profile` property mapping scoped to **profile**.
3. One confidential OAuth2 provider, one application, one group-admission binding.
4. Six group membership additions: existing owner and Tim to each new group.

The first apply stopped at its post-write validator, **without write retries**.
Exact mismatch: `mapping.scope_name == profile` true;
`mapping.expression == expected` false; actual length **320**, expected **321**;
`actual.strip() == expected.strip()` true. Authentik strips the final newline
when serializing expressions. Commit `d5d7c10` removes that final newline at its
source and makes the fake API trim expressions to reproduce the real behavior.
Tests passed before deploying the correction: **29 passed, 4 subtests passed**.

A fresh GET-only plan then had **zero operations and zero blockers**. Approved
zero-operation apply (`816f9831ac9fa2092a6ccb47a242f52ca9089772da821a8db9c4bfe5ed3b2b8e`)
performed no Authentik API mutations, completed the private journal as
`reconciled`, and GET-only check returned `reconciled=true`. No provider/mapping
rewrite or secret rotation was needed.

Only then, `netbird-private-stage2.py configure-idp` used native
`POST /api/identity-providers` once. GET readback confirmed the exact connector.
Namespace UID `0933b181-1409-4394-a2c6-87d90cb97949` was guarded before the API
operation; deployment UID `5acdd79c-9e12-48cd-86cb-9fa924212509` stayed unchanged.
All pod-forwards bound only `127.0.0.1`, and were terminated after use.

## Readback and preservation

- The actual Authentik provider secret SHA256 equals both the private runtime
  secret SHA256 and journal fingerprint. No secret/fingerprint value is in Git.
  Native NetBird GET deliberately omits `client_secret`: its successful POST
  used that verified runtime file, but a separate stored-secret GET comparison
  cannot be claimed from that API.
- Provider readback uses only managed `openid`, managed `email`, and the dedicated
  profile mapping; stock profile and separate `groups` scope are not attached.
  The exact allowlisted expression emits the three approved group names,
  `sub_mode=user_uuid`, and claims are included in ID tokens. This is configuration
  validation, **not an observed real-login token**.
- NetBird JWT settings remain `groups`, allow `netbird-pilot-login`, propagation
  enabled. Full account/user API readbacks are canonical byte-equal before/after
  connector creation; only the technical bootstrap user exists in NetBird.
- Existing Authentik provider records (including Grafana), applications,
  scopes, groups, outposts, policies/bindings, flows, certificates, MFA stages and
  factor records are canonical-JSON byte-equal. No old objects were removed.
  Only the two expected user `groups`/`groups_obj` fields changed; old membership
  objects and all nonmembership user fields (including UUID/email/privileges)
  are byte-equal, and exactly the three new group PKs were added to each user.
  Embedded outpost providers remain `[5, 9]`; NetBird is not attached.

Private evidence remains under remote
`~/.local/state/netbird-internal-stage/journal/`: `stage3-authentik-before.json`,
`stage3-authentik-after.json`, `stage3-authentik-comparisons.json`,
`stage3-authentik-plan.json`, `stage3-authentik-zero-plan.json`,
`stage3-netbird-before.json`, `stage3-netbird-after.json`,
`stage3-claims-and-secret-verification.json`, and `identity-provider.json`.
Credentials and dedicated reconciled journal remain in the existing private
Authentik credential root. Evidence files are 0600; no logs were collected.

## Separate readiness and remaining gates

**Connector exists; server Ready is still false.** Loopback `/health` returns
**503**, `status=unhealthy`, `listeners=null`, `certificate_valid=false`.
The configured readiness probe uses this relay `/health` endpoint on port 9000;
zero available replicas is therefore independent of successful management API
and connector creation. This pre-existing relay certificate/listener readiness
condition was not bypassed or repaired. No server log collection was used.

The real owner must personally complete OIDC login before native ownership
transfer to that actual created identity. Do not impersonate the owner or edit
the database. Local-auth disablement requires that subsequent acceptance.
Public routing/DNS/Ingress, host peers, setup keys and traffic tests remain
explicitly unperformed and outside this bounded private stage.
