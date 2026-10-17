# Private wiki editor network

The public hostname remains `wiki.alchemmist.xyz`. Public Traefik serves only the static wiki. Administrative WireGuard clients resolve the same hostname to `10.250.0.1` or `10.250.0.3`. The existing WireGuard-only nginx gateway serves the static site and forwards `/api/editor/` to `wiki-editor.wiki.svc.cluster.local:8080`.

The private virtual host checks the socket peer against `10.250.0.0/24`, not user-supplied forwarding headers. It replaces `X-Socrat-WG-Peer` and `X-Forwarded-For` with that socket address. Every administrative WireGuard peer can edit; this is not individual user authentication. The editor must reject direct requests without the trusted gateway path. Its service must remain internal with network policy appropriate to host-network gateway source IPs.

Deploy server access with `ansible/playbooks/wiki-editor-access.yml`. It preserves existing gateway values, adds the certificate in the gateway namespace and installs an exact-host DNS override on administrative resolvers. It does not publish an editor Ingress or NodePort.

## macOS

`ansible/playbooks/wiki-editor-client.yml` installs a root-owned launch daemon. Every ten seconds it checks that a private DNS server is reached over an `utun` interface and actually returns the private wiki address. Only then does it install `/etc/resolver/wiki.alchemmist.xyz`. When the private route or resolver disappears, it removes its own override and flushes the OS DNS cache, restoring public resolution. It refuses to overwrite an unmanaged existing resolver. Existing `socrat.alchemmist.xyz` resolution is unchanged.

Browser DNS caches, already-open connections, and browser-specific encrypted DNS may delay route changes. Reload the page after connecting or disconnecting WireGuard; browser encrypted DNS must respect the system resolver for this hostname. Expect up to ten seconds before the OS resolver changes. An inaccessible gateway causes the capability probe to fail closed; no editing is granted by frontend visibility alone.

To remove the client integration, unload `system/xyz.alchemmist.wiki-resolver`, remove its launch daemon and executable, then remove the exact-host resolver only if `/var/db/socrat-wiki-resolver-owned` exists. Remove that ownership marker and flush the DNS cache.

## Other clients

Configure split DNS for the **exact hostname** `wiki.alchemmist.xyz` on the administrative WireGuard link, using `10.250.0.1` or `10.250.0.3` as DNS servers. Remove the routing domain when that link disconnects. On Linux with systemd-resolved, a per-link `~wiki.alchemmist.xyz` route-only domain is suitable. Do not redirect the entire `alchemmist.xyz` zone and do not leave a permanent hosts-file entry: both change unrelated/public behavior. Clients without private split DNS keep the public read-only site even while connected to WireGuard.

## Acceptance checks

- Public IP with the wiki Host header: static content works, editor endpoints are unavailable, including with spoofed `X-Forwarded-For` and `X-Socrat-WG-Peer`.
- Private gateway via an administrative WireGuard peer: static content and editor capability work under the same HTTPS origin.
- Requests outside the administrative subnet cannot use the private virtual host.
- Save requests are protected against cross-site requests by the editor backend; WG network reachability is not a CSRF defense.
- WG disconnect removes the managed resolver and restores public read-only resolution; reconnect restores editor discovery.
- Existing private virtual hosts and Syncthing access remain functional after gateway rollout.

## Bootstrap and publication

First run `ansible/playbooks/wiki-editor.yml` to create stable secrets and the separate Fleet GitRepo. Register its printed public key as a write-enabled deploy key for homelab. Private keys and gateway tokens stay in Kubernetes Secrets. Then run the access playbook and the macOS client playbook. The backend has its own image, workflow and `wiki-editor-publish` branch, so ordinary Markdown edits rebuild the public site without restarting the editor.

On this cluster host-network gateway traffic may use Flannel source addresses `10.42.2.0` and `10.42.1.0`; ingress policy permits only the gateway nodes and their narrow host addresses. The additional shared gateway secret is checked by the backend before accepting peer identity. Lifecycle tests in `tests/test_wiki_editor_resolver.py` exercise private routing, disconnect/public fallback and unmanaged-file preservation without changing live networking.
