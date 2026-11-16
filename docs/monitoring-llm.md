# LLM monitoring

The **LLM** dashboard (`socrat-llm`) is a primary dashboard with detailed views for
LiteLLM, the model switcher, vLLM, NVIDIA GPU telemetry and container resources.
Use the existing authenticated Grafana entry at
`https://grafana.socrat.alchemmist.xyz/`; native SSO/admission still applies.
This is not an anonymously published dashboard.

## Current ownership and maintenance

Scrape resources belong to Argo Application `monitoring-llm` and
`charts/monitoring-llm`; dashboard/rules have their existing Git owners.
`ansible/playbooks/monitoring-llm.yml` is retired and refuses before host roles,
Helm or credential work. Do not replay this combined installer or target the full
Socrat group for GPU maintenance. Existing timers and scrape resources are not
removed by this source-only retirement. GPU host changes need a separately reviewed,
explicitly scoped maintenance procedure; socrat-2 VPN workloads remain excluded.

GPU collection uses a systemd timer on socrat-0 and the existing `nvidia-smi`.
It creates no CUDA workload, GPU resource reservation or public endpoint.
The timer writes atomically every 15 seconds; failed collection replaces old
GPU values with a failure flag. Dashboard GPU readings require success and a
sample less than 60 seconds old. The collection health and age remain visible
when stale. Unsupported readings, including VRAM temperature on this RTX 3090,
are not fabricated.

`monitoring_llm_gateway` now stages a **read-only verifier**, not a reconciler.
It requires the existing Git-owned LiteLLM Application and destination, checks the
actual Deployment chart label, and derives the master-key Secret reference from
the Deployment rather than stale Helm-release values. It checks the existing key
has exactly `/metrics` allowed, anonymous metrics and model access stay denied,
and authenticated scraping works. HTTP authorization redirects are not followed.

All Kubernetes commands are bounded single-resource GETs. HTTP calls are GET-only;
no inference, vLLM idle polling, Helm invocation, rollout, key generation or Secret
apply is present. Missing Application/Secret, malformed reads, transport errors or
changed ownership fail closed without installation/repair. The existing restricted
key remains in `llm/litellm-monitoring`; credentials and API error URLs are not
printed. First-time provisioning/rotation is a separate explicitly authorized
operation, not a fallback from verification. The obsolete `--idle-timeout` argument
is accepted only for CLI compatibility and no longer triggers an idle wait.

The `monitoring-llm` chart installs three PodMonitors in `llm` and narrowly scoped
network policies. Only matching Prometheus pods can scrape vLLM and the queue
collector. LiteLLM metrics use the restricted bearer key. The status collector
reads the authenticated switcher `/status` endpoint using the existing vLLM key;
it never submits inference or changes the loaded model. Its ingress is restricted
to Prometheus. Model switching and application access policies remain in place.

## Verify

From the repository root, run `python3 scripts/check-llm-monitoring.py` and
`python3 scripts/check-monitoring.py`. The first validates all LLM scrape targets,
GPU freshness, queue metrics and every dashboard query without generating load.
Latency panels may have no recent observations when inference is idle.

## Meaning of the metrics

- **Switcher queue**: requests waiting for the one-GPU scheduler; its running
  indicator also includes model loading. The model label is the last confirmed
  loaded model from the switcher, not a separate hardware probe.
- **vLLM queue**: requests waiting inside the inference engine. It is distinct
  from requests still queued at the switcher.
- **LiteLLM pre-call latency**: time before invoking the model, including
  authentication/ASGI handling. It is not instantaneous queue length.
- **GPU memory-controller activity** and **allocated VRAM** are distinct metrics.
- vLLM `request_success_total` has finish reasons including `error` and `abort`;
  the dashboard preserves these distinctions.
- All latency percentiles, prefix cache hit ratio and LiteLLM error ratio are
  summary values over the selected dashboard time range. They show
  `No observations` when undefined, rather than fragmented time-series graphs.
  Load, queues, throughput and GPU metrics retain their time-series views.
  Counters start with collection; prior requests are not backfilled.
- Missing error counter series are treated as zero only when matching total
  request series exist. Missing telemetry does not become a healthy zero.

The vLLM model selector affects the vLLM section; LiteLLM is grouped independently
by its requested model. GPU graphs apply to the shared physical GPU.
