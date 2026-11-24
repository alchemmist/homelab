# cert-manager RBAC contracts

The cert-manager release (`charts/cert-manager`, upstream v1.21.3, namespace
cert-manager) is a certificate manager whose controllers fundamentally read and
write Kubernetes Secrets (TLS cert data). These RBAC grants are the documented
upstream cert-manager access model, scoped to exactly the verbs needed:

- `cert-manager-cainjector` (ClusterRoleBinding): cainjector reads Secrets
  (CA bundles) and injects them into webhook configurations / CRDs; that is its
  entire function.
- `cert-manager-controller-issuers` / `cert-manager-controller-clusterissuers`:
  read issuer credentials stored in Secrets (ACME private keys, external DNS
  provider tokens).
- `cert-manager-controller-certificates`: read/write the issued certificate
  Secrets.
- `cert-manager-controller-orders`: read ACME order secrets during issuance.
- `cert-manager-controller-challenges` (access-to-create-pods +
  access-to-secrets): ACME HTTP01/TLS01 challenges create solver Pods and read
  the issuer secrets needed to complete them.
- `cert-manager-webhook:dynamic-serving` (RoleBinding): the webhook reads its
  own serving certificate Secret to serve TLS to the API server.

Each grant is the least privilege the cert-manager controller role requires
(its job is managing cert material in Secrets and solver Pods). This is not
over-privilege; removing `secrets` access would break certificate issuance.

## What was fixed in this pass

- cainjector: enabled `--health-probe-bind-address` (controller-runtime health
  endpoint) + liveness `/healthz` and readiness `/readyz` probes on :8081.
- controller: enabled livenessProbe `/livez` and added readinessProbe `/readyz`
  on the http-healthz port.
- startupapicheck Job: ttlSecondsAfterFinished 3600.
- Per-workload NetworkPolicies for controller/cainjector/webhook/
  startupapicheck (API + DNS egress; ACME 443 for the controller; webhook
  ingress :9443 from the API server).

Evidence: docs/quality/cert-manager-contracts.md.
