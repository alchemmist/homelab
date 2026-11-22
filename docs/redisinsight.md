# Redis Insight: signing in with Authentik

`https://redis.socrat.alchemmist.xyz` provides one dashboard for logical Redis services. The [GitOps configuration](../deploy/platform/redisinsight/resources/ui.yaml) runs one pod in namespace `redis` on `socrat-5` and stores settings on the retained `redisinsight-data` PVC. Redis Insight listens only on loopback. The sole Service exposes oauth2-proxy; Authentik protects the UI, API and WebSocket. The gateway uses PKCE, an exact `/oauth2/callback` and membership in either `homelab-owner` or `redisinsight-readers`. Do not replace OIDC with a check on a client-supplied header.

`redis-common` is configured through Redis Insight's standard preconfiguration variables. On first sign-in the owner is prompted to accept the license agreement; the UI does not import preconfigured connections until then. Nobody accepted the terms on the owner's behalf. The `insight-browser` Redis user can read `litellm:*` values and the probe key, but cannot write or administer the server. `SCAN` exposes key names across the instance: this dashboard is for trusted readers, not isolated tenants. Adding another Redis requires a separate ACL and network access to its endpoint. Protect the PVC and `redisinsight-runtime` (the settings encryption key). Never copy Redis control credentials into the UI.

## Granting and revoking access

In Authentik, go to **Directory → Groups → `redisinsight-readers` → Users** and add or remove the user's personal account. Do not grant `homelab-owner` for this purpose. After being added, the user must sign in again. Removal prevents new sign-ins unless the user is an owner; an existing gateway cookie can remain valid for up to 30 minutes. Group membership does not grant a Redis password or access to port 6379. Members see the same saved connections and do not have isolated UI settings. Do not save privileged accounts in this dashboard.

### Access checks and acceptance limits

- The `redisinsight` Authentik application has two group bindings; either one permits access. The [group script](../scripts/redisinsight-reader-group.py) creates an empty, unprivileged group and its binding but does not assign users. For routine grants, change membership only; no reprovisioning or pod restart is needed.
- The [oauth2-proxy gateway](../deploy/platform/redisinsight/resources/deployment.yaml) independently checks the same two groups in the OIDC `groups` claim. The [Redis ACL](../deploy/platform/redisinsight/onboard.py), not Authentik, controls commands and key prefixes.
- After the 22 November rollout, both live bindings and both `--allowed-group` pod arguments were verified. Without a session, `/` returned `302` to Authentik; `/api/databases` and `/socket.io/` returned `401`. Interactive sign-in as a new reader was **not** tested: no real users were added when the group was created. After granting access, ask the recipient to sign in again and open `redis-common`.

[End-user guide in the wiki](../wiki/content/platform/redis.md).

## Initial DNS publication

As with pgAdmin, the public A record points **only to HOME**. Do not expand the VPS ingress watch scope to the database namespace. Use the standard playbook: it checks the changes on all four zone writers, compares the shared plan hash, then updates one writer at a time. The configured operator Mac uses existing SSH aliases with pinned keys. Start in the repository root in an interactive terminal. Enter the sudo password **only at the local Ansible prompt**:

```sh
cd ansible
inv='socrat-0,socrat-1,socrat-2,socrat-4,'
ansible-playbook -i "$inv" playbooks/redisinsight-public-dns.yml --ask-become-pass
# Verify all four plan_hash values and the single redis.socrat change, then:
read -r hash  # paste the verified plan_hash and press Enter
ansible-playbook -i "$inv" playbooks/redisinsight-public-dns.yml --ask-become-pass \
  -e redisinsight_public_dns_apply=true -e "redisinsight_public_dns_hash=$hash"
```

Check authoritative DNS answers and run `kubectl -n redis wait --for=condition=Ready certificate/redisinsight-tls --timeout=5m`. Open the UI without `--resolve` and with TLS verification enabled. Check the Authentik redirect and denial of anonymous requests to `/api/databases`. The owner verifies interactive sign-in and visibility of the connection. Do not reset MFA or certificates to perform a check.

**22 November snapshot:** pod 2/2, PVC Bound, OIDC discovery and owner binding verified. Through the gateway, anonymous `/` returned 302 to Authentik; the API and `/socket.io/` returned 401. Tests from the UI container verified TLS hostname validation and Redis AUTH/PING; ACL DRYRUN denied SET. The public A record was applied on nodes 0/1/2/4; all three authoritative nameservers returned HOME only. The Let's Encrypt certificate was Ready. After the Service port was renamed `http` (TLS terminates at Traefik), standard HTTPS without DNS overrides returned 302 to Authentik, and anonymous API and Socket.IO requests returned 401. The TLS-verified redirect was independently confirmed from the Moscow node. Interactive owner sign-in, MFA and EULA acceptance were not performed.
