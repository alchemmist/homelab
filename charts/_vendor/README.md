# Pinned upstream Helm source, not an Application

`kube-prometheus-stack-92.10.0.tgz` is the unmodified upstream package retrieved
with `helm pull kube-prometheus-stack --repo https://prometheus-community.github.io/helm-charts --version 92.10.0`.
SHA256: `85240efc443d7c2525d72851ab9c7c550c7abdb892b70f768ab8e727d9c3c898`.

Five independent component charts link this immutable bundle under `charts/`.
Each enables only its own runtime/rule groups; their rendered sets are disjoint.
This is template/code reuse, not a combined Application or shared mutable values.
Every component owns its own values and can pin a separately reviewed bundle/version;
never replace a versioned archive in place. No Helm dependency download is required
by Argo rendering. Historical release names are deliberate compatibility identities.
