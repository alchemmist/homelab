# Venice browser API — Mac-independent production, 16 November 2026

## Current state (supersedes candidate-only/initial-login notes)

Public https://venice.socrat.alchemmist.xyz now routes to the bridge beside the
server Chrome on socrat-5. Old Deployment venice-api has desired replicas0.
The live Deployment retains the name venice-browser-candidate to preserve its
profile/PVC identity; it is now the production backend, NOT a second test writer.
No Mac browser, Mac HTTP proxy, or reverse SSH tunnel is in the serving path.

Requirement: Venice WEB UI through real Google Chrome, not official paid API.
Owner completed initial Google agaga login in the dedicated server profile.
Venice was initially Guest; ordinary Continue with Google signed it into the
existing owner account without password/MFA. No Google passwords handled by code.

## Ownership and runtime

GitOps: existing Argo Application venice-api, charts/venice-api plus
 deploy/venice-api/values.yaml. browserCandidate.enabled/bridgeEnabled/serveApi
are true. Service venice-api selects app=venice-browser-candidate. Legacy
hostNetwork/proxyServer/cdpUrl values cleared. No live image overrides.

Pod containers:
- chrome: real Google Chrome157.0.8103.78 + Xvfb, dedicated /data/profile,
  Default profile, sandbox enabled, no cookie injection/stealth. Image pinned
  to sha256:10f6a5c13bfbaee22ae1648d34f454a9537e3f4da5004f7218b2035214f9708b
  in harbor.socrat.alchemmist.xyz/homelab/venice-browser.
- egress: same image, native SSH -N -D127.0.0.1:1080 to10.250.0.2:2222.
  Dedicated venice-browser-egress Secret, existing VPS host key pin. VPS
  authorized key limited to source10.250.0.41, forced false shell, web80/443
  forwarding only; remote listen limited to privileged loopback1.
- bridge: canonical .Values.image repository/digest, CDP on127.0.0.1:9224,
  existing API_KEY from venice-api-env, public API on8080. bridgeImage override
  empty so ordinary CI/deploy-to-socrat releases update the live sidecar.

One replica/Recreate, stable hostname venice-browser, no API serviceaccount token.
PVC venice-browser-profile, 10Gi request, local-path venice-browser-retain,
RWO, actual PV Retain and node affinity socrat-5. Profile0700, process lock and
Chrome single-writer lock. This is local persistence, NOT HA/off-node DR.

NetworkPolicy denies direct external egress; permits only VPS SSH and DNS in
kube-system. Ingress only8080 (API bearer required); CDP9224 and VNC5900 bind
pod loopback, not publicly exposed. No hostNetwork.

## Authentication and response behavior

Bridge checks actual non-Guest account state, not merely account-menu existence.
Background startup/15s maintenance reuses the existing Google session if Venice
needs sign-in, serialized with request navigation. Password/MFA/identity selection
or consent is not bypassed; operator verification may still be required if Google
revokes its session. Persistent Google login is not an infinite-session guarantee.

Exact model DeepSeek V4.1 Flash Uncensored is verified before sending. Missing
selector or unsupported requested model fails closed. Assistant text is read from
.assistant .assistant-content .prose, never by cutting whole-chat text or deleting
legitimate answer lines. Generation deadline errors are not reported as normal stop.

SSE is deliberately BUFFERED until the DOM answer is final: Venice can rewrite
partial Markdown and append-only forwarding corrupted it in acceptance testing.
Initial role event + keepalive comments are sent while waiting; final assistant
text/stop/[DONE] follow. This is not native token streaming. Plain-chat roles
remain flattened; tool-bearing requests now use the strict Pi adapter described
below. temperature/top_p/max_tokens and tools are not native Venice API semantics.
Do not advertise full OpenAI feature compatibility.

## Acceptance evidence

- Direct server SOCKS Venice200, independent exit109.120.141.60.
- Direct external1.1.1.1:443 denied, proxy port81 denied, machine shell denied.
- Google/Chrome profile survives pod replacements; authenticated model pong
  passed after replacement, without owner relogin.
- Scoped Venice cookie clear (Google cookies untouched) redirected to /sign-in;
  automatic Google recovery then returned pong. This also found/fixed Guest
  account-menu detection and pre-login navigation ordering.
- Public endpoint: anonymous401, unknown model400, pong, long prompt -> violet.
- Public buffered SSE repeated twice, exact integers1..20 and [DONE].
- Obsolete Mac Venice reverse tunnels were absent; old Mac Python HTTP proxy
  explicitly stopped. Public pong and both SSE tests passed with them off.
- Eleven unit tests passed in the application image, including exact-model
  refusal, Guest detection, unmodified assistant text and DOM rewrite buffering.
- Process readiness/Argo Healthy is NOT a continuous model inference guarantee.

Source in alchemmist/venice-api main, release source8fc7600; browser-candidate
branch is retained as history, not the canonical development branch. The older
venice-api/docs audit is historical; this runbook records current acceptance. Current effective
image digest must be read from values/runtime; CI may publish a new digest of
that source after the initially accepted manual immutable image.

## Operator access / custody

Run scripts/browser-operator.sh from venice-api checkout on an authorized client.
Open vnc://127.0.0.1:5901. Password is in controller private file
~/venice-auth/server-browser/operator-password; never paste in chat/Git.
venice-browser-operator Secret stores its VNC password file. Controller custody
0700/0600; no runtime dependency on controller or /tmp files.

Closing port-forward only closes operator display, NOT Chrome/egress. Reopen the
forward after pod replacement. Do not terminate the owner's Mac Chrome or touch
its profile: it is no longer involved. Do not start another Chrome on the server
profile, broadly change VPN/DNS/routes, expose CDP/VNC, or promise session immunity.

Remaining: off-node profile backup/restore acceptance, extended soak and actual
Google-session revocation recovery (requires human if password/MFA requested).
Normal recovery uses Google SSO and was tested; full Google logout/revocation was
not deliberately induced. Any future browser image update requires rechecking
sandbox, SSO and DOM selectors before production handoff.

## Final CI and live closeout

GitHub Actions43866523454 completed SUCCESS for source8fc7600. Native release
updated canonical image through deploy-to-socrat; Argo reconciled40c1b553 and
recreated production pod with image
sha256:84244bd0d88e6669ed8bfa69adefbaab669a3e34a6f9910fee187de1f0209ffa.
No image override, Google relogin or Mac proxy was used after this rollout.
Fresh public checks after CI rollout passed: pong, four exact answer lines
(assistant/private/DeepSeek is a model/sources preserved), SSE pong+[DONE],
anonymous401 and health authenticated=true. VPS exit109.120.141.60 repeated.
Argo Synced/Healthy, one production Pod3/3; old standalone deployment0/0.

## LiteLLM integration — accepted 16 November 2026

Users can now call model **venice-deepseek** through the existing
https://llm.alchemmist.xyz/v1 endpoint with their own LiteLLM virtual keys.
The original direct Venice endpoint still exists; never give its upstream key
to ordinary LiteLLM users if access control is meant to stay in LiteLLM.

Canonical change: deploy/platform/litellm/values.yaml, not the legacy snapshot
in deploy/litellm/values.yaml. Existing Qwen route/image/database/migration fence,
users, key rights, SSO and logging settings preserved. LiteLLM remains1.105.1,
one worker/replica; no PostgreSQL upgrade or schema migration was enabled.

- Alias venice-deepseek maps to openai/venice-agentic-deepseek-v4.1-flash-uncensored.
- Internal api_base http://venice-api.venice-api.svc.cluster.local:8080/v1.
- API key injected from llm/venice-bridge-upstream Secret, api-key field, into
  VENICE_BRIDGE_API_KEY. Value is the existing bridge credential, whitespace
  normalized; not the LiteLLM master key. No credential value in Git.
- Current admission max_parallel_requests4 per deployment, timeout/stream_timeout900s,
  num_retries0. The bridge executes one generation and queues up to three other
  requests, with a180s wait timeout. Single worker/replica is material: the
  LiteLLM admission limiter is process-local.
  Do not scale LiteLLM without reconsidering model concurrency. Browser's own
  lock remains the final single-page guard.
- Synthetic input/output token cost0: this is NOT real Venice-credit accounting.
  Buffered SSE and browser adapter feature limits remain unchanged.
- Existing store_prompts_in_spend_logs=true retained: request/response text can
  be stored in LiteLLM. Integration did not silently change logging policy.
- Keys with all-proxy-models see the new model by their existing policy. Qwen-only
  keys were NOT expanded. No existing user/key rights were edited. When granting
  access, select venice-deepseek in the user/key model allowlists; owner/team
  restrictions still apply. No permanent test keys/users were created.

Live acceptance THROUGH PUBLIC LITELLM, not just its provider SDK:
- Venice-only temporary key /v1/models contains venice-deepseek, not Qwen.
- Qwen-only temporary key -> Venice403; its Qwen inference remains HTTP200.
- Venice non-stream pong and SSE pong+[DONE] passed, repeated after new bridge CI.
- Initial overlapping-request acceptance returned200+429. This exposed an
  unsuitable fail-fast policy for Open WebUI; the bounded queue fix below
  supersedes that policy without increasing browser generation concurrency.
- All temporary keys were deleted via native /key/delete. Original key count10
  restored, zero venice-acceptance fixtures. TTL10m was an additional safeguard.
- LiteLLM and Venice Argo Synced/Healthy; no master/Google/upstream keys printed.

Selector readiness flake found during research was fixed BEFORE prompt submission:
bounded20s model-selector hydration wait, still fail-closed on absent/unverified
model. No retry of sent prompts. Venice sourcec7593f4, CI43877841064 SUCCESS,
live bridge digest09ec0fbca255ca3cc4416c60bb1eb9fa4dddc6de42d859449545ee3c850a368b.
Twelve bridge unit tests and five dedicated static integration tests passed:
python3 -m unittest discover -s tests -p test_venice_litellm_integration.py -v
(from homelab). Resource manifests also passed Helm render/server dry-run.

Private config/deployment preimages are on the controller under
~/venice-auth/litellm-integration-20261116, not Git; no fixture keys remain there.
Rollback: remove only Venice model stanza/env reference through GitOps after
checking active calls; retain existing Qwen and database/SSO/key objects. Do not
rotate/delete the upstream bridge credential as part of a model-only rollback.

## Open WebUI overlapping-request incident — fixed

Owner chat3ef4ad84-466b-41ab-96a6-97bdf6a9295b showed LiteLLM deployment
max_parallel_requests1 exhaustion. Logs13:58:27/13:58:33UTC show overlapping
requests from Open WebUI10.42.6.28; one completed and one was rejected429.
The slot later freed. This was fail-fast admission, not proof of a stuck
browser or permanent slot leak. Installed LiteLLM MaxParallelRequestsLimit
explicitly raises429 and does not queue. The exact type of the first UI task
was not established; do not present background-title generation as proven.

Current design replaces that initial policy:
- LiteLLM admits up to4 in-flight calls for venice-deepseek only.
- Bridge MAX_PENDING_REQUESTS4 includes one active generation and three waiters.
  Actual browser access remains serialized by the original single-page lock.
- QUEUE_TIMEOUT180s bounds waiting; full/expired queue returns retryable busy
  errors (HTTP429 + Retry-After5 for non-stream, typed SSE error after streaming
  headers). It is not unbounded buffering or four browser generations.
- Cancelled waiters/active jobs release their slots. On active cancellation,
  the bridge attempts the visible Stop control before releasing its page lock.
- Streaming worker is also cancelled if the initial stream is disconnected.
- No retry of already submitted prompts, extra Google login, UI DB mutation,
  Open WebUI restart, Qwen limit change or existing key-permission change.

Venice sourcea39f5c9, CI43881708255 SUCCESS; live bridge image
sha256:b24dfc8d19643bed01aa56538333ce4c3fe9027fc56bc1c6ce21f876d57f9045.
Seventeen bridge unit tests passed, including overlap serialization, saturation,
wait timeout, active/waiting cancellation and slot release. Five integration
config gates passed with LiteLLM capacity equal to bridge capacity4.
Both Helm manifests passed server-side dry-run and were reconciled through Git.

Fresh acceptance FROM OPEN WEBUI POD with its existing upstream key and endpoint:
one non-stream and one SSE request were started together. Both returned200/pong,
completed in11.0/19.5s, SSE ended with[DONE]. This tests the real UI upstream route,
not a replay of the owner's private chat or a claim of browser/UI-click acceptance.
The existing failed chat message is unchanged; retry/regenerate it in the UI.


## Pi text-function adapter — 16 November 2026

Source `alchemmist/venice-api` commit **0c2bfc7**, CI **43892239711**
(second attempt SUCCESS; first failed at Harbor TLS handshake, before publish).
GitOps release `3abc9bb5`, immutable bridge image:
`sha256:4c4b66c38283289dee0b67a985b779b8ee57f48dc5f4d66363334f8c84a22106`.
Deployment UID unchanged; new server Chrome pod Ready3/3 and Argo Synced/Healthy.
Google session recovered through the existing profile, no manual login or Mac
browser/proxy dependency. Local test adapter was stopped before final acceptance.

### Implemented contract

- OpenAI text function tools, single call per step; auto/none/required/named choice.
  JSON Schema argument validation, no coercion, external refs rejected. Custom/
  grammar tools and non-text blocks rejected, not silently treated as supported.
- Ordered role/content/tool_calls/tool_call_id history, null assistant content,
  multiple matching results and tool errors preserved. Unknown tools, malformed
  JSON, duplicate JSON keys, mismatched results and oversized envelopes fail closed.
- Non-stream assistant.tool_calls with bridge-generated IDs and JSON-string
  arguments; buffered SSE indexed delta.tool_calls, finish_reason=tool_calls,
  [DONE]. Final text uses stop. No cluster command runner: Pi runs tools locally.
- Sole complete raw envelope is recognized only from the current assistant's
  pre-Markdown source, using bounded/validated React Markdown props traversal.
  Missing/ambiguous UI props fail closed; no lossy DOM-text fallback, regex command
  extraction, clipboard use or hidden format-repair generations.
- Protocol namespace is pi_bridge/action/target/payload (invoke), or action=answer
  with text. Ordinary Markdown strips JSON backslashes; fenced/inline code
  experiments triggered native Venice tool attempts or delimiter collisions and
  FAILED acceptance. Those intermediate results are not successful releases.
  The source-based raw JSON path passed the real tests below.
- Queue4/wait180s, one actual browser generation, cancellation and no bridge retry
  of submitted prompts retained. Pi itself may retry model errors; the bridge is
  not an exactly-once shell execution ledger. Pi/user permissions remain authority.
- Agent prompt budget120000 UTF-8 bytes, response envelope65536 bytes. These are
  conservative adapter budgets, not proven model context limits. Approximate
  character-count usage now reaches Pi via SSE finish events, allowing context
  tracking/compaction heuristics; it is NOT native token or Venice-credit accounting.

### Evidence and limits

- **31 application contract/unit tests** pass (including original browser/queue
  tests and lossless-source/boundary tests); **5 homelab integration tests** pass.
- Final real Pi1.5.2 through PUBLIC LiteLLM, existing owner's virtual key, buffered
  SSE, isolated temporary fixture: two read calls; bash unittest exit1; edit
  subtraction to addition; bash unittest exit0; write JSON with quotes/backslashes/
  newline; read-back. All seven tool calls occurred locally, not in Venice.
  Independent local JSON check passed. Approximate usage is nonzero in Pi events.
- Pre-release source-based bounded run: 12 separate reads of random fixture values,
  write collected.json, bash verifier exit0: **14 calls /182.5s**, zero model errors;
  independent manifest comparison matched all12 values. This used a localhost
  adapter forwarding to the same server browser; do not claim it was the final
  public-LiteLLM route or a multi-hour soak.
- Final public LiteLLM non-stream named read choice -> tool_calls; linked synthetic
  result + tool_choice=none -> final with the actual result string. No rights edited.
- After final rollout, concurrent non-stream/SSE from Open WebUI pod using its real
  existing upstream configuration both returned pong (13.0/22.9s, SSE [DONE]).
  This is upstream-route acceptance, not replay of a private owner chat/UI clicks.
- Existing Qwen user route returned200 during acceptance. No LiteLLM upgrade,
  database migration, global provider API change, model ACL expansion or secret
  rotation. Pi retains per-model openai-completions; only Venice's
  supportsUsageInStreaming was changed from false to true so it requests
  stream_options.include_usage. LiteLLM strips usage without that request.
  A fresh real public Pi session then recorded input1655/output20 for read and
  input1735/output73 for final. First repeat hit public connect timeout; the
  following read-only run passed. Dotfiles already had unrelated dirty changes;
  only that Venice flag was edited and no dotfiles commit/push was made.
- A Pi process interrupted with SIGINT emitted no local tool events; a following
  independent session completed pong. Detailed lock/slot release is unit-tested;
  do not infer exactly-once distributed execution from this disconnect smoke test.

Start a **new** Pi session, choose `litellm/venice-deepseek` (or
`pi --provider litellm --model venice-deepseek`). Old chats containing claims about
missing shell access are not useful acceptance fixtures. Built-in read/bash/edit/
write were tested; arbitrary extensions/custom tools are not collectively certified.

**Hours-long unattended operation is NOT certified.** Native Venice instructions,
UI/React changes, navigation/network timeouts, approximate compaction/context and
Google-session revocation remain risks. One initial bounded attempt hit navigation
90s timeout and malformed JSON; validation emitted no write, Pi retried and stopped.
Long-running work should remain bounded and inspected, with normal Pi permissions.

Detailed adapter contract: `venice-api/docs/pi-agent-protocol.md`. Private real Pi
journals/preimages/fixtures: controller `~/venice-auth/agent-adapter-20261116/`;
no credentials or private transcript payloads committed here.

### Follow-up: ordinary owner's Pi configuration, not a minimal harness

Owner requested stronger acceptance. Pi1.5.2 was run with its **normal real user
configuration**, no isolated agent dir and no no-extensions/no-mcp/no-skills flags,
against public `litellm/venice-deepseek`. Its system advertised13 tools, including
codemode. Work was restricted to a new disposable controller fixture.

- Initial normal Pi session: actual bash inspected files; a real unittest run
  found2 failures out of3; edit corrected the Decimal tax formula; rerun3/3 passed;
  write created REPORT.md. Five tool calls; no model protocol errors. The initial
  model command echoed EXIT=1/0 after unittest (outer shell exit0), so the failure
  evidence is actual unittest output, not that wrapper's shell status.
- Reopened the same saved session: actual codemode invoked nested local read and
  bash tools; tests passed; write created CONTINUATION.md. No model protocol errors.
- Three more separate read calls consumed32466 bytes of synthetic context;
  returned all three end markers and nonzero usage, no model errors.
- Manual compaction via actual Pi RPC succeeded: tokensBefore15896,
  estimatedTokensAfter13468, reported summary-call usage4474/1310. Afterwards
  real bash read the corrected file and ran unwrapped unittest: all3 passed,
  actual structured exit_code0, final answer and agent_settled completed.
- Active-command cancellation through RPC: local bash started a harmless Python
  sleep and printed12345; abort returned `Command aborted`, agent_settled aborted
  true. In the SAME Pi process, the next task ran unittest successfully with raw
  exit_code0 and settled normally. Completion marker67890 was never produced.
- Independent comparison confirms the fixture test file was NOT weakened/edited.

Only Venice's compaction settings were tuned in the existing dirty dotfiles:
`compaction.modelOverrides["litellm/venice-deepseek"]` now reserveTokens12000,
keepRecentTokens6000, rather than retaining the global20000-token recent window
inside this32768-context model. Other model/default settings were preserved;
preimage is private; no dotfiles commit/push. Small-session manual compaction
first returned the honest `Nothing to compact (session too small)`; the successful
check above used the larger synthetic context and does not imply automatic
multi-hour compaction has been soak-certified.

Public connectivity is a separate remaining limitation: one intermediate RPC
follow-up got repeated Node UND_ERR_CONNECT_TIMEOUT before model completion.
Controller ordinary DNS resolved HOME109.173.40.247 and VPS109.120.141.60.
Two credential-free forced-IP Host/SNI/TLS checks returned401 from HOME while
VPS TCP443 timed out. This is THIS vantage's reachability result, NOT proof of
worldwide VPS outage or stale DNS. The existing public DNS runbook already warns
about partial reachability/failover limitations. No DNS/VPN/route/ingress changes
were made; normal subsequent Pi sessions succeeded. Network failure must not be
presented as a function-call failure, nor hidden under an hours-long reliability
claim.

Private evidence: `~/venice-auth/agent-adapter-20261116/normal-pi-acceptance/`,
including real session/tool events, compaction and abort RPC receipts, unchanged
test hash and generated reports. This strengthens actual normal Pi compatibility;
it still does not certify every one of13 tools or unattended multi-hour work.

## Five-point hardening release — 16 November 2026

Implemented by owner request, source `af1c640` (application changes `f7475e4`),
CI **43921572102 SUCCESS**, GitOps image update `15b6479e`:
`sha256:3cf6143c948c182661942eb65dacc7b6284876a32a021678f45e4cfc747585b1`.
Production deployment UID remains `2d7c20a1-cf02-4185-a7e9-237cb1be9d00`;
new pod Ready3/3, Argo Synced/Healthy. Hashes of deployed main.py and
agent_protocol.py match the checkout exactly. No live image override, secret
rotation, profile migration/deletion, Google login reset or Chrome image upgrade.

### Changes

1. Shared default-deny `.dockerignore` allows exactly8 required build/runtime
   files for BOTH recipes. CI uses real BuildKit scratch export on staged allowed
   sources plus synthetic .env/Git/profile/cookies/debug/private-script canaries.
   It does NOT stage the controller's actual profile or secrets. Runtime COPY
   dependencies are checked by unit tests. No arbitrary future directory is
   implicitly included.
2. Agent budget failure now returns OpenAI-style HTTP400
   `error.code=context_length_exceeded` before browser generation or SSE headers.
   Safe accounting includes total/limit, serialized UTF-8 message sizes,
   non-message overhead, fixed instructions/tools budget, count and largest3
   message indices/roles/sizes. No contents/paths/arguments/call IDs are echoed;
   no trimming. Guidance distinguishes message compaction/output reduction from
   tool definitions that cannot fit even with empty history. Size hints are also
   in the message because LiteLLM1.105.1 normalizes error.code to the string400
   and may not preserve all extra fields. The installed Pi1.5.2 overflow detector
   recognizes the error text.
3. JSON floating overflow, including deeply nested1e999, is rejected at parsing,
   in addition to nested duplicate keys and NaN/Infinity. Native nonfinite values
   in schema/message extras are rejected before serialization.
4. History validates call/function shape, role placement, names/IDs, JSON-object
   arguments, ordered matching results and non-null non-assistant content.
   Assistant text plus calls remains LEGAL. Arguments are checked against current
   schemas; old invalid attempts/schema evolution/removed tools are annotated via
   history_validation and retained with linked results, not coerced or rejected
   wholesale. No inference of error semantics from arbitrary text, no historical
   re-execution, and no weakening of validation for NEW calls.
5. Root README now documents runtime ownership, mode-specific env, build context,
   secret wiring, context errors and limitations. Old infrastructure audit has an
   explicit historical warning. Bridge image no longer implies a cookie-file
   mount; standalone cookie import is explicit COOKIES_FILE only, never auto-read
   from home. A missing explicit file fails initialization and closes the created
   context. Default standalone profile is outside the checkout under XDG/home,
   private0700, with no automatic migration of existing data. Production remains
   CDP plus the existing server Chrome PVC; observed CDP env present, implicit
   cookie env absent.

### CI and actual acceptance

- **57 application tests**, including all previous queue/browser tests, passed
  locally and on native CI Python3.12. **5 homelab integration tests** passed.
- CI BuildKit audit verified exactly8 files; actual bridge image imports passed.
  First attempt failed Harbor login TLS; second built/published but extra pull for
  smoke hit token-service TLS timeout, so no deployment occurred. The final
  workflow publishes AND loads the same BuildKit result, then smoke-tests its
  local source-SHA tag with `--pull=never`; deployment still uses the published
  immutable digest. Job/build/smoke have bounded timeouts. No shared DNS/network
  configuration was changed to mask those failures.
- Direct running bridge: stream/non-stream over-budget ->400 with typed code and
  safe largest-message accounting; nested1e999/NaN/Infinity/-Infinity and duplicate
  keys ->400. No private canary content appeared in diagnostics.
- PUBLIC LiteLLM: both over-budget modes ->400 with actionable size/compaction
  hints (normalized code400); nested numeric overflow history ->400. Synthetic
  history with path17 plus a linked validation error was accepted for replay;
  named next call used schema-valid string path fixture.txt. This last probe
  validates wire correction, not actual filesystem execution.
- Ordinary owner's Pi, real configuration/extensions, public LiteLLM, disposable
  fixture: **7 actual calls, zero model protocol errors**. read missing-note.txt
  intentionally failed; two real reads succeeded; unwrapped unittest returned
  actual exit1; edit fixed discount addition to subtraction; unwrapped rerun
  returned exit0; write created REPORT.md. Independent test run passed2/2 and
  original test SHA was unchanged. Error results therefore remain replayable.
- Concurrent ordinary chat and SSE from Open WebUI pod using its existing
  upstream config both passed pong (9.0/18.4s, SSE DONE). No private owner chat
  replay or UI-click acceptance claimed. Helm render/server dry-run passed.

Private receipts/preimages/Pi events/report: controller
`~/venice-auth/bridge-hardening-20261116/`.

**Scope limit:** this package does NOT fix the separate intermittent native
Venice agent/tool-registry confusion reported by the owner. Successful fixture
runs are not a guarantee for every project/session or unattended hours. Public
connectivity/failover limitations and approximate context accounting also remain.

## Native Venice tool isolation — 16 November 2026, 19:00 UTC acceptance

This supersedes the preceding hardening release's unresolved native-agent scope
limit, but is NOT a claim of infallible model answers or multi-hour certification.
Owner identified the blocked Pi in tmp window2, lower pane %75. Its saved log
contains successful real host calls followed by assistant prose claiming
Tool not found; the quoted missing bash/read/write/codemode/web_fetch errors were
NOT actual Pi toolResult events. Do not repair a healthy local registry based on
those assertions. The last real bash reading main.py470–700 had succeeded.

### Root boundary and implementation

Source **bd0f200028e36b2d5984d7f1acb1da3004897456**, native CI
**43930013632 SUCCESS** (third attempt; first two failed Harbor login TLS before
build/deployment). Published/deployed bridge:
`sha256:bcf4bcb60bf422e662d80da54076a817ce90071f0e6173785d51fe6ceaa98cfb`.
New pod `venice-browser-candidate-869456686f-k2v9c` Ready3/3, zero restarts;
Argo Synced/Healthy. Deployed main.py/agent_protocol.py hashes match Git source.

The former web-native /agents/venice runtime had its OWN tool dispatcher and
instructions; merely asking it to emit an external JSON envelope did not isolate
host calls. The current browser composer request is forwarded exactly ONCE to
Venice's web-client **/api/inference/chat/agents/ad-hoc** operation, preserving
browser authentication without extracting tokens. Payload uses explicit
`modelId=deepseek-v4-1-flash-uncensored`, text system instructions, `tools=[]`,
`clientTools=[]`. This disables ONLY browser-runtime tools, NOT Pi's host tools.
The frontend-shipped ad-hoc schema was inspected and actual responses verified.
No official paid Venice API, standalone HTTP inference client or response replay.

All bridge completions, including ordinary chat and compaction, use this text
transport. Plain/compaction instructions do not demand JSON. Agent envelopes,
strict current schemas, history replay policy and local permission authority are
unchanged. Only the current exact composer message is forwarded; full Pi history
is already inside it and is NOT trimmed. Earlier browser messages/native approval
or media tool declarations/other request fields are not forwarded.

Default AGENT_INFERENCE_ORIGIN is https://outerface.venice.ai. Unknown inference
POST/origin, composer mismatch, repeated native continuation or missing rewrite
fails explicitly with HTTP502 / upstream_agent_transport_error, not a successful
fake final. Routing is removed in finally, including installation cancellation.
No native fallback, hidden repair generations or natural-language error filtering.
The UI/private web-client schema is still an upstream maintenance dependency.

### Evidence and limitations

- **71 app tests** and existing **5 homelab integration tests** passed. Actual CI
  BuildKit context remains exactly8 allowed files; image import smoke passed on
  the same locally loaded BuildKit result before GitOps deployment.
- Pre-release actual browser: reconstructed owner's compacted context, **82067
  prompt bytes**, produced the correct external read request for main.py700–799.
  Then30 sequential model-visible calls with increasing history and quoted fake
  Tool not found file data passed. Final correctly counted30 host results. All33
  responses (replay,30 calls,final,plain pong) were HTTP200 on ad-hoc, not venice.
- Cancelled an active ad-hoc stream after actual response headers; route/queue
  lock released, next request in the SAME browser session returned pong.
- PUBLIC LiteLLM, ordinary owner's Pi/config/extensions, disposable fixture:
  **29 actual calls**, expected missing-file read error, failing unittest exit1,
  edit, passing unittest exit0/report,20 separate direct reads, write/read nonce
  JSON. All20 random nonce strings matched exactly; test SHA unchanged. This was
  not one codemode bulk-read hiding many files behind one model turn.
- Exact owner-session COPY (original pane/session untouched, SHA unchanged): real
  read700–799 plus real bash pwd/wc succeeded. Manual compaction of this actual
  large context succeeded **17771 → estimated14964 tokens**; actual read and bash
  succeeded again afterward. Fresh fixture compaction initially returned the
  legitimate Nothing to compact (history below keepRecent6000); this refusal was
  retained, not misreported as successful compaction.
- Active local bash sleep aborted, same Pi process ran tests exit0 afterward.
  Saved-session process restart performed real read and tests exit0. Separate
  real codemode executed nested read/bash, and real host web_fetch read public
  Python Decimal documentation. Across these live acceptance runs: **41 actual
  tool-end events, zero model protocol errors**. Expected read/test/abort errors
  were actual local results and did not cause fictitious registry failure.
- Repeated public safe-budget stream/nonstream, nonfinite rejection and historical
  schema-error correction checks passed. Open WebUI pod ordinary chat and SSE
  both passed via its existing upstream configuration.

No original tmux input/session rewrite, host tool registration/permission change,
model/settings change, key rotation, Google reset, profile/PVC migration, Chrome
image upgrade, Mac Chrome/tunnel runtime dependency or shared network change.
The same public alias continues working without restarting Pi. Prior audit claims
based on HEAD0c2bfc7 are not accepted as verified findings for current source.

Receipts, exact replay, both successful and initial ineligible-compaction results,
Pi events, protected test hashes and fixture reports are private on controller:
`~/venice-auth/native-isolation-20261116/` (dirs0700/files0600).

Remaining: private web-schema/React source extraction changes can still require
maintenance; network failover/TLS timeouts and approximate usage remain separate.
This bounded acceptance does not certify unattended multi-hour operation, MCP
services not exercised here, or correctness of every natural-language claim.
