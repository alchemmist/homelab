# blog + socrat-home: replace socrat-2 with VM105

Owner approved moving these two applications only on15Nov2026.

## Current placement

| Application | Before | Accepted after |
|---|---|---|
| blog | socrat-0 + socrat-2 | socrat-0 + socrat-5 |
| socrat-home | socrat-1 + socrat-2 | socrat-1 + socrat-5 |

Two replicas each retained; required hostname anti-affinity prevents co-location.
Hard nodeAffinity eligibility is owned by deploy/blog/values.yaml and
 deploy/socrat-home/values.yaml, not live overrides. Chart nodeAffinity defaults
empty; optional anti-affinity can be disabled explicitly. Both use maxSurge0 /
maxUnavailable1: a two-domain required anti-affinity otherwise deadlocks surge.
Initial blog rollout hit that deadlock while old0/new5 remained Ready. Corrected
in owning Git strategy, not by forced Pod deletion, scaling or node drain.

Source commits019276cd and9a931d46; Argo automatic reconciliation, targeted refresh
only. Image digests, Secrets, TLS/Ingress/Service identities and application
content unchanged. No PVC/hostPath data and no database transfer for these apps.
No other workloads moved; no host services, VPN, etcd or n8n changes.

## Acceptance

- Both Deployments rolled out; Argo Synced/Healthy.
- blog749f7f57cd: nglmd on5, zzt52 on0.
- socrat-home85f66f8cdb: k9npz on5, nqrkp on1.
- Four Pods Ready, restart0; no blog/home Pods remain on2.
- Service EndpointSlices include exactly the expected two Ready node endpoints.
- Each individual Pod serves HTML through Kubernetes read-only HTTP proxy.
  Proxy-rewritten link URLs differ per Pod, so those response hashes need not match.
- Bounded external curl HTTPS GETs: alchemmist.xyz, www.alchemmist.xyz and
  socrat.alchemmist.xyz all200, three repeat rounds; home favicon/wallpaper/font200.
  TLS verification enabled. Initial combined Python urllib check timed out and was
  replaced with explicitly bounded curl checks; not counted as a passing probe.
- Four rendered-placement unit tests passed, six existing onboarding test functions
  directly invoked/passed (pytest not installed in Ansible interpreter), both Helm
  lint checks passed. No browser/visual or full VM cold-boot acceptance claimed.
- Guest before: root74GiB available/data~2TiB available; only static container
  images/config involved, no large data copy. VM105 physical backing is not reserved
  by virtual disk capacity; this operation is not a new physical-capacity proof.

Private preimages and public acceptance receipt:
~/Library/Application Support/homelab/static-apps-vm105-20261115 (0700/0600).

## Rollback / future movement

Change eligible hostname pair in owning deploy values; keep two replicas,
required separation and non-surge strategy, commit/push and verify reconciliation
and HTTP routes. Do not merely delete Pods: scheduler would recreate same placement.
A node5 outage leaves blog on0/home on1, unlike existing single-node Rancher/n8n.
Public edge routing remains on VPS; moving replicas does not move public ingress.
