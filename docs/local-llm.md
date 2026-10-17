## Current model selection (2026-10-16)

Qwen3.8-27B INT4 is the only installed model. LiteLLM routes through the internal serialized gateway to one vLLM engine, with vision, 112K context and a 95% GPU-memory target. See [model serving](model-switching.md). Earlier configuration snapshots below are retained as history.

## Public gateway migration (2026-10-15)

Current target URLs: Open WebUI `https://chat.alchemmist.xyz`, LiteLLM `https://llm.alchemmist.xyz`. Public DNS and trusted TLS were verified on 2026-10-15. Earlier private URLs below describe the initial deployment.

Open WebUI authentication is enabled, signups disabled, secure cookies enabled, direct connections disabled. The original user ID and chat history are preserved; its login is now `anton.ingrish@gmail.com`, with the user-selected password; change it under Settings > Account. It is stored hashed in the application database, not in environment variables. The JWT signing secret was rotated to invalidate pre-authentication sessions.

Open WebUI uses only `http://litellm.llm.svc.cluster.local:4000/v1` with the dedicated `open-webui` virtual key. NetworkPolicy `vllm-gateway-only` blocks direct access from other pods. There is no vLLM public ingress. See [LiteLLM](litellm.md) for deployment and account management.

# Local inference on socrat-0

## Current state: Qwen3.8-27B with vision and 112K context

On 2026-10-15 the user authorized restarting inference with monitoring and continuing the vLLM/API setup if the reboot did not recur. The Ansible playbook completed successfully, Helm reports a deployed release, and vLLM is running with one replica. Open WebUI was subsequently deployed as described below; LiteLLM remains deferred.

The current model is RedHatAI/Qwen3.8-27B-INT4, served as qwen3.8-27b, with a 114688-token context, FP8 KV cache and one active request. It accepts text and up to eight images per request, including history. Images are resized to at most 1048576 pixels. Open WebUI uses max_tokens=16384, leaving up to 98304 tokens for input when the full output allowance is reserved. Text, image tokens, generated reasoning and the final answer share the context budget. See [vision configuration](llm-vision.md).

The initial successful retry disabled Kubernetes service-link environment injection, used the standard CUDA 13 vLLM image, and retained the Qwen3-8B BF16 model, 8K context, 85% GPU-memory target and two-sequence limit. The subsequent 95% configuration is described below. NVIDIA device plugin is v0.20.1. The host kernel and NVIDIA driver were not changed.

Historical Qwen3-8B validation passed before and after one deliberate pod recreation:

- Unauthenticated /v1/models is rejected with HTTP 401; the stored bearer key works.
- Model listing, a coding response, SSE streaming, automatic tool selection and tool-result continuation passed.
- Twelve requests at concurrency two generated 6144 output tokens in 84.13 seconds, approximately 73 output tokens/s combined for this workload. Each request had approximately 1534 input tokens and deliberately stopped at its 512-token output cap; this is a throughput probe, not a code-quality benchmark.
- A 6524-token input completed successfully after pod recreation.
- /v1/responses returned status completed.
- The controlled startup, load and restart observation covered 477.6 seconds (235 telemetry samples), with one unchanged host boot ID, no automatic container restarts, and no new NVRM/Xid/Oops/panic entries in the captured kernel stream. Sampled peaks were 21369 MiB total GPU memory, 100% GPU utilization, 72 C and 344.95 W. Available host RAM remained at least 22.82 GiB.
- The same smoke suite also passed from the Mac through an SSH tunnel and Kubernetes port-forward; the temporary test tunnel was closed afterward.

Evidence is under /Users/antonmoss/.antex/artifacts/socrat-0-20261015/retry/: kernel-live.log, telemetry.jsonl, load-test.log, api-after-restart.log, vllm-first-start.log, vllm-after-restart.log and summary.json. Telemetry was streamed off-host, and a temporary boot-ID guard was prepared to stop inference if another reboot occurred. Temporary collectors are stopped after validation.

This successful retry does not identify or prove a repair of the earlier kernel defect. The plugin, application configuration and host memory state changed between attempts, so the result is not a controlled comparison isolating one cause. Continue normal API use, but preserve any subsequent pstore records and stop inference for investigation if another kernel error or reset occurs.

## Private Open WebUI and increased memory

The chat is available at https://llm.socrat.alchemmist.xyz through the Socrat WireGuard network only. Open WebUI v0.12.2-slim is pinned by digest and runs as a separate CPU-only Deployment in the llm namespace. Its SQLite database, chat history and settings persist on a 5 GiB local-path PVC. WEBUI_AUTH=False deliberately uses a shared account without a login prompt for this test; anyone with permitted network access shares that account and its chats.

Private DNS on all three nodes maps llm.socrat.alchemmist.xyz to 10.250.0.1. The Mac has an exact split resolver at /etc/resolver/llm.socrat.alchemmist.xyz. The existing public wildcard under socrat.alchemmist.xyz lets cert-manager validate the hostname with HTTP-01. The Certificate open-webui-private-tls and its Secret are in the syncthing namespace, using ClusterIssuer letsencrypt-http01. The issued certificate expires on 2027-01-12. The application has no public Ingress; only temporary ACME validation routes are public during certificate issuance/renewal.

HTTPS uses the same existing WireGuard-only NGINX as the node Syncthing interfaces: WG port 443 is translated to 18443, and an SNI virtual host on socrat-0 proxies the chat to open-webui.llm.svc.cluster.local:8080. Its separate TLS Secret is watched for renewal. The original Syncthing BasicAuth and paths are retained. Syncthing identities and paused-folder state matched before and after the proxy rollout on all nodes.

Private HTTP port 80 is translated to 18080 and handled by a small NGINX redirect Deployment bound only to 10.250.0.1. It returns 308 to HTTPS. The administrative firewall permits that translation only for registered WireGuard clients, and the application route is restricted to the WireGuard subnet. Public HTTP/HTTPS requests with the same Host header returned 404 during verification. Existing Syncthing HTTPS still returned its expected 401 without credentials.

The user-requested vLLM resource changes are now applied: gpu-memory-utilization=0.95, RAM request 12 GiB and RAM limit 24 GiB. The current Qwen3.8-27B configuration uses a 131072-token context and one active sequence. The 95% value sizes vLLM against CUDA-reported GPU memory; it is not a hard isolation boundary from Hyprland. During the earlier Qwen3-8B two-request test, only about 355 MiB GPU memory remained free; that measurement is historical and does not describe the replacement model. Host RAM limits are ceilings, not preallocated memory.

The API smoke suite passed at 95%, followed by four requests at concurrency two. The model also answered a Russian prompt through the actual HTTPS browser chat. No new kernel/NVIDIA errors or host reboot occurred during this observation. Evidence is under /Users/antonmoss/.antex/artifacts/socrat-0-20261015/gpu95/.

Reapply from ansible/:

```sh
ansible-playbook playbooks/llm.yml
ansible-playbook playbooks/open-webui.yml --ask-become-pass
ansible-playbook playbooks/open-webui-https.yml --ask-become-pass
```

The HTTPS playbook waits for the Certificate, snapshots Syncthing state, updates its existing private proxy and enables the redirect. The extra virtual host is persisted in inventory/host_vars/socrat-0.yml so later app deployments preserve it. Recreating the Mac resolver uses playbooks/wireguard-admin-client.yml with --tags dns and local administrator privileges. Do not switch this no-auth installation to a public Ingress without revisiting authentication.

## Initial kernel panic

On 2026-10-15 at approximately 02:11 MSK, socrat-0 unexpectedly rebooted during bring-up. Archived EFI pstore confirms a kernel page fault and fatal panic in the context of VLLM::EngineCor. No reboot, shutdown, k3s restart, driver reset, or host CUDA modification was issued by this task. The workload exercised the failing execution path, but the underlying kernel, driver, or hardware defect remains unresolved. The user reported no previously noticed spontaneous restarts.

The node and cluster recovered. Inference was initially scaled to zero while evidence was collected. The interrupted pending-install Helm release was then uninstalled and reinstalled for the authorized retry. Its cache PVC and independently managed API Secret were preserved throughout.

Evidence from the previous boot:

- 02:08:36 MSK: NVIDIA kernel driver reported NV_ERR_NO_MEMORY during CUDA engine initialization.
- The model subsequently loaded successfully, using 15.27 GiB GPU memory; vLLM calculated 4.45 GiB for KV cache.
- 02:10:35 MSK: vLLM failed on Kubernetes-injected VLLM_PORT containing a tcp:// URI. This chart configuration error caused an application exit and automatic restart. Disabling service links fixed the startup failure and was validated during the retry; it does not by itself explain the kernel panic.
- 02:11:19 MSK: the previous journal ends abruptly. No orderly shutdown or Linux OOM-killer event was found in the inspected final interval.
- The archived pstore records contain Oops#1 and Panic#2 for the same fault at monotonic time 20854.746: supervisor write to a non-present kernel page, RIP clear_page_erms+0xb/0x20, PID 3045333, Comm VLLM::EngineCor. The stack goes through prep_new_page, get_page_from_freelist, __alloc_pages_noprof and do_anonymous_page, ending in Kernel panic - not syncing: Fatal exception. NVIDIA and device-plugin functions are absent from the failing stack.
- kernel.panic_on_oops=1 and kernel.panic=10 explain automatic restart after the fatal exception. vm.panic_on_oom=0 and systemd RuntimeWatchdogUSec=0. These settings were inspected, not changed.
- 02:12:28 MSK: the new boot began. All three Kubernetes nodes returned to Ready.

The initial empty /sys/fs/pstore listing was misleading: systemd-pstore had already archived the records under /var/lib/systemd/pstore/1792019487/{001,002}/dmesg.txt. The complete archive was copied to /home/alchemmist/llm-panic-20261015.tar on socrat-0 and /Users/antonmoss/.antex/artifacts/socrat-0-20261015/ locally. The 002/dmesg.txt copy contains the panic at lines 374-438. Preserve the original records for further diagnosis.

The fault occurred while zeroing a newly allocated anonymous system-memory page, not while reporting ordinary VRAM exhaustion. An earlier NVIDIA allocation error is relevant context but does not prove causality: model loading and GPU-cache profiling succeeded afterward. A process name in a kernel crash identifies the executing context, not proof of an application implementation defect. Earlier driver corruption, a kernel memory-management defect, and faulty RAM remain hypotheses.

The loaded kernel is 6.12.111+deb13-amd64; the NVIDIA open kernel module and user-space driver both report 615.71.09. No earlier Bad page, Bad RSS, MCE, AER, or slab corruption was found in the inspected previous kernel journal. Memory is two SK Hynix 16 GB modules configured at 2666 MT/s without ECC; absence of EDAC errors cannot exclude RAM faults. CONFIG_DEBUG_PAGEALLOC is disabled and CONFIG_INIT_ON_ALLOC_DEFAULT_ON is enabled. The previous 6.12.107 kernel and matching NVIDIA DKMS build are installed as a possible controlled comparison; no boot selection or driver change was made.

A temporary duplicate deployment, service, and empty Pending PVC created in the default namespace during manual chart application were removed. They did not obtain the GPU. The completed model-prefetch Job was removed. The inference workload is confined to the llm namespace.

NVIDIA device plugin v0.20.1 is now deployed and verified: one Ready DaemonSet pod, one allocatable nvidia.com/gpu, and RTX 3090 visible from the container. Updating the plugin did not restart k3s or the host. The upstream changelog does not identify a fix for this panic, so the upgrade is not considered a proven repair. vLLM v0.31.0 is the latest checked stable release. Qwen3-8B is an older baseline model, not the latest Qwen generation.

## Next diagnostic steps

If the failure recurs, stop inference and compare the new pstore physical page number and PTE flags against the first crash. A scheduled offline memory test can investigate RAM without the NVIDIA driver. If memory passes, compare one packaged kernel or NVIDIA driver version at a time, preserving a known boot fallback and collecting kernel/GPU telemetry off-host during an agreed reproduction. A successful small allocation test alone does not prove stability under the original workload. Do not disable panic handling, GSP, HMM, or memory initialization merely to hide the failure.

Source review found the known secretmem race that returned a page before restoring its direct mapping, but that race was fixed in Linux 6.12.59 and the corrected ordering is present in 6.12.111. It is not an identified explanation of this crash. The observed PTE also retains writable/dirty flags, unlike ordinary secretmem invalidation in that kernel. No exact upstream kernel/NVIDIA fix was identified. See [the stable fix history](https://www.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.12.59) and [the exact kernel implementation](https://github.com/gregkh/linux/blob/v6.12.111/mm/secretmem.c).

Primary references: [device-plugin changelog](https://github.com/NVIDIA/k8s-device-plugin/blob/main/CHANGELOG.md), [Linux page-zeroing implementation](https://github.com/torvalds/linux/blob/v6.12/arch/x86/lib/clear_page_64.S). Related but nonmatching NVIDIA reports [1431](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1431) and [1387](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1387) are leads, not confirmation of this root cause.

The initial service used Qwen/Qwen3-8B in BF16 as a baseline for GPU access, coding responses, streaming and tool calls. It has been replaced by RedHatAI/Qwen3.8-27B-INT4 for coding and longer conversations.

The NVIDIA device plugin runs only on socrat-0 in kube-system. vLLM runs in the llm namespace with runtimeClassName nvidia and one nvidia.com/gpu resource. Both charts are managed by ansible/playbooks/llm.yml. The host already has the NVIDIA driver and container runtime; the playbook checks these prerequisites without changing them or restarting k3s.

## Configuration

- Image: vLLM v0.31.0 with CUDA 13, pinned by digest in charts/vllm/values.yaml. The cu129 variant failed at startup because its TorchCodec dependency required libnvrtc.so.13.
- Model: RedHatAI/Qwen3.8-27B-INT4, compressed-tensors INT4 weights with BF16 activations.
- Model and tokenizer revision: 91bd022d5b49442a868bc35008f6c21e1860edfa.
- API model name: qwen3.8-27b.
- Context limit: 114688 tokens, including input, images and output. Open WebUI output allowance: max_tokens=16384.
- Maximum active sequences: one. Additional requests can queue.
- Vision enabled: up to eight images per request, resized to at most 1048576 pixels each. Video is disabled. The former language-model-only flag was removed.
- KV cache: FP8. With kv-cache-dtype=auto, this checkpoint’s quantization configuration selects FP8 during attention-layer initialization.
- GPU memory target: 95%, as requested after the initial 85% validation. This is not hardware isolation from Hyprland.
- Eager execution for initial bring-up; CUDA graphs can be evaluated later.
- Thinking disabled by default; qwen3_xml tool parser and qwen3 reasoning parser enabled.
- CPU request/limit: 2/8 cores. RAM request/limit: 12/24 GiB.
- Persistent model cache: 40 GiB local-path PVC, bound to socrat-0. Local-path does not enforce a filesystem capacity quota. Monitor free disk space.
- Deployment strategy: Recreate, because a second replica cannot reserve the same GPU during an update.

## Deploy

```sh
cd ansible
ansible-playbook playbooks/llm.yml
```

The playbook preserves an existing llm/vllm-api Secret and generates a random key on first deployment. It never stores the key in Git. The initial image and model downloads can take tens of minutes. Startup probing allows 30 minutes after the container starts; Helm waits up to 45 minutes.

The device plugin image comes from nvcr.io. During bring-up, this registry returned HTTP 403 from socrat-0. The official v0.20.1 image was fetched through socrat-2, its blobs and uncompressed layer diff_ids verified, and imported into socrat-0's k3s containerd cache. The Linux/AMD64 upstream manifest is sha256:d279ecdb47b252c4cd96f4224650e9808c36012f6979570c9611ddbc5b0749a7; the transferred Docker-save archive SHA256 is 6ce2e1e2e632a2067ccec9e282aba50d9b9f8ca7df5ac0328895d9aae3f8b970. Importing a Docker-save archive reconstructs its manifest, so the local manifest digest can differ while the verified content is retained. If the cache is removed, registry access or an image import is needed again; the playbook does not configure a proxy automatically.

## Access

The internal API is http://vllm.llm.svc.cluster.local:8000/v1. There is no Ingress or NodePort for vLLM. Requests require the bearer key from the llm/vllm-api Secret. Open WebUI already uses that key internally; LiteLLM remains a future deployment.

For access from your workstation, keep this SSH tunnel running:

```sh
ssh -L 127.0.0.1:8000:127.0.0.1:8000 socrat-0 'kubectl -n llm port-forward --address 127.0.0.1 service/vllm 8000:8000'
```

Load the key into your shell without printing it, then run the smoke checks:

```sh
export LLM_API_KEY="$(ssh socrat-0 'kubectl -n llm get secret vllm-api -o jsonpath="{.data.api-key}"' | base64 --decode)"
python3 scripts/check-llm.py
unset LLM_API_KEY
```

The checks cover model listing, a short coding response, SSE streaming, an automatic tool call, and continuation using synthetic tool data. They do not execute model-generated code or prove compatibility with every coding agent.

## Operations

```sh
ssh socrat-0 'kubectl -n llm get pods,pvc; kubectl -n llm logs deployment/vllm --tail=100'
ssh socrat-0 'kubectl -n llm exec deployment/vllm -- nvidia-smi'
ssh socrat-0 'kubectl -n llm scale deployment/vllm --replicas=0'
```

Scaling to zero releases GPU memory while preserving the model cache. Scaling back to one reloads the model. Helm uninstall preserves the cache PVC through its keep annotation; deleting that PVC explicitly can delete its local-path volume. The API Secret is managed separately from Helm and is retained.

The GPU and its cache are local to socrat-0. This service has no GPU failover to the other nodes. Preserve host RAM and VRAM headroom before increasing context length, parallelism, or model size.

Open WebUI model visibility: `qwen3.8-27b` is registered as a base-model workspace entry with a `user:*` read grant. Registered users can select and use it; editing remains administrator-only. Upstream-only models without a workspace access grant are hidden from regular users in Open WebUI v0.12.2.

Public WebSocket migration: pass the chart values file explicitly during Helm upgrades. A retained release override for the old private `webuiUrl` otherwise keeps CORS_ALLOW_ORIGIN on the old hostname and rejects the public Socket.IO handshake with 403. Fixed and verified with an open browser WebSocket across a heartbeat cycle on 2026-10-15.
