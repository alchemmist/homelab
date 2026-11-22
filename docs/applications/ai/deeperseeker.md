# DeeperSeeker: the DeepSeek web-session bridge for `o-deepseek`

The acceptance results below are from **19 November 2026**. The limits recorded after rollout at `1687e0d8` are a separate checkpoint, not a second successful chat test. Git describes the intended deployment; it does not contain the live session token or VPN subscription. Never print credentials or put them in Git, logs, issues or chat.

## Deployment and ownership

| Component | Repository source or setting |
| --- | --- |
| Application | `deploy/argocd/apps/deeperseeker.yaml`; namespace `deeperseeker`, pruning disabled |
| Chart and overlay | `charts/deeperseeker` and `deploy/deeperseeker/values.yaml` |
| Bridge image at acceptance | `harbor.socrat.alchemmist.xyz/homelab/deeperseeker@sha256:696884aa3c846f4471b6876b4b3455e8fa047dfd2638f050c5f0b8cf270e16ac` |
| Placement | `socrat-5`, `Recreate` strategy, process UID 10001 |
| Storage | `deeperseeker-data`, 2 GiB `local-path` ReadWriteOnce PVC mounted at `/app/data` |
| Access | ClusterIP `deeperseeker:4000`, no ingress; operators use `kubectl port-forward` |
| VPN sidecar | `ghcr.io/mhsanaei/3x-ui@sha256:1628adbd9bed680d25d6f714bef4a20f132105f4612ea294952f6665dad32e5b` |

The image uses the [DeeperSeeker fork](https://github.com/artyom08-dev/deeperseeker) at `1b1148ec1e2a` (package 7.0), with local proxy wiring. The chart copy is `charts/deeperseeker/files/proxy-wiring.patch`; the rebuild copy is `deploy/deeperseeker/patches/proxy-wiring.patch`. A clean upstream build does not include that wiring. Pin the manifest digest served by Harbor: the initial local `RepoDigest` (`sha256:8bda1721…`) was not available from the registry and caused `ImagePullBackOff`.

## Network and secrets

The bridge follows the [service VPN egress contract](../../network/vpn-egress/service-vpn-egress.md). `svc-free-deepseek` is the bridge's dedicated service identity, not a retired pod identity. Revoking it stops bridge egress. The sidecar provides a loopback-only SOCKS listener on `127.0.0.1:1080`; the pod does not use host networking. The browser and upstream HTTP client require explicit proxy configuration. The chart sets `DEEPSEEKER_BROWSER_PROXY` and `DEEPSEEKER_UPSTREAM_PROXY`; upstream DNS resolution goes through the tunnel. NetBird and personal SSH access are not application egress paths.

| Secret | Namespace | Keys and purpose |
| --- | --- | --- |
| `deeperseeker` | `deeperseeker` | `admin-user`, `admin-password`, `api-key`: private dashboard and bridge API |
| `deeperseeker-service-vpn` | `deeperseeker` | `subscription-url`: service VPN subscription |
| `deeperseeker-harbor-pull` | `deeperseeker` | Registry pull credentials |
| `deeperseeker-upstream` | `llm` | `api-key`: LiteLLM's bearer credential for the bridge |

The operator's local dashboard credential file is `~/.config/homelab/deeperseeker-credentials` (mode `0600`), outside Git. The bridge credential is distinct from the upstream account session: a valid bridge key does not establish that DeepSeek accepts the account.

## Health checks and incident diagnosis

| Observation | Interpretation |
| --- | --- |
| `GET /health` returns `503` with `{"status":"degraded"}` and the token pool is empty | The process is alive. Liveness uses TCP port 4000; HTTP liveness previously caused restart loops before login. |
| `/health?deep=1` returns `401` without a bearer credential | The **bridge** rejected the probe; this is not an upstream response. |
| Authenticated deep probe returns `503`, `no ACTIVE token in pool` | No upstream call is made. |
| Authenticated deep probe returns `503`, `deep.upstream_reachable=false`, with `401` in `deep.reason` | The bridge accepted the key but upstream rejected the session. This was observed even with an `ACTIVE` token and `cookies_valid=true`. |
| Deep probe returns `200` | The read-only `users/current` check succeeded. It does not create a chat or demonstrate sustained chat capacity. |

Readiness runs the authenticated deep probe inside the pod with `DEEPSEEKER_API_KEY`. Until it succeeds, the pod is not a ready Service endpoint. An earlier unauthenticated readiness probe left the pod at `1/2` even when a manual authenticated probe passed; `8cde6d07` fixed it. Do not weaken readiness or add another scheduled deep probe.

`SocratDeeperSeekerSessionLoggedOut` reports a running bridge container that has not been ready for five minutes. It does not report a stopped container. `SocratContainerRestartsFrequent` covers repeated restarts (three in 30 minutes). The Deployment's `progressDeadlineSeconds: 604800` prevents session quarantine from looking like a stuck rollout; it does not silence the session alert. The historical alert silence expired on 21 November 2026 at 23:48 +0300 and was not intended for renewal.

## Acceptance results and their limits

On 19 November, pod `deeperseeker-cf68c6dbd-ccwcv` was `2/2 Running` with zero restarts. The authenticated deep probe returned `200`, `active_tokens: 1`, `pow_ok: true`, `upstream_reachable: true`, `chat_created: false` and 645.5 ms latency. A short `v4.1flash` chat returned `200` and `pong`. LiteLLM also returned `200` and `pong` for `o-deepseek`. These were individual requests, not a load test or a day of stable service. Cookie regeneration inside the pod was not verified.

A later checkpoint recorded alias `main` as `QUARANTINED`. One restore and one short request produced `40003 INVALID_TOKEN`, and quarantine resumed. No second restore was performed. A degraded Argo health status is expected when quarantine leaves the bridge without a usable token. A restriction or upstream rejection is a reason to stop requests, not to roll back the limits or route around the restriction.

## LiteLLM routing and load limits

`deploy/platform/litellm/values.yaml` exposes `o-deepseek` at `http://deeperseeker.deeperseeker.svc.cluster.local:4000/v1`, with upstream model `openai/v4.1flash`. `DEEPSEEK_PROXY_API_KEY` comes from `deeperseeker-upstream`. The configured input limit rose from 32,768 to 369,228 tokens; the output limit remained 8,192. `v-deepseek-uc` is a separate Venice route. `openhands-monori` is not connected to this bridge.

| Control | Recorded setting | Why it matters |
| --- | --- | --- |
| LiteLLM `rpm` | `6` | Shared model limit across keys, not an allowance for each key |
| LiteLLM `max_parallel_requests` | `1` | Only one model request at a time |
| LiteLLM `max_retries`, `num_retries` | `0` | Do not repeat rejected requests |
| `DEEPSEEKER_MAX_UPSTREAM_ATTEMPTS` | `1` | No additional upstream attempt after rejection |
| `DEEPSEEKER_RATE_LIMIT_COOLDOWN` | `300` seconds | Do not immediately return a limited session to the queue |
| `DEEPSEEKER_CALL_GAP_SECONDS` | `4` | Delay after a turn; not a rate limit on new chats |
| `DEEPSEEKER_TOKEN_CONCURRENCY` | `1` | Serialize work for a single session |
| `DEEPSEEKER_PERSIST_SESSIONS` | `true` | Reuse conversation state across restarts |

Requests per minute and new upstream chats are different measurements. Different histories, interrupted streams and context rollover can create additional chats. The recorded Loki rule `deeperseeker:web_chats:created:1h` cannot count successful chat creations on the deployed digest: that build logged `chat_session/create` on errors but not on success. Do not use it as a capacity metric.

## Build evidence and recovery boundaries

The candidate `1b1148ec1e2a-hints` (`sha256:3cab7de3a4c23787e808d62364abc079ff98c60b8b8713edb55e1800e840d1df`) was tested locally on amd64, **not deployed**. Its authenticated `/v1/models` response listed `v4.1flash`, and a local mock produced `created chat_session mock-1`. This is not evidence of a successful production session. The tested image contained Chrome for Testing `156.0.8078.4`; headful startup failed with `SIGTRAP` even with Xvfb. The recorded settings remained `DEEPSEEKER_COOKIE_HEADLESS=true` and `DEEPSEEKER_WARMUP_NON_HEADLESS=false`.

A restart may contact upstream. Do not restart a quarantined account to test recovery or repeatedly restore a rejected token. Local session state is on the PVC at `/app/data/deeperseeker.db`. The token purge endpoints are **not** local cleanup: they request upstream chat deletion. Do not use them to clear local state. After an authorized recovery, verify an authenticated deep-probe `200`, readiness of both containers and clearance of the related alerts. Keep the service VPN secret when retiring the old pod in `llm`.
