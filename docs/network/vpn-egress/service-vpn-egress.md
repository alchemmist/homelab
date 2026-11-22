# VPN-as-a-service for applications on the Russian nodes

An owner-agreed architecture, November 17, 2026. Do not confuse it with the
previous SSH-egress for n8n: that was an erroneous architectural decision and
has been replaced.

## Three different tasks

| Task | Mechanism | Boundary |
|---|---|---|
| Node connectivity and infrastructure transit | `wg-socrat` | VPN-as-infrastructure; does not give an application a foreign exit |
| Administration | NetBird + ordinary SSH with a personal identity | Not an application proxy and not a common exit node |
| An application's foreign access | A separate client and a **3x-ui** subscription, an ordinary VPN client in a Pod | VPN-as-a-service; its own accounting, limits and revocation |

The last task must not be solved by adding an SSH tunnel to NL, using an
administrative key, exiting directly through the mesh, or changing the whole
node's default route. The existence of a working bypass does not mean
compliance with the architecture.

## The ordinary path

```text
An application in a Pod on a Russian node
  → the local entrances of the ordinary VPN client
  → a profile from the subscription of its own 3x-ui service client
  → the existing Moscow VPN-as-a-service entrance
  → the existing infrastructure transit Moscow → NL
  → the VPN backend in NL → the destination
```

`wg-socrat` can protect the existing inter-server infrastructure leg. It does
not replace the service identity: the application connects as an ordinary
VPN-as-a-service client. Personal clients, subscriptions and user routing are
not changed.

## The order of granting access

1. Record the service, namespace, required destinations, protocols, owner,
   quota and validity period. For permanent service clients: the `services`
   group, without a quota or automatic expiry unless the owner explicitly set
   otherwise. Identity is per service, not one shared by all Pods. Several
   replicas of one service require an agreed `limitIp`.
2. Through the **native 3x-ui API/UI** create a named client, for example
   `svc-n8n-google`. Bind it only to the needed working inbound. Do not create
   a new listener/server per application. Do not write to SQLite.
3. Store the own subscription in a Secret/private credential custody. The
   subscription URL is a bearer credential: do not print it, commit it, or
   insert it into public-URL diagnostics, issues or logs. Do not copy a
   person's subscription.
4. Choose an ordinary server client for the real subscription format. Do not
   assume that the Happ GUI runs headless. n8n uses the official Xray-core and
   the **native JSON endpoint of the same 3x-ui identity** for which the
   panel also issues an ordinary URI/Happ subscription. That is another format
   of one subscription, not a hand-assembly of server credentials and not a
   separate account system.
5. Connect the application to the client's local proxy/entrances only for the
   agreed destinations. No hostNetwork, NET_ADMIN, TUN or node route changes.
   A global HTTP_PROXY is allowed not by default, but only if all the
   application's traffic really must go through the service VPN.
6. Deploy via Git → Argo. Native identities/Secrets are issued separately; the
   Secret reference, the client, the local policy and the image version are
   managed by Git. For stateful n8n a fresh **global** natural drain and
   SPI owners/processing/paid=0 are mandatory. Do not cancel
   Wait/executions for the sake of a rollout.
7. Verify the real path, TLS, the restrictions and the natural operation of
   the service. Only after acceptance delete the temporary/erroneous old
   mechanism.

Creation via API: intent before writing, a unique name, native readback and a
comparison of old clients/bindings. On an unknown POST result first check the
existence of your identity; do not blindly repeat the creation. Temporary
administrative API tokens must be deleted; the application does not need them.

## The n8n implementation — the current example

- Panel client: **`svc-n8n-google`**, ID **40**, only the working
  VLESS/REALITY inbound **32053**. The public endpoint is taken from the
  subscription: the existing Moscow one, not direct NL. By the owner's
  explicit decision the client is in the **`services`** group, **without a
  traffic quota and without automatic expiry** (`totalGB=0`, `expiryTime=0`),
  `limitIp=1` preserved. The initial 5GiB/90 days were removed; accumulated
  traffic was not zeroed. A quota and an expiry for a permanent service are
  set only by agreement, not as a hidden cut-off point.
- `automation/n8n-service-vpn` contains the `subscription-url` of the native
  JSON subscription.
- The init `prepare-service-vpn` fetches the subscription over HTTPS with
  ordinary TLS verification, no redirects, with a timeout/size limit. It
  selects the single VLESS/REALITY profile with the expected Moscow endpoint.
  Credentials and Reality settings are taken from the native renderer without
  reinventing the VPN protocol.
- A small adapter **only prepares the configuration**: removes foreign
  listeners and the routing/direct fallback, and adds two local
  `dokodemo-door` entrances. The VPN transport and cryptography are performed
  by the official **Xray-core 26.10.21** from the same pinned image used by
  the ordinary 3x-ui.
- The `service-vpn` sidecar: UID/GID1000, read-only rootfs, drop ALL
  capabilities, no serviceaccount token; 32 MiB request / 128 MiB limit, CPU
  limit200m.
- The configuration with credentials lives only in a memory-backed emptyDir,
  mode0600. The source link is available to the init, not to the application
  container.
- The entrances listen **only on the Pod loopback**:
  `127.0.0.1:18443 → www.googleapis.com:443`,
  `127.0.0.1:18444 → oauth2.googleapis.com:443`.
  This is not an open SOCKS/proxy; there is no Kubernetes Service/Ingress for
  these ports.
- The n8n transport uses them only for the two exact Google hosts:443. TLS
  stays **end-to-end n8n → Google**, with the original SNI/CA/hostname
  checks. HTTP gets only a verified TLS socket. No OAuth POST replay or direct
  fallback. GitHub, Yandex and the other destinations use the previous path.

### Subscription updates

The current implementation fetches the profile **at Pod startup**. That is not
a hot refresh and not an infinite live Happ GUI. Changing the
endpoint/protocol requires a controlled Pod update via Git and a drain; an
unknown/ambiguous profile fails closed. Identity revocation and limit
exhaustion are enforced by the 3x-ui backend even if the old profile is still
in the client's memory. Do not restart Xray in the middle of requests for a
refresh timer's sake: this could cut off an OAuth POST or another application.
Do not change existing users' subscriptions to update one service.

## Acceptance and revocation

- TLS to the real required resource passes through the VPN; TLS verification
  stays enabled for both the subscription and the resource. A single
  `Connected` is insufficient.
- The absence of a common exit route and of a direct path for foreign
  destinations has been verified.
- The service client is visible in the panel; the previous clients, bindings
  and credentials are preserved. Do not use someone else's traffic as proof
  of your identity.
- Config/hash/Argo/HEAD are separated from the natural scheduled workflow,
  paid model, voice/Telegram or a refresh POST. Do not create such events for
  a test.
- Revocation is disabling/deleting **your own** service client through native
  3x-ui and removing only its unused Secret after the Git transition. Do not
  delete shared inbounds, change other clients' keys, or restart the VPN for
  everyone.
- Quota, expiry, subscription loss, a Moscow/NL failure and the sidecar are
  separate causes of denial. No guarantee of HA/eternal availability/night
  monitoring.

## History and boundaries

The n8n fix: `5b722c5c`, fresh global pending[]/SPI0, 48 Node tests. Two
unauthenticated Google HEADs through the real service client from socrat-5:
TLS verified, roughly373/272ms. After the Git rollout the Pod is Ready2/2, Argo
Healthy; the runtime Google HEAD goes through loopback/VPN, GitHub directly.
All7 native workflow graphs/settings/credentialrefs/static/pin/activity, the
PVC and the encryption Secret are preserved. The old n8n SSH sidecar was
removed, its separate authorized_keys line revoked, its two unused Secrets
deleted. The common registry robot was not revoked. Archive private receipts
are preserved separately.

**Venice is not migrated yet:** its former SSH-egress is a known deviation,
not a recommended template. Do not change the live browser session/identity
together with n8n without separate preparation and acceptance.

See also [VPN](vpn-hardening.md), [network boundaries](../README.md),
[Venice](../../applications/ai/venice-api.md), [n8n](../../n8n/n8n-workflows.md).


### Native client changes: account for the installed panel version

For the accepted **3x-ui3.11.0** the group is created via
`POST /panel/api/clients/groups/create` with `name=services` (not
`/api/groups`). Updating a client is `POST /panel/api/clients/update/:email`.
In this version you must send the client's full saved fields: the
partial-update behavior of the current upstream main is not a contract of the
installed release. Get the source fields via a native GET, preserve
UUID/password/subId and all the other settings, and change only
group/totalGB/expiryTime. The numeric ClientRecord ID and the protocol UUID
are different fields; do not send the record ID as the UUID. After an
indefinite error, first a readback — do not blindly repeat the write. No SQL
UPDATE, resetTraffic, subscription rotations or Pod restarts for a quota's
sake.

17Nov: the services group (ID3), the client svc-n8n-google (ID40),
quota0/expiry0/enabled. Full verification: the other clients and bindings
unchanged, own credentials/subscription unchanged, counters not reset,
temporary API tokens deleted.

## A detailed runbook: a new service from request to operation

### 1. First describe the access, then create the identity

Before changing the panel, fill in a card in the service's operational
documentation:

| Field | What to record, without secrets |
|---|---|
| Service and owner | Who is responsible for the access and accepts the result |
| Identity | A unique `svc-<service>-<purpose>`, the `services` group |
| Placement | Namespace, workload, replica count; not tied to a random Pod name |
| Destinations | Exact host:port, TCP/UDP, APIs and separate OAuth/token endpoints |
| Direct traffic | What must stay outside the VPN: internal APIs, DNS, storage etc. |
| Inbound | One existing compatible inbound; the reason for this protocol choice |
| Client | The official implementation, version and immutable image digest |
| Secret | Only namespace/name/key and the custody owner, never the content |
| Updates | When the subscription is read, how the profile changes and what needs a rollout |
| Acceptance | Safe path checks and the expected natural business result |
| Revocation | The specific identity and its dependencies; no shared keys/inbounds |

Do not issue one `svc-shared` to all applications. Different services must be
independently revocable, have an understandable spend and not share a
subscription URL. Replicas of one service may use one identity only with a
deliberate access model. Agree `limitIp` with the real transit: the backend
may see the relay address, not the original Pod. It is not a reliable Pod-count
boundary or theft protection. The preserved `limitIp=1` of n8n is not a
universal standard.

**Agreed defaults:** the `services` group, traffic without a quota, without
expiry. A different limit is only the owner's explicit decision, with a clear
renewal procedure and a warning before the cut-off. Do not add 5GiB or 90 days
“just in case”.

### 2. Issue a client in the existing 3x-ui

1. Log in through the ordinary administrative UI/API. Do not use a human
   subscription, default passwords, an MFA bypass, browser-session reading or
   SQL writes.
2. Find the `services` group; create it only if absent. Check the client name:
   if it already exists, first sort out the owner and the state instead of
   generating a second identity after the previous request's timeout.
3. Take a private preimage: existing clients, bindings, own counters and
   relevant settings. Do not carry a full panel export into Git/chat.
4. Create your client and bind it to the chosen working inbound. Do not create
   a new panel, server, shared listener or an application SSH key.
5. For a permanent client set `totalGB=0`, `expiryTime=0`, enable=true. In
   this model zero means the absence of a limit, not zero allowed traffic.
   The API's `totalGB` field stores **bytes**, despite the name.
6. Verify the native readback: one new identity, the right group and inbound,
   the other clients/credentials/bindings unchanged. Delete temporary API
   tokens.

For the accepted release3.11.0 the following **relative** native endpoints
are useful (the real web base path is determined by the installed panel, not
guessed):

| Action | Endpoint under `/panel/api` |
|---|---|
| List groups | `GET /clients/groups` |
| Create group | `POST /clients/groups/create`, JSON `name` |
| Read a client | `GET /clients/get/:email` |
| Create a client | `POST /clients/add`, JSON `client` and `inboundIds` |
| Update a client | `POST /clients/update/:email`, full Client fields |

This is a reference for a specific version, not permission to automatically
run all the requests. An HTTP200 response is not success: check the native
`success` and the readback. The GET returns a ClientRecord: the numeric `id`
is not the protocol UUID. When preparing a Client for update, keep `uuid` as
the protocol `id`, plus its own `subId`, password, auth, flow, enable and the
other fields. Do not send the whole GET response in the POST: it contains a
wrapper, statistics and fields of another type. Another protocol needs its
own full correct payload, not a mechanical copy of the VLESS example. Check
the **installed release**, not the shifting upstream main.

### 3. Subscription, Happ and headless compatibility

A subscription is a renewable profile delivery for an identity, not the name
of a VPN protocol. Happ may be a user-side consumer of such a subscription,
but that does not mean the Happ GUI is suitable as a Kubernetes sidecar.
Three things must be verified:

- What the endpoint actually delivers: a URI/base64 list, native Xray JSON,
  or another format.
- Whether the chosen official core supports exactly that transport/security
  and settings syntax. Matching on the word VLESS is insufficient: REALITY,
  XHTTP, peer identity parameters and the client version matter.
- How to apply only the needed local listeners and routing without importing
  a foreign general-purpose proxy, direct fallback, DNS or a global route.

For n8n the native JSON endpoint of **the same service identity** was chosen,
not a conversion of a Happ profile by guesswork. The adapter keeps the native
outbound and adds only local entrances; it does not implement the tunnel, the
encryption or a manual peer-key substitution. Do not add a random external
online converter: the subscription would leak there.

Keep the URL in a separate Kubernetes Secret and private custody. Do not pass
it in a command line, Helm values, Git, tickets, screenshots or access logs.
Create/update the Secret through the permitted secret-management mechanism,
private stdin or a protected file; do not insert the value into shell history.
Git contains the Secret reference, not the credential itself. A Kubernetes
Secret's base64 is not encryption; Secret read rights and `exec` into the Pod
must be restricted.

### 4. Connect the client to the application only

The preference is the application's ordinary proxy setting with an exact
destination allowlist. If there is none, document the narrow transport
adapter, as in n8n, and its boundaries: a new HTTP SDK, HTTP/2, WebSocket or
another connection method may need separate support and re-acceptance.
`HTTP_PROXY`/`HTTPS_PROXY` are not universal: different libraries read them
differently, and the variable may send the unnecessary parts into the VPN.

The minimal Pod model:

- the init fetches the subscription with HTTPS verification, time/size
  limits, no redirects and no full response output into logs;
- the configuration is created atomically in a memory-backed volume, mode0600;
- only the official core with the pinned version/digest performs the VPN
  transport;
- local entrances listen on `127.0.0.1`, without Service/Ingress/NodePort;
- unprivileged UID, read-only rootfs, dropped capabilities, bounded resources;
- no TUN/NET_ADMIN/hostNetwork and no node default-route/DNS changes;
- the application's TLS to the final API stays original: SNI/hostname/CA
  verification;
- a VPN error does not switch the chosen destination to a direct path
  automatically.

**Security boundary:** the loopback and allowlist in the configuration are a
restriction of the application's ordinary path, not a server-side ACL by
domains and not protection from a fully compromised Pod. The Pod's containers
share the network namespace; a process with access to the client
configuration can steal the credentials. Do not claim that the 3x-ui identity
is technically limited to Google if no server-side ACL was configured. A
stricter isolation needs a separately agreed design, not such a declaration.

### 5. Verify before and after Git → Argo

Before the rollout: offline tests of profile parsing and scope, the Helm
render, a resource/security review; then the final safe check of the real
profile from the needed node. Do not run paid inference, a manual workflow or
a notification for the sake of a network check. Do not restart the working
service until the image, the Secret and compatibility are ready.

For n8n the existing natural global drain rules apply: all native pending
executions empty, including Wait, SPI owners/processing/paid=0; pause only
permitted admissions; the original activities recorded and then restored. A
fresh check immediately before the replacement. Executions must not be
canceled for a pretty zero. Save workflow IDs/graphs/settings/credential
refs/static/pin data, the PVC and the encryption Secret. For another
application first define its drain/state contract, do not blindly copy the
n8n procedure.

After reconciliation collect separate proofs:

| Level | What it actually proves |
|---|---|
| Git/render/Argo | The needed spec is applied; not a successful external request |
| Pod/core/config | The client runs with the needed profile; not API availability |
| TLS to the needed API | The path and peer verification work; not OAuth authorization |
| A foreign host | The direct path of that destination is untouched |
| Negative scope | No public proxy, unneeded listeners, broad routing/fallback |
| Native panel readback | The right service identity, group, limits and the safety of the others |
| A natural event | A real business process completed in the observed final window |

A random REALITY shortId may change between native renders. In that case
check that it belongs to the inbound's allowed set, with the other identities
and transport unchanged. Do not change keys or disable TLS for an identical
hash. Do not mix HEAD/TLS with an OAuth refresh POST, voice/Telegram
delivery, HA or an “all night” check. Expect only real permitted events.

### 6. Operation and changes

| Event | What to do |
|---|---|
| Change group/quota/expiry | Native client update preserving credentials and counters; no resetTraffic |
| Update the native profile | Verify format/core; a controlled rollout per the drain contract |
| Change the core version | Git pin, compatibility and tests before rollout; no live image override |
| Startup subscription fetch fails | Check HTTPS/DNS/the native endpoint without printing the URL or the response with credentials |
| TLS to Google does not establish | Separate the localhost client, the VPN handshake, the transit and the final API TLS |
| TLS works, the API answers401/403 | Check the application authorization/API quota; do not call it a VPN break |
| A control POST timed out | Native readback and checking your intent, not an automatic repeat write |
| The service is removed | Remove the consumer via Git, revoke your identity, then remove the unused Secret |
| The subscription is compromised | An agreed revocation/rotation of only that identity with a safe consumer replacement |

A limited quota, if explicitly agreed, is a total limit until a periodic reset
is separately configured and verified. Do not automatically call it monthly.
On reaching the quota or the expiry the backend stops passing the client's
traffic; the application sees its own VPN-path errors. Removing the limit
must not zero the spend history. Unlimited gives no HA: a Moscow/NL/
subscription/sidecar failure stays a separate operational dependency.
Monitoring and notifications need a separate implementation; this section
does not mean they are already configured.

Do not test production revocation by disabling the only working client
without permission. On a planned removal first remove all consumers, then
revoke your own access; on a leak the priority may be immediate revocation
with a deliberate interruption. Do not delete the shared inbound, a group
with foreign clients, the common registry robot, administrators'
NetBird/SSH keys, or Venice's access together with n8n's.

### Completion checklist

- [ ] Own identity in `services`; inbound and owner recorded.
- [ ] No unagreed quota/expiry; limitIp matches the transit model.
- [ ] The subscription only in Secret/custody, not in public materials.
- [ ] The official client is compatible with the actual native profile.
- [ ] Only the needed destinations go into the VPN; other paths and TLS preserved.
- [ ] No new SSH-egress, common node routing or public proxy.
- [ ] Deployment via Git/Argo; state and drain observed.
- [ ] Runtime/path and natural acceptance recorded separately with boundaries.
- [ ] Temporary admin tokens deleted; the former mechanism removed only after acceptance.
- [ ] Refresh, revocation, failure and open checks documented.

## Application candidates after incident #404

Do not issue a client merely for contacting a foreign domain. On the November
21 check, `img-proxy`, `remark42` and `socrat-bot` were already on **socrat-2
(NL)**. A path through Moscow back into NL is not an independent reserve by
default.

| Service | Destination and condition for switching |
|---|---|
| `img-proxy` | Nginx contacts `images.weserv.nl:443`; the ordinary Pod network. If moved to a Russian node with a confirmed need — a separate service identity, a fixed local entrance only for this upstream, and verification of the original TLS name. |
| `remark42` | Telegram is a separate destination, not the application's whole traffic. Currently `hostNetwork: true`: first verify the ordinary pod network, ingress, authorization, notifications and the data binding. |
| `socrat-bot` | For a Telegram response timeout first measure the direct path. Currently `hostNetwork: true`: a loopback sidecar would be the node's loopback. Before issuing a subscription verify the migration to the pod network, the webhook, the Service and all consumers of the direct `10.250.0.2:8082`, including SPI. |

A one-time direct measurement from the current bot container (without a token, HTTP requests or messages):

```bash
kubectl -n socrat-bot exec -i deploy/socrat-bot -- python - < scripts/telegram-egress-probe.py
```

For comparison run the same file at the same time from a trusted environment
on another node with Python 3.11+ and CA. This checks direct sockets, not a
trace of the application's real request: compare Telegram and the control
`example.com` **by address family and stage**, and do not count the absence
of IPv6 as an IPv4 failure. A one-time test's results do not explain the
past timeout. If an application VPN is really needed, use the issuing order
above, not Happ on the host; do not change user subscriptions, etcd routes or
the management relay.

After shipping the periodic diagnostics: the `telegram-path` container in the
bot pod and a separate `socrat-telegram-path-control` on `socrat-3` every 30 s
collect the same direct measurements. The last 120 cycles (about an hour at
normal latency; missed intervals are not caught up) are kept only in a
bounded memory-backed volume; a Pod restart deletes them. Save the window on
a repeat, do not wait a day. Read `kubectl -n socrat-bot exec deploy/socrat-bot -c telegram-path -- cat /samples/recent.json`
and the same for `deploy/socrat-telegram-path-control`. This is not access to
the bot's secrets. The control route is not a failover. Toggling
`telegramPathProbes.enabled` changes the pod template and causes a
**Recreate**: first run both Service probes and check the current SPI path;
during the rollout observe from the same pods without a restart.
