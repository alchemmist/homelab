# Rancher node list after a datastore migration

On 2026-10-16, Kubernetes and Rancher's management API both contained four
healthy nodes, but the Explorer showed only three. This was a server-side
cache problem, not a browser cache or node registration problem.

Both Rancher v2.15.2 replicas returned only socrat-0, socrat-1 and socrat-2
from `/v1/nodes` and `/k8s/clusters/local/v1/nodes`. The individual
`/v1/nodes/socrat-3` request worked, and `/k8s/clusters/local/api/v1/nodes`
and `/v3/nodes?clusterId=local` returned all four nodes.

The stale list carried revision `1098885`, above the current Kubernetes
revisions around `968xxx`. Rancher logs recorded a resource version changing
from `1092823` to `246` during the earlier SQLite-to-etcd conversion. This
points to cached resource versions surviving a datastore revision rollback.
The UI SQL cache was enabled; its database lived in each Rancher container's
writable layer, without a persistent volume.

## Recovery

From `ansible/` run:

```bash
ansible-playbook playbooks/rancher-refresh-cache.yml
```

The play requires two healthy Rancher replicas, replaces them one at a time,
and waits for the deployment between replacements. Recreating the containers
also discards their disposable SQL caches. It does not restart Kubernetes
nodes, change their roles, disable the SQL cache feature, or restart apps.

The verifier compares the authenticated Steve node list with Kubernetes on
both replicas and through the configured ingress. It discovers an existing
unexpired admin token through Kubernetes and uses it only in process memory;
it never prints or saves the credential. This requires the operator's
existing administrative Kubernetes access and an available Rancher admin
token. Token hashing must be disabled for this stored-token verification.

After recovery, both replicas and ingress returned all four nodes. A temporary
annotation on socrat-3 propagated through all three list endpoints; its removal
also propagated, confirming that subsequent watch updates worked. The test
annotation was removed. All Kubernetes nodes remained Ready.

After a datastore conversion or restore, verify the UI's actual Steve list,
not only `kubectl get nodes` or `nodes.management.cattle.io`.

References: [Steve API and SQL-cache behavior](https://github.com/rancher/steve),
[Steve v0.9.23 SQL store](https://github.com/rancher/steve/blob/v0.9.23/pkg/sqlcache/store/store.go).
