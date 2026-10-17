# LLM monitoring

The **LLM** dashboard (`socrat-llm`) is a primary dashboard with detailed views for
LiteLLM, the model switcher, vLLM, NVIDIA GPU telemetry and container resources.
It is available only through the existing private Grafana gateway.

## Apply

Use both inventories so the node-exporter textfile directory is prepared on all
four nodes. From `ansible/`:

```sh
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/monitoring-llm.yml --ask-become-pass
ansible-playbook playbooks/monitoring.yml --tags monitoring_base,monitoring_k3s
```

GPU collection uses a systemd timer on socrat-0 and the existing `nvidia-smi`.
It creates no CUDA workload, GPU resource reservation or public endpoint.
The timer writes atomically every 15 seconds; failed collection replaces old
GPU values with a failure flag. Dashboard GPU readings require success and a
sample less than 60 seconds old. The collection health and age remain visible
when stale. Unsupported readings, including VRAM temperature on this RTX 3090,
are not fabricated.

`monitoring_llm_gateway` preserves installed LiteLLM values and models, enables
the Prometheus callback on pinned chart 1.105.1, and keeps metrics authenticated.
It waits for idle vLLM samples before a rolling LiteLLM update, with zero
unavailable replicas and a 7260-second termination grace for existing requests.
It does not restart vLLM or the model switcher. A dedicated virtual key permits
only `/metrics`; the role checks that `/v1/models` remains denied. The key is
stored in Secret `llm/litellm-monitoring` and is never committed.

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
