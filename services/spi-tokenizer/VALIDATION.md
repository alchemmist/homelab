
## Source-only local counter validation completed — 2026-11-06

CODE_READY for source only; **not activation or live acceptance**. This supersedes
the earlier unfinished lifecycle validation, not the blocked three-card live gate.
No current cards were queried or forced. Default remains byte-bound-v1.

### Installed-reference actual-payload oracles

Read-only SQLite historical prefixes were reconstructed through actual
Model.analyze; Model.call was intercepted before admission/transport. Payloads
were passed in pipes only, not persisted or printed. Installed CPU-only
AutoTokenizer.from_pretrained(local_files_only=True) in the existing vLLM
container applied add_generation_prompt=True, enable_thinking=False to the
actual messages. No generation/inference endpoint was used. Local native IDs
(add_special_tokens=False) matched reference IDs by SHA256 of canonical JSON
integer lists; rendered UTF-8 hashes and counts also matched in every row.

| Prefix | Input JSON bytes | Local reservation | Reference prompt | Prompt + 2500 | Headroom | IDs/render/count match |
|---|---:|---:|---:|---:|---:|---|
| e712 | 18421 | 9315 | 5366 | 7866 | 1449 | true |
| de23 | 22703 | 10999 | 7050 | 9550 | 1449 | true |
| 1cbe | 27564 | 12023 | 8074 | 10574 | 1449 | true |
| 0900 | 27203 | 12433 | 8484 | 10984 | 1449 | true |
| 613a | 28594 | 13229 | 9280 | 11780 | 1449 | true |
| 1482 | 21683 | 10826 | 6877 | 9377 | 1449 | true |
| 9b7 | 20980 | 10335 | 6386 | 8886 | 1449 | true |

Public ASCII contractions, NFC café, four-byte emoji, combining e+acute,
escaping and literal template/special-token injection fixtures also matched.
Empty-system rendering is separately exercised by the maximum-size fixture.
The manual render was confirmed for these supported inputs, not replaced by
rounding or a chars-per-token guess. Unsupported models/roles/tools/thinking
remain fail-closed. No private body/encoding cache exists.

Pinned public source base:
https://huggingface.co/RedHatAI/Qwen3.8-27B-INT4/resolve/91bd022d5b49442a868bc35008f6c21e1860edfa/

- tokenizer.json SHA256 06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523
- chat_template.jinja SHA256 c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041
- tokenizer_config.json SHA256 5f7aa0d810000c4a0940b35c8f16e56c3439260fccc13a321826ebc3ccf2501f
- tokenizers 0.22.2 musllinux wheel SHA256 38337540fbbddff8e999d59970f3c6f35a82de10053206a7562f1ea02d046fa5; immutable public wheel URL in services/spi-tokenizer/wheel-url.txt.

Reservation is exact supported rendered prompt count + full response-format
UTF-8 bytes + 256 allowance + explicit completion cap (2500 or 768), not exact
provider usage. Historic headroom is 1193 schema bytes + 256; public {} fixtures
have 258 headroom. Reservations are materially below the validated byte bound;
no provider-alias equivalence beyond this pinned contract is asserted.

### Regression, memory and effective scheduling

Separate ephemeral validation image added only Node v24.22.1 and git 2.54.0 to
the existing candidate, Python 3.13.18 unchanged. Production Dockerfile has no
Node/git. Absolute real paths were used for Docker mounts; the existing common
Git directory was mounted read-only at /Users/antonmoss/code/homelab/.git.
Final validation image 9b64190ce002ebfb12132816baa06129dd33d2c890bf67ce02e3af4538a84af3
is the tool-extended candidate with the same legal files overlaid, not a runtime
artifact. Source-only packaged production image:
5b9b9c6da929f902902d7b415d923000004e3ddcb6560bbb568c9d86fd4841d1.

All **206** SPI tests pass in local mode, 384MiB/1CPU/network none, zero skips,
errors or OOM; 41.337s, 277800 KiB peak process RSS, 24 retained Models share
one native counter (8.538s initialization/validation). Peak is not steady RSS.
All original correctness fixtures remain; no runtime feature edits. Native
asset/template/library/manifest failures reject Model construction before any
recovery/admission/HTTP calls; request model/roles/tools/thinking failures reject
accounting before admission/HTTP. Local 60k compressible JSON succeeds with a
valid fake response; deterministic incompressible 60k rejects before HTTP.
Legacy assertion explicitly selects byte-bound mode instead of hiding failures.

Byte-bound compatibility in the asset-equipped validation image: 206 tests pass,
zero skips (29.585s). Native host: 206 tests pass, three optional native class
cases skipped because the host lacks /opt/spi-tokenizer (4.095s); this is not
substituted for the zero-skip local image result. Helper suites: 4 chart + 1
writer-secret tests pass. Ingress JS: 9 pass, zero skips. Helm lint/template and
git diff --check pass.

New typed integer-cost fake-clock durable-ledger regression uses actual native
costs [3586,3586,3586], sum 10758 vs byte-bound [18299,18299,18299], sum 54897.
Three serial calls fit 30k TPM/3RPM; parallel reservation rejects; fourth rejects
until first completion+61 (161.999 rejects, 162 accepts). Reopening Store after
each completion retains charges; actual=1 never refunds. Upward actual=30000
persists across restart, blocks until completion+61 (223.999 rejects,224 accepts).
This proves synthetic effective admission, not live throughput or a card ETA.

### Packaging and operations

Build is deliberately a strict verified preloaded asset context, not a universal
fetch script: sh services/spi-tokenizer/build-local.sh /path/to/verified/assets.
No repeat 20MB download is required. Build/runtime pins and wheel are unchanged.
Matching immutable upstream tokenizers LICENSE and Rust LICENSE pointer are
preserved in services/spi-tokenizer/legal and copied into the internal image.
Commit f383101a26663708484cac0727792aad74f78234 (v0.22.2) recursive upstream tree
contains no NOTICE; none invented. See legal/PROVENANCE.md for exact public URLs,
hashes, model Apache-2.0 declaration/attribution and canonical Apache license.
No model weights, third-party shipping or certification of all transitives.

No push/deploy/queue/provider/resource changes; runtime network remains disabled
for validation. No source-phase claim about current three cards, no new probes,
nominee grouping or lifecycle redesign. Credentials, IDs, PVC, calendar/Yandex,
blog-off, Root network, Mac/DNS/edge unchanged. Rollback selects original image
and byte-bound-v1, preserving database/cache/v3 proofs and integer ledger charges.

## P1 correction: native-plus-proxy floor (source only)

This supersedes the earlier native-only reservation formula and 3586-token
synthetic charge, **not** any activation/live-acceptance gate. Default remains
`byte-bound-v1`; no rollout or remote/model/quota configuration change is included.

For `local-qwen-v1`, method **native-qwen-plus-proxy-floor-v1** is:

```
max(native_rendered_prompt_tokens + response_format_utf8_bytes + 256,
    ceil(sum(len(raw_HTTP_message.content)) / 4) + 256)
+ explicit_max_tokens
```

The supported contract remains model `qwen3.8-27b`, exactly system/user string
messages without extra message fields, thinking explicitly false, completion
768 or 2500. Unknown top-level fields (including metadata, tools and completion
aliases) fail closed. This is conservative reservation, not billed usage.
Completion is added once, outside the max. Native IDs/rendering, assets/library
pins, v3 prompt/event/cache binding and model selection are unchanged.

### Installed-source evidence, not provider inference

Authorized readonly installed-source inspection established LiteLLM **1.105.1**.
`litellm/proxy/hooks/parallel_request_limiter_v3.py` uses
`DEFAULT_CHARS_PER_TOKEN = 4`; `_estimate_input_and_output_tokens` obtains
`len(get_str_from_messages(messages))`, then `max(1, total_chars // 4)` for
nonempty input. The helpers in
`litellm/litellm_core_utils/prompt_templates/common_utils.py` concatenate string
contents and optional search-results text. Our contract excludes search results,
list content and extra message fields. Roles/dict/list repr, JSON escaping,
response schema and temperature do not enter this installed input estimator.
`_get_explicit_output_cap` uses the explicit max_tokens; default-output heuristics
apply only without an explicit cap. Candidate multiplier is 1 under our
contract (n/best_of/config are unsupported). Integer floor division is rounded
UP locally and given 256 framing allowance; therefore the local defensive floor
also dominates the earlier fractional chars/4 statement. The native branch
retains the entire schema byte bound and separate framing allowance.

The v3 TPM pre-call primitive atomically checks **current + estimate > limit**,
then reserves the estimate. Reserved scopes settle by **actual - reserved** on
success; failure without partial usage refunds the reservation, recovered partial
usage is settled, with release-once guards. SPI deliberately does **not** emulate
these refunds: durable integer charges never decrease, actual usage only adjusts
upward, old rows survive restart, completion+61 remains the retention policy.
Installed-source private evidence is `/tmp/spi-proxy-source-private.txt` (0600),
SHA256 `709f985be633fa5fd1fac035a2bab92bd11920137612c68a9cedc1ffb7041c7f`.
Only library limiter/text-estimator source and version were read; no runtime
config, environment, API keys, provider request or inference was involved.
A remapped remote alias/template or different proxy version still needs operator
revalidation; this source proof cannot guarantee an unrelated remote deployment.

### Raw bound and analysis probes

Before trimming, schema serialization or BPE, the counter validates the public
contract and walks raw supported request fields with a 512KiB work bound. Each
string first has a character-length guard before bounded UTF-8 encoding; JSON
escaping/container overhead and schema are charged too. It never uses trimmed
rendering for the proxy floor. Oversized valid inputs return integer **30001**,
not an exception masked by a broad catch: Model.call rejects before ledger/HTTP,
while analysis budget probes may proceed to the existing explicit excerpt
fallback. Contracts and invalid assets still fail closed. Model.payload retains
its existing evidence-to-message serialization; the bound is on counter input,
not a new evidence ingestion policy. The new 120-long-report analysis regression
starts above 512KiB and reaches bounded excerpts without losing candidate numbers,
artifact IDs, references or mutating the original/private bundle. Matching batch
and nominee grouping remain unchanged.

Review counterexample, system `s`, raw user 100000 spaces + `x`, empty schema,
max_tokens=2500: new **27757**, installed proxy **27500**, historical fractional
proxy **27500.5** (previous native-only reservation 2777).
Compressible non-whitespace, Unicode/escaped JSON, ceil boundaries, both completion
caps, giant whitespace (no BPE/HTTP), unsupported metadata/contracts and schema
bound regressions are included.

### Refreshed seven historical reservations (private payload pipes only)

Existing historical reference CPU-tokenizer oracle evidence is retained; no new
reference/model baseline or inference was performed for this correction. Actual
Model.analyze payloads were reconstructed readonly and passed to the rebuilt
local image by pipe. Local prompt count/render hashes remained equal to the
historical oracle, and the native encoding code/pins are unchanged. Token-ID
oracle equality is the earlier seven-case evidence, not a newly claimed remote
ID comparison. This rerun independently checks both reservation branches and
reference prompt+completion for every row.

| Case | New reservation / native+schema+completion | Installed proxy incl. completion | Defensive proxy incl. completion | Reference prompt+completion | Byte-bound | Savings |
|---|---:|---:|---:|---:|---:|---:|
| e712 | 9315 | 6530 | 6787 | 7866 | 20075 | 53.6% |
| de23 | 10999 | 7364 | 7620 | 9550 | 23405 | 53.0% |
| 1cbe | 12023 | 8459 | 8716 | 10574 | 27787 | 56.7% |
| 0900 | 12433 | 8411 | 8668 | 10984 | 27594 | 54.9% |
| 613a | 13229 | 8819 | 9076 | 11780 | 29228 | 54.7% |
| 1482 | 10826 | 7157 | 7414 | 9377 | 22578 | 52.1% |
| 9b7 | 10335 | 6972 | 7229 | 8886 | 21840 | 52.7% |

Computed actual native synthetic charges are now **[5253,5253,5253]**, sum 15759,
versus proxy **[4997,4997,4997]** and byte-bound **[18299,18299,18299]**. Three
requests still fit 3RPM/30kTPM/parallel1. Fake-clock regressions cover proxy's
pre-call/settlement model, conservative local no-refund behavior, two floor-heavy
requests deferred until completion+61, three normal requests, restart/old integer
rows and upward usage. No avoidable pre-call TPM overlap occurs under that modeled
source accounting. This is a synthetic scheduling proof, not live throughput.

### Local verification

Production candidate (local only):
`d8de038102b9c5657ea90abec55021c9494c1c3ba2ab2cd0b1739b8f6c909372`.
Test-only Node/git image:
`87741b7b6a39b2ac77606ced0bd8f809297d77dd89df0d49b28356b28883fb5e`.

Full **211 tests OK, zero skips** in local mode, 71.181s, peak process RSS
279172KiB; full compatibility **211 OK, zero skips**, 34.780s, peak 289448KiB.
Both used network none, 384MiB/1CPU, readonly rootfs and source/full-repo/git-common
directory mounts, /tmp tmpfs, retained 24 shared Models. No OOM. Peaks are not
steady RSS. Existing test-only Node/git/legal overlay was reused, no apk install
or production Node/git added. Helpers **5 OK** on host with existing yaml/Helm;
JS **9 passed, zero skipped** in the test image; Helm lint/template and diff-check
pass. An initial helper attempt inside the minimal test image lacked PyYAML;
the host helper run is the successful complete result, not hidden as a pass.

Logs: `/tmp/spi-proxy-local-qwen-v1.log`, `/tmp/spi-proxy-byte-bound-v1.log`,
`/tmp/spi-proxy-helper.log`, `/tmp/spi-proxy-js.log`, `/tmp/spi-proxy-helm.log`,
`/tmp/spi-proxy-template.yaml`, `/tmp/spi-proxy-seven.log`,
`/tmp/spi-proxy-safe-summary.log`. Build inputs remain the existing preloaded,
pinned assets, without downloads/push. Default stays OFF. No job selection,
retry/revival, queue mutation, deployment, image/git push, new keys/fees, quota or
resource change. Live card acceptance is not claimed; dead-job retry requires
separate explicit authorization and independent review of this source fix.
