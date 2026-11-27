# OpenHands Agent Canvas — installation and acceptance

Updated 2026-11-18. **Partial acceptance, NOT a completed Ready-to-Review service.**

## Installed

Official Agent Canvas 1.41.0, pinned image digest, upstream vendored chart under
`charts/openhands`, Argo Application `deploy/argocd/apps/openhands.yaml`, values
`deploy/openhands/values.yaml`. StatefulSet `openhands-0` is on socrat-5. Retained
6Gi PVC persists both `.openhands` state and `workspace` using upstream subpaths.
Restricted PSA, non-root, no capabilities/privilege escalation/SA token/RBAC,
no Docker socket or host filesystem. Quota storage 12Gi is headroom, not PVC resize.

Local runtime is the official shared-container backend: **not per-conversation or
multi-user isolation**. Do not expose it as an unrestricted shared coding service.
No GitHub write credentials, App signer, production or Kubernetes credentials are
provided to coding tools. NetworkPolicy permits DNS, the actual LiteLLM pod label,
and public HTTP(S), excluding RFC1918, metadata, loopback and CGNAT destinations.
Public production hosts are not distinguished by this policy; it is NOT domain
allowlisting or proof against public-production probing.

## Native configuration, not LLM_* environment assumptions

Run `python3 scripts/provision-openhands.py` explicitly as the operator, after Argo
creates the app. It creates/preserves a distinct LiteLLM virtual key restricted to
`venice-deepseek`, max_parallel_requests=1, in Secret `openhands-model`. The independent OpenHands key replaced a copied SWE Mini key. Retiring SWE Mini
does not require modifying the OpenHands Secret, its key or personal Pi keys.

The helper uses the native settings, provider-connection, LLM-profile and
AgentProfile APIs and activates `socrat-deepseek`. Profiles reference an encrypted
provider connection; no GH integrations, extra secrets or MCP servers are enabled.
UI launchers require an AgentProfile: merely setting legacy agent settings made
API-started tasks work but left the UI's LLM-setup warning. Environment LLM_MODEL,
LLM_BASE_URL and LLM_API_KEY did not configure native settings and were removed.

Native backend owner key is saved, without printing, in
`~/.config/homelab/openhands/session-key` (directory0700/file0600). Do not commit,
paste into chat, put into URLs or share it: access allows shell and file operations.
`pbcopy < ~/.config/homelab/openhands/session-key` is private diagnostic/recovery
only, not the public login UX. Public access uses Authentik OIDC. Browser usage-reporting consent was opted out
in the diagnostic browser; do not assume that proves all SDK telemetry is disabled.

## Proven and not proven

- `7cb28d7a-87e3-4bcd-930f-5489faf77acb`: actual Venice/DeepSeek native tool calls,
  two terminal commands, `openhands-autonomy-ok` read back, then finish; no client
  connection was held open. Events and workspace are on PVC. Initial connection
  failure was a wrong NetworkPolicy pod selector; corrected via GitOps, then retried.
- `3760c11e-5e47-41c7-ba94-f8fed7fa3d43`: task submitted through the actual Canvas
  workspace picker/chat, waited for server acceptance, then closed the tab. Without
  a connected Canvas page, the agent executed a45-second wait/write command and a
  separate read/verify command, both exit0; exact `openhands-browser-closed-ok` proof,
  status `finished`, no conversation errors. Reopened the saved conversation in the
  browser and inspected both commands and final result in the native UI.
  This proves browser disconnect for this fixture, NOT public access/long PR autonomy.
- First browser attempt `d74c92f6-fd50-4b2a-a4bd-e14046763b4e` hit max_parallel_requests
  because native automatic naming overlapped the agent call. Restored SDK-default
  bounded `num_retries=5`; key limit remains1, no paid fallback or limit relaxation.
  The failed conversation is retained, not rewritten as successful. Closing a tab
  before the UI acknowledges creation can cancel submission; wait for acceptance.
- Longer PR500 pilot `e23f711a-5db2-47ce-a428-026d97a9bac9` cloned/read the repo but
  stopped with a future-intent sentence after a condensation event, without a
  candidate. `finished` is NOT evidence of task completion.
- Native Stop-hook fixture `1b272f96-cd72-4cdd-a59f-6d82455f14fd` deliberately attempted
  to finish without a file; the configured hook exited2, generated native environment
  feedback, and the agent automatically executed the missing command and finished.
  No manual continue message. This is a tested native feature, not a general task
  completion predicate installed for all UI tasks and NOT a PR-readiness guarantee.
  Exit1 is fail-open in the SDK hook contract; blocking hooks must exit2.
- GitOps pod replacement preserved native profile activation, owner key, earlier
  conversation history and workspace proof; no copied SWE model key remains in env.
- Publication, remote-CI follow-up and per-comment reply/resolve integration are
  NOT connected. `deploy/openhands/integration/READY_TO_REVIEW.md` is policy, not enforcement.
  `scripts/openhands-pr-ready.py` is a read-only fail-closed audit, not an orchestrator.

## Public entrance: standard Authentik OIDC; public DNS/TLS accepted

Canonical URL: **https://openhands.socrat.alchemmist.xyz/canvas/**.

**Current acceptance,18November after authorized DNS repair:** all four existing
Knot nodes received only the exact `openhands.socrat` failover name. Whole-fleet
preflight matched; all four health-state deltas preserve unrelated records; serial
refresh completed with private receipts and no daemon/node/VPN restart. REG.RU
nameservers/glue and other records were not changed. All three authoritative NS,
Google and Cloudflare now return both existing HOME/VPS entrances. The restored
`ansible/scripts/openhands-public-dns.py`/Ansible playbook is exact-name-only, not a general
zone editor; source and tests are committed.

Certificate `identity/openhands-oidc-tls` is **Ready=True**. Both public edges pass
normal trusted TLS (no `-k`), `/canvas/`302 to Authentik, API and WebSocket401
without SSO. Normal DNS HTTPS and valid-backend-key-only/forged-group denial also
pass. VPS initially returned502: its hostNetwork route selects **10.42.0.0** as
flannel source (verified on S2), so a precise `/32` ingress exception to proxy4180
was added; it does NOT open Canvas8000. Argo is **Synced/Healthy**, both pods Ready.
25 OpenHands unit/render tests pass. Browser opened the real public URL and reached
Authentik's existing login flow. **Positive owner MFA/callback/UI and public-domain
browser-close/reopen still need the owner's genuine login**; sudo credentials are
not reused as SSO credentials. Earlier loopback fixture is not substituted for this.

This is the intended final browser entrance, not a diagnostic port-forward.
Agent Canvas1.41.0 has no native human OIDC/RBAC; its owner backend API key is not
per-user SSO. The deployment uses official **oauth2-proxy7.15.6**, digest-pinned,
with native Authentik OIDC. There is no custom login handler or universal proxy rollout.

- `charts/openhands/templates/socrat-oidc.yaml`: dedicated gateway, Service, Ingress
  and NetworkPolicy in **identity**, which both existing Traefiks already watch.
  No shared ingress-controller restart/reconfiguration is necessary. The explicit
  Certificate is tracked by Argo, so pending TLS is not hidden behind healthy pods.
- Canvas stays in **openhands** on socrat-5. Its native direct ingress stays disabled;
  the ONLY application ingress terminates at oauth2-proxy, not Canvas8000.
  Canvas ingress NetworkPolicy permits only the labeled identity gateway pods.
- Authentik app `openhands`, confidential client `socrat-openhands`, strict callback
  `/oauth2/callback`, Code+PKCE S256. Existing signing key and authentication,
  explicit-consent and invalidation flows are reused without modification.
- **Only existing `homelab-owner`** is admitted, both by the Authentik application
  binding and by oauth2-proxy's verified `groups` claim. No users, memberships,
  platform roles, foundation objects or outposts are changed. Do not widen this
  to Internal/External/platform-operator: this backend is single-tenant shell access.
- Secure/HttpOnly/host-only/SameSite=Lax session cookie; configured8h maximum,
 2m refresh and5m access tokens. Live owner MFA, silent refresh, logout and group
  revocation remain human/roundtrip acceptance items, not claimed proven.
- oauth2-proxy's client/cookie credentials exist only in **identity/openhands-oidc**.
  Canvas/coding tools do not receive them or the operator's Authentik API token.
  No access/ID token or identity header is passed to the backend. Bearer bypass is off.
- Native `AGENT_CANVAS_ALLOW_LAN_SESSION_KEY=true` provides Canvas's supported HTML
  bootstrap AFTER the OIDC gate. This avoids a second manual backend-key login.
  Helm fails if this bootstrap is enabled without OIDC, or if the native direct
  ingress is enabled alongside OIDC. Backend keys alone must not bypass the gateway.
- As in existing SPI on S5, proxy-only hostAliases resolves the canonical Authentik
  hostname to existing Traefik Service IP **10.43.218.222**. Issuer/Host/SNI and TLS
  verification stay unchanged. Split-DNS192.168.0.250 is unreachable from S5.
  Egress covers the ServiceLB443/Traefik8443 DNAT path, not arbitrary private hosts.
  If that existing Service is recreated with a new ClusterIP, review this pin too.

Historical pre-DNS snapshot,18November12:55UTC (superseded above):

- Canvas and official gateway both1/1, gateway0 restarts after fixing initial startup.
  Argo **Synced / Progressing**, explicitly tracking Certificate readiness; its TLS
  Secret is not issued and `Certificate Ready=False`. Not advertised as ready.
- Private service-only HTTP test (NOT public TLS acceptance): `/canvas/`302 to the
  canonical Authentik authorization endpoint, expected callback and PKCE S256.
  Anonymous API, valid native backend-key-only, bearer-key-only, forged identity
  headers, forged cookie and WebSocket handshake all401. Callback with an actual
  generated state but no CSRF cookie403. Malformed state syntax instead yields the
  upstream500 error; neither case authorizes access or is represented as success.
- Restricted, no-token/no-secret/no-volume ephemeral acceptance Job on S5 verified
  issuer metadata using normal TLS validation, then proved a non-gateway pod cannot
  open TCP8000 to Canvas. Job completed and TTL cleanup removed it.
- Existing browser-closed proof is still exact on the retained PVC after rollout.
-20 OpenHands unit/render tests, Helm lint and server-side manifest dry-run pass.
- Both public edges tested with DNS-only `curl --resolve`, NO `-k`: certificate
  validation fails (curl60). Current authoritative `ns1/2/3.alchemmist.xyz`, resolved
  independently, all answer NXDOMAIN for the concrete OpenHands hostname.

`python3 scripts/provision-openhands-oidc.py` is a GET-only plan. Initial apply
requires its exact fresh plan hash and a <=1h encrypted identity backup receipt.
It creates only this provider/application/owner binding, uses private0600 journals,
stops on uncertain writes or identity drift, and delivers the dedicated proxy Secret.
It does not replay the identity foundation or rotate existing IdP credentials.
Existing private operator input: `~/.config/homelab/openhands/authentik-api-token.json`;
never mount it in Canvas or print token/client/cookie values. Initial pre-first-start
cookie encoding was corrected to Go's URL-safe base64 alphabet; this was not an
IdP signing/client-key rotation. Regression coverage uses deterministic non-secret bytes.

**Historical DNS blocker, now repaired by the exact-name addition above.** The owner reported an existing wildcard;
read-only checks on18November against all three public authoritative NS returned
`NXDOMAIN` for `*.socrat.alchemmist.xyz`; Google/Cloudflare and cert-manager's
in-cluster resolver also could not resolve the concrete OpenHands name. The HTTP-01
Challenge is pending on that lookup failure. Do not call a default certificate or
TLS-verification bypass a successful HTTPS test. At that snapshot no DNS record or authoritative renderer had been changed. The
retired exact-name helper was subsequently restored and applied with owner-authorized
sudo; it is now the tracked source for this scoped repair.

A wildcard is not required for the now-published exact name. DNS, native HTTP-01,
trusted TLS and anonymous-auth checks have since passed. Complete real owner MFA
and browser-close/reopen acceptance through the canonical URL; these remain distinct
from gateway availability and the earlier loopback-only fixture.

## PR500 was externally closed, not accepted as Ready

Latest inspection: CLOSED, unmerged at `2026-11-18T11:46:34Z`, head
`c538f659856d4cec8c966529c09ecca6dd942756`. This session had converted it to draft
while gates were red. Another writer merged main/regenerated workflows and closed
it as superseded by #503. These commits/closure were NOT performed by the OpenHands
pilot or this session. Do not reopen or overwrite that decision implicitly. Graph
validation is now green, Format check/Lint/Quality Graph remain red and dependent
jobs skipped; bot reviews are incomplete. Closing obsolete work is not a successful
Ready-to-Review acceptance. The audit now explicitly blocks CLOSED/MERGED/unknown
state and reassesses the final snapshot before reporting; no handoff or merge.

Earlier inspected head `c2be67056ea0e5c00a8d1be5238bd8c4fd50a820`, merge conflicts,
Workflow graph validation/Quality Graph red, other jobs skipped, CodeRabbit review
skipped for bot-authored PR. The actual graph error was three stale generated workflow
files (`uv run --locked --group quality-graph qg validate`); npm ci itself passed.
Current main `e2738ad` contains newer maintainer dependency updates that must not be
downgraded by conflict resolution. CodeRabbit needs a deliberate current-head review
request through the trusted handler. Never bulk-resolve remarks or treat skipped as
green. No merge or Ready-to-Review handoff has been performed.

### First real owner callback correction —18November

The real owner callback failed403: oauth2-proxy rejected `email_verified=false`.
No user/email-verification flag or membership was changed. This owner-only shell
service now explicitly uses the signed immutable OIDC `sub` as its internal
identity (`--oidc-email-claim=sub`); mail scope is not requested or used for linking.
Issuer/audience/signature/expiry/PKCE/CSRF checks and both owner-group gates remain.
No insecure allow-unverified-email switch was enabled. Retry from `/canvas/`, not
by replaying an already redeemed callback authorization code. Successful full owner
callback/UI acceptance remains pending until actually observed after this repair.

## Configured coding-loop demo — 18 November, 14:43 UTC

Owner reports Skip reached the main Canvas UI. Native active agent profile is now
`socrat-the-loop` (`b8cb1891-7251-47a3-96a6-ec38d238ae89`), backed by the existing
Venice-only `socrat-deepseek` profile, no additional secrets/integrations. Policy:
[THE_LOOP.md](../../../deploy/openhands/integration/THE_LOOP.md). `scripts/configure-openhands-loop.py`
installs the official filesystem MCP 2.4.0 using the tracked npm integrity lock,
`--ignore-scripts`, scoped only to `/home/openhands/workspace/the-loop-demo`.
MCP returned 16 tools, read TASK.md in the actual coding run, and rejected an
out-of-scope `/etc/hostname` read. This does not restrict the separate terminal
or turn the shared owner container into a malicious-agent isolation boundary.

Actual conversation `5787a58a-ed18-457f-805b-15103bc66608` ran without an attached
browser, recorded 7 failing / 3 passing baseline tests, implemented merge_intervals,
ran all 10 green and wrote HANDOFF.md. Agent's empty git diff on untracked tests
was NOT accepted as evidence: operator byte-compared to the tracked original and
validated the snapshot in fresh no-token/no-PVC/read-only, deny-all Jobs.
`scripts/validate-openhands-demo.py` repeats this without executing candidate code
on the laptop. It rejects overlapping NetworkPolicies (additive policy semantics)
and retains isolation until foreground Job/pod deletion succeeds. Last successful
candidate SHA256 `5d8ed77cb15618bc931c9adbba51ed8b8d7144a4489e78c3971d72512fea053b`,
original tests `ff6b7b66653b0d324d8cd6f521badb0acaac57f2dc6cd748d669117e3c377350`.
The workspace Stop hook uses exit2 on failure; feedback only, not security enforcement.

Native automation `54373c5f-fc35-4049-971b-52dd45fb3645` really fired by cron (not
manual dispatch). First run `c784db9a-9c3f-4733-8e42-eb78743ab4bb` FAILED at cold SDK
installation after timeout; retained as failed. Supported per-automation runtime
config now uses `setup_script_path:null`, `entrypoint:"python main.py"` with SDK,
tools and workspace packages already installed as 1.62.0 in the pinned image.
This is a workaround for this owned schedule, NOT a fix to every upstream preset.
New UI presets or prompt edits may restore cold installation; inspect runtime
settings rather than silently assuming scheduling works globally.

Second real cron run `bc3c6f26-20bc-422d-9c79-b0c33be3e9d9` COMPLETED, conversation
`8a801cb9-c41b-4640-ada0-2c87d28e5a0b`, wrote scheduled-proof.json at
`2026-11-18T14:36:05.061491+00:00`, actual test success. Future runs deliberately
INACTIVE, daily 08:00 Europe/Moscow (05:00 UTC), timeout300s, keep_alive false.
`scripts/configure-openhands-schedule.py` defaults GET-only; --apply creates/updates
only the matching owned schedule, always paused, never dispatches model work, and
refuses duplicates, incomplete listing, drift and active runs. Applied twice with
one schedule remaining. Source template: `deploy/openhands/integration/the-loop-demo/schedule.json`.
Internal callback base is loopback8000, not browser OIDC; public auth stays enabled.

Private loopback Playwright diagnostic independently reopened the persisted coding
history after rollout, showed `socrat-the-loop` + `socrat-deepseek` selected, MCP
connection test reported reachable (filesystem has no credentials), and Automate
showed inactive / latest Successful / 2 runs / 50% success, preserving the old failure.
This is NOT automated positive public SSO/MFA acceptance. Public owner onboarding
success is owner-reported; do not invent an observed public task/browser-close test.

Full the-loop PR publication/CI/current-head bot reviews, critical comment handling,
replies-before-resolve and trusted publisher are still NOT implemented. Demo code
success, cron, checklist completion and hooks must not be presented as PR Ready.

## OIDC refresh/relogin repair — 18 November

Owner reported frequent Authentik round trips. Logs showed concurrent refreshes
of the same cookie session, repeated >4KB split-cookie warnings, successful refresh
followed by `invalid_grant` and fatal session clearing. Cookie lifetime already8h;
provider access tokens5min / refresh tokens8h. Likely rotating-refresh-token race,
not an insufficient configured browser cookie lifetime.

GitOps now selects official oauth2-proxy Redis session storage: dedicated
`identity/openhands-oidc-sessions` Deployment/Service/NetworkPolicy onS5, official
Redis8.2-alpine digest-pinned, authenticated, nonroot/read-only/no-SA-token,
64MB noeviction session budget, no egress, ingress only same-namespace OIDC proxy.
Coding pod connection denial verified. No shared Authentik/LiteLLM Redis usage.
`scripts/provision-openhands-sessions.py` defaults GET-only, creates only this new
Secret via stdin with --apply, validates ownership/config and never rotates/adopts.
No changes to existing IdP/users/MFA/OIDC client/signing/cookie secrets or tokens.

Redis store supplies native per-session refresh locking and reload under lock in
oauth2-proxy7.15.6, avoiding concurrent redemption of stale rotated refresh tokens.
Browser gets a small session ticket rather than the token/claims payload in split
cookies. Cookie expiry8h, refresh2min, secure/HttpOnly/SameSite, verified issuer/TLS,
owner group authorization, CSRF and PKCE remain unchanged. No token lifetime increase.
Cache is memory-only: restart/loss forces reauthentication, never loss of Canvas
history/workspace. Recreate strategy prevents two independent session caches behind
one Service during rollout. This is not HA session storage.

Rollouts completed via Argo at `7c9452c9`; Synced/Healthy. Redis unauthenticated PING
rejected, authenticated PING passed, NX lock first acquisition succeeded and second
failed; test key removed. Public trustedHTTPS canvas302, APIs/socket401. Startup
has no errors. 33 local OpenHands tests + Helm lint passed. Existing browser cookies
may require one fresh SSO round trip during migration. Long-lived real owner refresh
acceptance still requires a fresh owner session and observation beyond token expiry;
do not claim proven8h convenience from startup/negative probes alone.

## Update watch registration and blocked upgrade —18November17:50UTC

Owner requested software-update alert coverage and upgrade. Registered target
`openhands` in `charts/monitoring-k3s/values.yaml`: GitHub `OpenHands/OpenHands`
(the actual Canvas1.41→1.42 release stream), not the unrelated agent-canvas1.6
or software-agent-sdk1.62 streams. Watch now reads installed StatefulSet image;
monitoring SA gets only GET statefulsets named openhands, no write. Six update-watch
unit tests passed. GitOps commit `b9bffcd9`, monitoring app Synced/Healthy.
Live exporter positively returned current1.41.0/latest1.42.0, available1, success1.
Generic existing alert `SocratSoftwareUpdateAvailable` remains warning/for15min.

IMPORTANT: exporter output is NOT end-to-end alert acceptance. Both Grafana MCP
and official socrat-metrics queries returned no current OpenHands series/alert.
Legacy Prometheus serviceMonitorSelector is retired; current static OTel scrape
ConfigMap has60jobs and no monitoring-update-watch. Existing ServiceMonitor alone
therefore does not establish this new target in the active collection path. Needs
narrow owning-source scrape integration and verification through Grafana/Thanos;
do not call the actual Grafana alert firing or fully operational yet. Do not
revive retired Prometheus scraping or casually restart the whole monitoring stack.

Latest stable1.42.0 confirmed via release API and image manifest:
`ghcr.io/openhands/agent-canvas:1.42.0@sha256:e2dc90908f08e51abf833cd3559bb0c4a61c53aab06210b6d92f867d281457ac`.
Image was NOT changed: pre-upgrade encrypted off-pod backup could not complete
reliably over exec transport (large WS streams timeout/EOF; bounded ASCII-chunk
attempts also exceeded time limits). SQLite quick_check and a small online backup
were OK; eight conversations were finished/error and automation inactive. This is
not evidence of DB corruption. Incomplete helper was not committed; temporary
plaintext tar archives and own stuck backup processes were removed. No verified
recovery receipt exists, no upgrade/rollback/backup-success claim. PVC, history,
SSO and running1.41.0 unchanged. Need verified bounded backup transport before
GitOps image bump, then active profile/MCP/history/schedule/SSO regressions.

## Red chats —18 November: distinguish three errors

The running Venice bridge `/app/agent_protocol.py` serializes protocol instructions,
all declared tool schemas, history metadata and all messages into UTF-8. Its
`MAX_AGENT_PROMPT_BYTES=120_000` is a guard on that FULL representation, not the
model's native token context. Original Monori conversation exceeded it: system
44,885 bytes plus ~55,433 non-message bytes left <20KB for everything else.
The provisioned live `v-deepseek-uc` agent had default broad tools, demo-only
filesystem MCP, and 240-event condensation without a token threshold. Repeated
`/run` and manual condensation did not fix that fixed-cost problem.

`e4bc9aaf…` briefly executed tools but its condenser lacked a resolved credential:
never roundtrip a redacted GET `agent` into a new conversation. Switching the
main LLM afterwards did not repair this separate summarizer. An unrelated
`o-deepseek` chat hit provider-side proof-of-work auth failure; that proxy was
not ready (separate owner), not a Canvas budget error.

Use `kubectl -n openhands exec -i openhands-0 -- python - < scripts/openhands-compact-profile.py`
for native compact profile creation/activation. Launch with `agent_profile_id`,
NOT a serialized agent. Existing profiles remain selectable. Only terminal/editor,
no MCP; existing encrypted Venice connection resolved at launch. SDK constructor
copies resolved LLM for condensation. Budget threshold 9000 estimated tokens or
32 events, not a proof for arbitrary large single messages. No adapter increase.
Current Monori continuation `1ab3985a-2193-4177-8dd2-8ec7d54dbfeb` shares workspace;
initial system event ~15.5KB. No changes to runner identity, model keys or history.

Do NOT trigger `/condense` concurrently with an active run. Observed max_parallel=1
contention, hung agent-server health checks and Canvas supervisor restart during
that diagnostic. Resume through `/run` ONLY after checking persisted state and
latest events; check new post-recovery actions, not just `running`. Never erase
historical errors or silently substitute a different provider. Rollback default
profile by activating saved `socrat-the-loop`; no PVC change required.

## No iteration-count termination (owner opt-in, Canvas1.41 / SDK1.62)
`deploy/openhands/values.yaml: unlimitedIterations` disables only the six local
SDK comparisons against the per-run step counter and the goal audit cap. Native
schemas still store positive 30/200/500 etc.; these are no longer stopping
conditions for this deployment, including restored conversations and task workers.
No PVC edits or secret mounts in the preparing init container. Two Python sources
from the pinned image are SHA-checked and compiled in emptyDir; read-only overlay
is mounted solely in Canvas. Remove/disable the value to restore stock behavior;
image changes must explicitly revalidate or remove overlay. Does not suppress
confirmation, pause, finish, errors, stuck detection, provider limits or quotas.

## Cold full-claim recovery checkpoint —19 Nov 2026

Retained `data-openhands-0` while Canvas was scaled to zero via Argo. Offline
`openhands-cold-backup-20261119` archived both full PVC directories without
exclusions. Streamed gzip + AES256-GCM; separate retained 3Gi claim
`openhands-cold-backups`, `canvas-cold-20261119.{gcm,json}`. OAEP/SHA256
recipient private key stays on operator laptop. Job authenticated reread of
ciphertext before parsing tar, verified critical restored bytes against cold
source, restored automation DB/WAL into disposable tmpfs, SQLite integrity OK,
settings/HANDOFF and both conversation base JSONs and history present. No writes
to source or restoration over live history. Owner-key unwrap proof and private
receipt: `scripts/verify-openhands-cold-receipt.py`; 798911317 ciphertext bytes,
125353 members, SHA256 2a556be3e9da39732dc03455b65517ceb8cd233447047b85657cc5af0a14ecdc.
For disaster recovery, authenticate entire ciphertext **before** trusting tar.
Use AES GCM IV/tag from receipt, AAD = ASCII `openhands-full-claim-v2`, wrapped
key RSA-OAEP-SHA256/MGF1-SHA256. Restore into an isolated empty volume first,
not over live data. This is a same-node checkpoint, not off-site DR or a full
application boot test. Do not replay this dated Job against a running Canvas.
Old failed pre142 attempt (UID fc7f87f8-226f-4ef5-a357-38d3358feed0) ran
18 Nov18:15 UTC, exit1, no retries; reason unavailable. Both old claims kept.

### Retired mutation-testing integration

The issue-509 pilot, report consumer, author/judge and mutation publication are retired. Do not reinstall the legacy units. The separate Monori application and Canvas QA publisher remain.

## Upgrade to Agent Canvas 1.43.0 — 23 Nov 2026

Vendored chart tracks upstream `helm/agent-canvas`; the only upstream change
v1.41.0→v1.43.0 is `appVersion` (release-please). Chart, templates, UPSTREAM.md
and all image pins (StatefulSet guard, cold/upgrade backup Jobs, demo validator)
moved to `ghcr.io/openhands/agent-canvas:1.43.0@sha256:bcdbb3fb9610f14eda67f39fc609f162ad8c3c28697d6ff3f4adae55c15c3f1d`.

SDK iteration overlay revalidated inside the new image before commit:
`local_conversation.py` still holds exactly 6 `iteration >= self.max_iteration_per_run:`
conditions, `goal/controller.py` exactly 1 `self.iteration >= self.max_iterations:`;
both patched copies compile and mount over stock files read-only. Overlay digest
constants updated (`01a20677…`, `651761b9…`).

Post-upgrade runtime exposed the real migration gap: dispatcher and scheduler
erred (`automation_runs.deferred_until`, `automations.factory_id` missing). Alembic
037→040 applied explicitly in the pinned image (postgres+pg8000, TLS verify-full,
per the automation_transfer precedent; startup auto-migration stays disabled).
038/039 are additive columns/index, 040 adds the `factories` table plus nullable
`automations.factory_id`. Pre-migration logical dump from the CNPG primary:
`pg_dump --no-owner --no-privileges`, 14 COPY blocks, 38 KB, SHA256
4731be85a1e3b96f536eb4ed2a70c8d5e953a0dc666fc5f1d219e76c689f8cba. After restart:
alembic version 040, `/health` ok, zero ERROR lines in container logs, Argo Synced.
Both dated cold/upgrade claims and the new dump are operator-side artifacts; a
verified off-site copy of the automations dump is still open work.

The completed immutable `openhands-cold-backup-20261119` Job (Job specs are
immutable, its rendered image had to follow the bump) is retired: flag false, Job
and its ConfigMap deleted from the cluster. The retained `openhands-cold-backups`
claim still renders permanently (Prune=false,Delete=false) like
`openhands-upgrade-backups`. Owner journal evidence lives in the sealed receipt
from 19 Nov; do not replay the dated Job.
