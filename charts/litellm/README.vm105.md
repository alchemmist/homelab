# Pinned LiteLLM chart extension, not a release upgrade

Exact existing production upstream litellm-helm1.105.1 from oci://ghcr.io/berriai.
OCI digest sha256:3931b5b25997d37aa05ff1635b396f07986fa3848fbe3aca5d78cdf4e33521b0.
Downloaded tar SHA256: b67305de7506e75cde0f233cec256c8361bd9a7769bb365b03cdfcb78bcd48ad

All upstream files/dependencies/licenses retained, only TWO stock template patches:
- optional hostAliases on application Deployment (narrow TLS/SNI-preserving IdP route);
- optional placementOnlyImage guard requires migration review on future image changes.

Before setting either option, rendered output is BYTE IDENTICAL to the OCI chart.
Application runtime image remains1.105.1, all keys/config/SDK preserved.
The previous migration Job succeeded and was already deleted. Production placement
sets migrationJob.enabled=false, pinned to this exact image with a fail-closed
version guard. No migration Job is recreated; future image updates must explicitly
review and re-enable normal migration handling.
The upstream chart does not support hostAliases; an unused values key is not a fix.
No global DNS rewrite, TLS bypass, credential/client change, init /etc/hosts hack,
custom proxy, admission webhook, Argo plugin or duplicate-Deployment override.
Future chart upgrades: refresh exact upstream source, reapply these two patches,
prove baseline render, no placement-time migration Job and future upgrade guard.
