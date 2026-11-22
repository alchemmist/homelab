# NetBird Users page: authenticated invite-list read blocked at the edge

2026-11-03. Dashboard 2.96.0 / combined management 0.82.0.

## Root cause

`src/modules/users/UsersTable.tsx` fetches `/users/invites` when the account has
`embedded_idp_enabled`. This is true for the combined embedded OIDC bridge used
with the external Authentik connector; it does not mean local password signup is
allowed. The dashboard needs the native list to calculate its invite badge/table.
Its `useFetchApi` uses SWR retries and revalidation on focus/reconnect, and displays
request errors, so the blocked read produced recurring 403 notification toasts.

The dedicated edge forwarder denied `PathPrefix(/api/users/invites)` wholesale.
That correctly protected local invite creation/acceptance but also rejected the
admin-only read. Before correction, an existing administrative credential received
200 for users/groups, 403 for the public invite list, and 200 with native empty
list when using a bounded loopback Kubernetes port-forward. Direct unauthenticated
list access returned 401. No invite contents or tokens were logged.

## Narrow correction

The deny condition for this prefix is now:

```text
PathPrefix(`/api/users/invites`)
  && !(Path(`/api/users/invites`) && Method(`GET`))
```

Only exact GET list requests fall through to the existing management API router.
The native identity/role checks remain; there is no public synthetic empty list,
new auth bypass, fake JWT, permission promotion, disabled toast or dashboard fork.
All other methods and child/token paths remain blocked. `/api/setup`, local login,
registration and signup protections are unchanged. `/api/setup-keys` remains a
separate authenticated machine API, not affected by the setup deny rule.

The live ConfigMap change preserved resourceVersion/UID and altered only that
router condition. Before-state was saved privately; no workload restart,
control-plane change, identity mutation or networking migration was needed.
Traefik file-provider hot reload was confirmed by actual endpoint responses.

## Live verification

Both public IPv4 entrances, trusted TLS and correct SNI:

| Probe | Expected and observed |
| --- | --- |
| Admin users GET | 200 |
| Admin exact invite-list GET | 200, native `[]` |
| Anonymous exact invite-list GET | 401 |
| Anonymous invite creation POST | 403 |
| Public invite token/details GET | 403 |
| Public invite acceptance POST | 403 |
| Setup GET | 403 |
| Local login and signup GET | 403 |

Mutating boundary probes were deliberately anonymous with invalid/empty input;
no real invitations, acceptance tokens, users or access grants were created.
Regression tests pin the exact method/path exception and the unchanged native
API route. Existing Signal streams are checked separately after the change.
The personal authenticated browser session was not copied or impersonated;
refreshing that session is separate user acceptance.

Durable source: `scripts/netbird-pilot.py`, used by
`scripts/netbird-public-entry.py`. Private before/readback records:
`users-invites-edge-before.json` and `users-invites-edge-verified.json` under the
existing controller journal, never public credential-bearing snapshots.
