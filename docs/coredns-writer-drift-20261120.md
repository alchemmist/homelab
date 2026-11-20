# CoreDNS: server manifest writers are not the DNS pod sites

After the VM105 promotion, `deploy@socrat-5` updated the Deployment at 13:30:44
UTC; the owner annotation identified packaged `coredns`. One Ready endpoint
remained, on socrat-1. The packaged digest on 0, 1 and 5 was identical, but only
0/1 had `coredns.yaml.skip` and the accepted `homelab-coredns-ha.yaml`. The
etcd-only node 2 has no server manifests directory. Do not restart K3s or replay
the broad HA role to fix this drift. No disk, VM or database migration is needed.

Scope: restore the two **intended DNS replicas** on 0/3; prevent the new
server 5 from reapplying the packaged singleton. Do not modify `coredns.yaml`,
Corefile, Service, ClusterIP, RBAC or unrelated AddOns. `.skip` suppresses future
packaged reconciliation, not the currently running Deployment.

For this repair, verify byte-identical known-good overlay on both old writers
(SHA256 `c33f31c18bfcb726f7b71dbf47757acaa0a224dd9ccc8929f488cf99922615b9`).
Save the live Deployment as a private preimage. Refuse if it differs from the
accepted spec outside replicas, rolling budget and node affinity. Stage the skip
on 5 only after checking the packaged hash and absence of competing overlay.
Patch live with tests of UID and full old spec, zero unavailable and surge one;
verify Ready endpoints and real DNS queries before atomically installing the
byte-identical overlay on 5. Recheck all writers when adding another API server.
If rollout fails, inspect events and use an inverse UID/spec-guarded patch only
against the exact attempted spec. Do not delete the Deployment or its Service.

## Endpoint gates and writer identities

- Before: exactly one Ready endpoint on 1; none on 0 or 3. Only writers 0/1
  had the matching skip/HA overlay; writer 5 had only the packaged file.
- Transition: skip staged on 5, writers 0/1 unchanged. During the guarded
  rollout the old pod on 1 may briefly coexist with new endpoints.
- After: require exactly two non-terminating Ready endpoints on 0 and 3;
  no endpoint on 1 or 5. The intended **writers** are 0, 1 and 5, not 0/3.
  Verify the staged skip and final overlay digest independently on each writer.

On 20 November both new endpoints and kube-dns VIP answered A queries via UDP
and TCP from both 0 and 3. At 15:35 UTC node 5 was Ready=Unknown and unreachable
via SSH/API; writer-5 final overlay and n8n pod-side checks were not confirmed.
Do not count those as DNS failures or restart the node. Retry when available.

Completion after node 5 returned (16:00 UTC): the post-rollout endpoint gate
applies **only once `kubectl rollout status deployment/coredns` completes**;
not during the overlap described above. All six nodes were Ready, both 0/1 API
readyz endpoints passed, and 0/1/2 were healthy etcd voters. On 5, the skip
and staged receipt survived; the final HA overlay was absent. The live DNS spec
still matched the known-good candidate. The same overlay was installed without
replacing any existing file and its digest was verified on 5. From the existing
n8n container, three A lookups per DNS destination (endpoint on 0, endpoint on 3,
and the Service VIP) all returned the expected Kubernetes API Service address.
No workflow invocation, database operation, disk migration or restart was used.
