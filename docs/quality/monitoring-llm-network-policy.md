# monitoring-llm NetworkPolicy target review

The PR #494 manifest audit reports two dangling policy targets in
`charts/monitoring-llm/templates/network.yaml`.

* `vllm-monitoring` is verified by an offline composed Helm render: the policy's
  exact `app: vllm` selector matches the Pod template rendered by the separately
  owned `charts/vllm` release in namespace `llm`. Its only ingress is TCP/8000
  from the selected Prometheus Pods in `cattle-monitoring-system`. The scoped
  regression test renders both real charts and checks the selector against the
  workload labels and retains the ingress restriction.
* `monitoring-llm-status` has no workload declaration in this repository. A
  repository-wide search finds only its NetworkPolicy; its values configure a
  status image but do not instantiate a Pod. The policy is intentionally left
  unchanged: removing it weakens isolation, while broadening its selector would
  grant ingress to unverified Pods. The test checks that the existing selector,
  source and port remain narrow; it does not claim that the target exists.

**Residual owner decision:** identify the authoritative owner/source for the
status-exporter Pod, then provide its rendered Deployment/Pod labels and namespace
(or confirm that the exporter is retired). Once that evidence exists, either
align the policy's exact selector to that real workload and test it in a composed
render, or have the owner approve retirement of the policy if the exporter is
retired. No selector change, policy deletion, rollout, or live-cluster inspection
is authorized by this source-only change.
