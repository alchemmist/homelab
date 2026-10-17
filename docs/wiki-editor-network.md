# Wiki access and optional WireGuard routing

The runtime serves public reading and locally authenticated editing on `wiki.alchemmist.xyz`. Users can sign in at `/login` from the internet or the administrative WireGuard network. Authorization comes from reader/editor/administrator accounts, not network membership. OIDC is not configured.

Production public ingress and both private virtual hosts have switched to the shared runtime. Local administrator login/logout over HTTPS was verified through public `109.173.40.247` and private `10.250.0.1` addresses. See [the migration runbook](wiki-runtime-migration.md) for data preservation and rollback.

## Gateway cutover

`ansible/playbooks/wiki-editor-access.yml` manages the existing private gateway and exact-host DNS overrides. The role switch `wiki_editor_runtime_enabled` defaults to `true`. Both private wiki virtual hosts forward to `http://wiki-runtime-wiki.wiki.svc.cluster.local:8080`, the same runtime used by public ingress.

The switch removes the separate editor upstream and legacy wiki authorization-header injection. It removes the editor secret mount when no other virtual host needs it. The private gateway still restricts socket peers to the administrative subnet; that network restriction does not grant application permissions. Preserve unrelated virtual hosts, existing gateway values and the private TLS certificate. Review the complete rendered gateway release before applying it.

The new runtime is declared by `deploy/fleet/wiki-runtime.yaml` and `deploy/wiki-runtime`. Keep one writer on its new PVC. Public ingress and private routing must switch together after account login works; do not leave a private route pointing at the old writer. Bootstrap users in the new application, not through the old editor bootstrap playbook or shared gateway credentials.

## macOS

`ansible/playbooks/wiki-editor-client.yml` installs a root-owned launch daemon. Every ten seconds it checks that a private DNS server is reached over an `utun` interface and actually returns the private wiki address. Only then does it install `/etc/resolver/wiki.alchemmist.xyz`. When the private route or resolver disappears, it removes its own override and flushes the OS DNS cache, restoring public resolution. It refuses to overwrite an unmanaged existing resolver. Existing `socrat.alchemmist.xyz` resolution is unchanged.

Browser DNS caches, already-open connections, and browser-specific encrypted DNS may delay route changes. Reload after connecting or disconnecting WireGuard; browser encrypted DNS must respect the system resolver for this hostname. Expect up to ten seconds before the OS resolver changes. Disconnecting WG changes the route, not the user's application permissions: authenticated editing remains available through public ingress.

To remove the client integration, unload `system/xyz.alchemmist.wiki-resolver`, remove its launch daemon and executable, then remove the exact-host resolver only if `/var/db/socrat-wiki-resolver-owned` exists. Remove that ownership marker and flush the DNS cache.

## Other clients

Configure split DNS for the **exact hostname** `wiki.alchemmist.xyz` on the administrative WireGuard link, using `10.250.0.1` or `10.250.0.3` as DNS servers. Remove the routing domain when that link disconnects. On Linux with systemd-resolved, a per-link `~wiki.alchemmist.xyz` route-only domain is suitable. Do not redirect the entire `alchemmist.xyz` zone or leave a permanent hosts-file entry. Clients without split DNS use the public ingress and the same account permissions.

## Acceptance checks after cutover

- Public HTTPS serves anonymous reading and `/login`; an authenticated editor can publish without WG.
- Anonymous or reader requests cannot mutate content, including requests carrying spoofed `X-Socrat-WG-Peer`, `X-Socrat-Editor-Key` or forwarding headers.
- Private HTTPS reaches the same runtime and enforces the same account permissions.
- Requests outside the administrative subnet cannot use the private virtual host.
- Backend CSRF protection applies on both routes; WG reachability does not replace it.
- WG disconnect removes the managed resolver and restores public resolution; reconnect restores the private route.
- Existing private virtual hosts and Syncthing remain functional.

`tests/test_wiki_editor_resolver.py` exercises private routing, disconnect/public fallback and unmanaged-file preservation without changing live networking. For rollback, follow the migration runbook: switching the gateway flag back is safe only after considering content accepted by the new runtime.
