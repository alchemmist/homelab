# Private Syncthing interfaces

Each Socrat node runs one independent Syncthing device in the Helm DaemonSet.
Its identity, database and folders remain under `/srv/syncthing` on that node.

Connect the Mac's `wg-socrat-admin` profile, then open:

| Node | Private interface |
| --- | --- |
| socrat-0 | `https://0.socrat.alchemmist.xyz/sync/` |
| socrat-1 | `https://1.socrat.alchemmist.xyz/sync/` |
| socrat-2 | `https://2.socrat.alchemmist.xyz/sync/` |

The existing BasicAuth username and password are retained. The nginx sidecar
mounts the existing `syncthing-basic-auth` Secret; no password or password hash
is stored in this repository. `/sync` redirects to `/sync/`, and paths outside
`/sync/` return 404. Syncthing's GUI/API listens only on `127.0.0.1:8384`.
Public `sync-0`, `sync-1`, and `sync-2` ingresses are removed.

## Traffic and TLS

The proxy binds the local WireGuard IP on TCP 18443. An owned nftables table
maps TCP 443 to that listener only for traffic arriving on `wg-socrat` to the
node's WireGuard address, plus local connections to that same address.
Its NAT priority is -110, before the Kubernetes destination-NAT rules. Public
HTTPS listeners and the user VPN keep their existing addresses and ports.

The administrator INPUT firewall permits this translated connection only when
its original destination port was 443. Direct administrator access to ports
18443, 18444, and 8384 remains blocked. Other node peers can access the private
HTTPS listener; its BasicAuth remains mandatory.

cert-manager manages `syncthing-private-ui-tls`, covering the private names.
The existing `letsencrypt-http01` ClusterIssuer publishes only temporary ACME
challenge paths through the public ingress. Certificate issuance and renewal
depend on working public DNS, ingress, and the control plane; serving an
already-running node's private UI uses its local proxy and projected Secret.
The nginx sidecar reloads when the projected certificate changes.

Uptime Kuma checks `http://<node-WireGuard-IP>:18444/healthz`. This listener
exposes only Syncthing's `/rest/noauth/health`, with all other paths returning
404. Monitoring therefore checks the actual Syncthing backend rather than
treating a proxy authentication challenge as application health.

## Apply

From `ansible/`:

```bash
ansible-playbook playbooks/syncthing-private-ui.yml \
  -i inventory/hosts.yml -i inventory/direct.yml --ask-become-pass
```

The playbook records public certificate fingerprints, device IDs, and folder
pause states; prepares the trusted certificate; configures private HTTPS on
each host; and rolls the DaemonSet with Helm's atomic rollback. It verifies
that the BasicAuth fingerprint and the recorded Syncthing state are unchanged.
Unchanged Helm manifests skip upgrades. A failed read-only manifest comparison
does not change the deployed release.

Only existing Syncthing Kuma monitors are migrated. When their configuration
differs, Kuma is briefly scaled to zero, its database is backed up locally with
mode 0600, the selected monitor fields are updated, and its previous replica
count is restored. Reapplying unchanged monitor settings does not restart Kuma.

`apps.yml` and `syncthing-backups.yml` generate the same private Helm values.
The GUI node registry and certificate names come from `wg_socrat_nodes` and
`homelab_ssh_public_host`; they do not require editing the chart for each node.
For a new node, first register its WireGuard identity and address, configure its
private connectivity and the administrator's client routes/resolver, prepare
the host with `syncthing-nodes.yml`, and reapply this playbook. Device pairing
and the set of synchronized folders remain separate configuration.

## Verify and recover

With WireGuard active, an unauthenticated GET to `/sync/` must return 401 with
the Syncthing BasicAuth challenge and a valid certificate. `/sync` must return
a relative `/sync/` redirect, without exposing port 18443. Sign in with the
existing credentials to use the GUI. Public addresses must not serve the UI.

Verify `kubectl -n syncthing get ds,pod,certificate,ingress -o wide` and
`systemctl status wireguard-private-web.service wg-socrat-admin-firewall.service`.
The DaemonSet must have one ready two-container pod per registered node, a
ready private certificate, and no public Syncthing ingress.

Local SSH recovery can reach the backend through a tunnel without publishing
it:

```bash
ssh -i ~/.ssh/socrat-master -p 2222 \
  -L 18384:127.0.0.1:8384 alchemmist@0.socrat.alchemmist.xyz
```

Full rollback to a previous public Helm revision reopens its public ingress;
use it only when that exposure is intended. Host rule removal is described in
`ansible/roles/wireguard_private_web/ROLLBACK.md`. Never delete hostPath data,
regenerate Syncthing identity keys, or unpause backup folders as part of UI
recovery.

## Deployment checks on 2026-10-14

All three nodes reached 3/3 DaemonSet readiness with two containers per pod.
The existing BasicAuth contents, public device certificates, device sets, and
folder pause states matched the pre-migration snapshots. Private DNS, trusted
TLS, `/sync` redirects, mandatory authentication, blocked raw GUI ports, and
public 404 responses were checked from the Mac. All three node health
endpoints returned HTTP 200 with `status: OK` from socrat-2. Kubernetes nodes
remained Ready. A complete browser session using the user's password and a
node/router reboot are separate manual acceptance checks.

## Review and reapplication on 2026-10-15

Reapplied `syncthing-private-ui.yml` successfully on all three nodes. The Helm
release and Kuma monitors were unchanged, so neither was restarted. The
comparison utility was updated on the controller, and the Arch package cache
was refreshed. Authentication fingerprints, device identities, configured
devices, folder paths, and pause states matched the pre-run snapshots.

The manifest comparison now aborts on cluster/read errors; only an explicitly
missing release permits installation. A failed snapshot, certificate setup,
deployment, or identity verification stops the playbook across all hosts.

Verified all nine node-name/resolver combinations, SSH with explicit identity
files, trusted HTTPS, `/sync` redirects, authentication challenges, and blocked
raw ports from the Mac. Requests for both old public names and new private
names through either public IP returned 404. All three backend health checks
returned `status: OK`; the host DNS, WireGuard, firewall, and private web units
were active and enabled. The full local suite passed 75 tests, Helm lint
passed, and the relevant Ansible playbooks passed syntax checks.

The proxy subpath follows the upstream
[Syncthing reverse proxy configuration](https://docs.syncthing.net/users/reverseproxy.html).
An authenticated browser session and reboot/failure-injection checks remain
separate acceptance checks; this review did not restart nodes or the router.
