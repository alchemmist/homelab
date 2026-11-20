# CoreDNS: server manifest writers are not the DNS pod sites

After the VM105 promotion, `deploy@socrat-5` updated the Deployment at 13:30:44
UTC; the owner annotation identified packaged `coredns`. One Ready endpoint
remained, on socrat-1. The packaged digest on 0, 1 and 5 was identical, but only
0/1 had `coredns.yaml.skip` and the accepted `homelab-coredns-ha.yaml`. The
etcd-only node 2 has no server manifests directory. Do not restart K3s or replay
the broad HA role to fix this drift. No disk, VM or database migration is needed.

Scope: keep the two **existing intended DNS replicas** on 0/3; prevent the new
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
