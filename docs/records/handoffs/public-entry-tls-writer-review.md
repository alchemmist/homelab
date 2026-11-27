# Direct RBAC grants are distinct from a TLS source pin

Before asking a closed controller to fetch a real key, review who can replace
or remove it. One Ready Certificate writer in the Ingress/Certificate inventory
does **not** mean only that controller can mutate the Secret. For example:

```sh
set -o pipefail
kubectl get roles,rolebindings,clusterroles,clusterrolebindings -A -o json |
  python -m ci.quality.public_tls_writer_grants schoolbot schoolbot-tls
```

Use authorized, complete RBAC list observations; never include Secrets in
this command. The report contains RBAC subject names: review locally, don't
publish the subject list. On the live Schoolbot source the four-kind read
found **29 bindings** with at least one direct Secret mutation verb. This is
not 29 confirmed human writers or evidence of tampering. Creation and bulk
deletion are distinguished from mutation of an existing named object. A
ClusterRole may confer only namespace-scoped rights through a RoleBinding.

This is a positive grant inventory, not an effective-access simulator. Missing
bindings, stale aggregation, external group membership, service-account token
use, admission controls and non-RBAC authorizers change the interpretation.
It does not enumerate indirect access through workload creation, RBAC changes,
issuer or Certificate changes, or compromise of a node/controller. Even a
complete empty result never approves a source. No production reader, RBAC
change, key fetch or new controller is part of the check.

**Open decision:** have the relevant owners classify the direct grants and
indirect writers, documenting their trust or a separately reviewed containment
change. Do not remove a controller's rights based on this count; doing so can
break renewal or unrelated workloads. Pending that decision the real-key
Schoolbot acceptance remains outstanding.
