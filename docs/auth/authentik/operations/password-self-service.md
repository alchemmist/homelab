# External: self-service password change

Address: **https://auth.socrat.alchemmist.xyz/change-password**.
The user remains External; no admin/staff groups are needed. `/if/user/` for
External users is closed by Authentik itself; the earlier promise to open
settings there is incorrect.

The `password-self-service` mini-service is deployed via a separate Argo CD
Application, source `charts/password-self-service`, namespace identity. nginx
validates the active cookie session via Authentik `/api/v3/core/users/me/`
without an admin token; an anonymous visitor is redirected to the standard
authentication flow with a return to `/change-password`. Validation errors do
not grant access. After session validation the mini-service redirects in the
same window to `/if/flow/socrat-change-password/`. The native flow uses the
existing domain Brand/CSS/random background and password/repeat prompts.
There is no iframe anymore; the `/change-password` address serves as the
permanent entry link. The native button is currently labeled Continue, the
heading is Update password. After the update a confirmation appears; Continue
ends the session via the standard logout flow and returns to the page (logging
in with the new password will be required).

New flow: authenticated-only → existing password/repeat prompt with the previous
password policy → existing never-create UserWrite → success message.
The password handler stays in Authentik; the mini-service does not accept
passwords and has no API token, ServiceAccount token, PVC or database.
Cache-Control no-store, CSP, read-only/nonroot container, pinned image.
Local external passwords are supported; this scenario does not change the
password of the external upstream IdP. App groups/type/UUID are unchanged.

Flow creation: `ansible/roles/authentik/files/password_self_service.py`
(GET-only by default; an explicit `--apply` creates missing own resources and
stops on drift). The initial exact-path redirect route keeps priority 150;
the Argo mini-service has 160 and serves the page. Do not remove the shared
login flow, Brand, password policy, or shared write/prompt stages on rollback.
To roll back the route, first remove only the new ingress, not the shared
authorization.

Live acceptance: Argo Synced/Healthy, Deployment ready; a public anonymous GET
returns 302 to the normal Authentik login with next=/change-password. Native
integration on a temporary zero-group External fixture: anonymous denied,
password/repeat fields, missing CSRF denied, mismatch rejected, the new
password written by the native flow, success prompt reached, External/zero
groups preserved. The fixture was removed. The authenticated fixture session
was created by a native test helper — this is **not a browser login/MFA E2E**.
The first harness runs were fixed for signed Authentik cookies, a custom CSRF
header and the redirect chain; production permissions/protections were not
weakened. The browser tool did not start: the profile was occupied by another
session, which was not closed. After two fixes the owner reported: “yeah, seems
to work now”. This is the owner's confirmation that the page works, not proof
of the full password-change/logout/re-login/MFA cycle for every External user.
Do not claim a successful change of a real password without separate
confirmation. Vladislav's or other real people's passwords were not changed;
MFA was not reset.

Private preimages: socrat-0
`~/.cache/homelab-authentik/password-self-service-*`; initial apply
`password-self-service-6nds08hm`. There was no full Authentik restart, SQL
workaround, cluster-wide sync/prune, or app admission change.

## Fixes that must not be rolled back

1. `6a2c14b5`: the initial iframe was blocked by the native
   `X-Frame-Options: DENY`. Now there is only a top-level redirect; do not
   disable Authentik's framing protection and do not remove the header.
2. `4216e51c`: a relative nginx redirect after successful session validation
   expanded to the internal `http://auth…:8080`. Both redirects now use a
   constant public HTTPS origin; the visitor's Host/next do not choose the
   destination address. A repeated HTTP probe with a temporary External
   session confirmed the correct `Location`; Argo Synced/Healthy specifically
   on `4216e51c`.

Mini-service/flow sources: `d21935e8`; first-stage documentation `9407b4c4`.
All these changes are published in origin/main. The current closeout only
changes documentation; it does not start a new password change, rollout, or
login on behalf of a person.

## Authentik Application Dashboard

Registered providerless application **Change password**, category **Account**,
launch URL `https://auth.socrat.alchemmist.xyz/change-password`. All card metadata
is English. No new OAuth provider, credentials, user memberships, admin rights or
admission bindings: this is a self-service link, not an app-role grant. The route
and native flow still require authentication. Users able to open the Authentik
Dashboard can see the card; this does not lift External `/if/user/` restrictions.
External users should keep the direct link.

Declarative metadata: `deploy/identity/password-self-service-application.json`.
Bounded additive registration: `ansible/roles/authentik/files/password_application.py`.
Standalone plan/apply playbook: `ansible/playbooks/password-self-service-application.yml`
(use existing pinned `ansible_host=socrat-0` alias on owner Mac; apply only with
`password_application_apply=true`). No full Authentik bootstrap is required.
Existing drift stops rather than overwriting. Live create/detail GET verified;
second run made no changes. Private receipt on0:
`~/.cache/homelab-authentik/password-dashboard-166gap0q`.
This is an Authentik dashboard registration, separate from the Argo Application;
no new Kubernetes deployment was needed for the card.
