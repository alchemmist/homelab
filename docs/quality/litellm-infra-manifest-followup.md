# LiteLLM infrastructure manifest follow-up

Scope: the `litellm-infra` owner row in PR #494. No gate, rule, policy
suppression, or cross-owner workload declaration was changed.

## Changes and offline evidence

The branding Nginx container now has a liveness probe on its existing `/health`
endpoint; the endpoint is already the readiness signal and returns from the
Nginx server. The existing asset-presence init container only reads its mounted
assets, so its root filesystem is now read-only. The rendered-chart regression
checks assert both properties.

A second test renders the actual vLLM, LiteLLM, monitoring-llm, and
litellm-infra charts into their Argo destination namespace and composes their
objects. It verifies that the `vllm-gateway-only` target selects the separately
owned vLLM Pod, its peer selector matches the rendered LiteLLM Pod, and the
allowed port is TCP/8000. It also verifies that the monitoring policy targets
that vLLM Pod and retains the configured Prometheus namespace/pod selector.
This establishes selector relationships from current source renders only; it
is not a CNI/API-server policy simulation, runtime reachability test, or
justification to widen either policy.

## Residual owner decisions (not fixed or waived)

1. **Cross-release NetworkPolicy finding(s):** the standalone manifests target
   inventory omits some separately owned releases, so the composed render
   proves the selectors have real current matches. The manifests gate still
   reports its findings; no checker suppression was added. Before changing
   policy or claiming its effective behavior, obtain an offline test of
   additive NetworkPolicy semantics for the actual CNI and validate both
   allowed gateway/Prometheus flows and denied unrelated sources. No production
   traffic test is authorized here.
2. **Branding isolation / peer matrix:** the branding Service is consumed by
   the separately owned LiteLLM release and exposed through the existing
   branding ingress. A NetworkPolicy needs an exact ingress-controller source
   identity and any required probe clients, plus an egress decision. Those
   identities and CNI enforcement have not been verified in this offline
   change. Do not add guessed peers or a default-deny policy. Approval/evidence
   required: a composed render tying the current ingress route and LiteLLM
   client to their real Pod selectors/namespaces, plus positive and negative
   policy tests for both paths.
3. **Branding init-container CPU/memory requests:** do not copy the Nginx
   container's 10m/16Mi request to a shell/test init container without
   measurement. Required decision/evidence: observed or benchmarked startup
   CPU and memory floors for the actual image/asset check, then an owner-approved
   request that preserves startup under node pressure. No limit/request was
   fabricated.

These residuals preserve the current working service contract and are not
claims that the remaining findings have been resolved.
