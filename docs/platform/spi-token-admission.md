---
title: SPI token admission live receipt
---

## 6 November 2026 — acceptance pending

SPI runtime revision **48b8161** (reviewed c2d9f57 + 8b933d9, rebased as
bd41901 + 48b8161) rolled out normally at 15:52:51 UTC. SPI Argo was Synced /
Healthy. Existing pinned Python image, ConfigMap delivery, Recreate strategy,
replica count and PVC/container specification are unchanged. Runtime hashes match
ConfigMap and normalized source; shared Store injection/admission methods verified.
No rebuild, provider/key/payment change or unrelated app sync.

Read the authoritative operational detail in
[the token admission runbook](https://github.com/alchemmist/homelab/blob/main/docs/n8n/spi/token-admission.md).
Its deployment-specific qwen-byte-bound-v1 uses NFC UTF-8 message bytes, schema,
256 framing bytes and full output reserve, validated against Qwen revision
91bd022d5b49442a868bc35008f6c21e1860edfa. It is not a generic tokenizer guarantee.
The conservative 3 RPM / 30000 TPM / parallel1 budget is unchanged.

A fresh consistent SQLite backup preceded push (integrity/FK/header valid).
All 315 original IDs/creation times and all 119 cancelled whole rows survived.

Natural observation **15:53:58–16:38:59 UTC**, then stopped: 33 saved batch
reviews / 346 candidate reviews, four jobs reached stage2 (match+collect), zero
new completed jobs/reports/publications. 35 fresh typed admission waits, zero new
HTTP429. Old retained error fields are not fresh errors. Checkpoint prefixes
survived 207 same-signature comparisons. Stage2 reservations 28332–28931 fit but
waited behind older matching work with near-full ledger holds; infinite small
request starvation is not demonstrated. Actual provider usage is not separately
persisted; charges are conservative reservations, not exact live usage.

The requested cards remain queued stage0 attempt0, **not completed**:

- Resolved uptake-kuma KubeDeploymentReplicasMismatch (original17:21MSK), episode
  `83bb101278aba11036f0ce7841eabaeb9ebc00339cd667da626c9beee8e41700`,
  firing job `305b227cdc96…`, resolved `8c6af704b3fd…`.
- Firing SocratContainerRestartsFrequent17:28MSK, episode
  `b5a10f46b0a2ce6ebb6429d78cc9cb13e42f0a562f6b39abc181c2d51a7cae0c`, job
  `08ba1f0938dd…`.
- SPI triage queue is stale17:45MSK, episode
  `b201c71c8b2bce1305233bfa7e47cacae545f2435fe6d644fd1df9bdf74cfb31`, job
  `998bcead1720…`.

All have two native card copies and exact event receipts. None has a primary or
link outbox yet: GitHub narrative, canonical file URL/Reader SHA and Telegram
applied2/2 are pending, not claimed using a different incident. The stale alert
was not muted or retuned. Remaining gate is natural analysis/publication followed
by exact episode/revision acknowledgements; no forced selection or resets.

Rerun:169 SPI,5 chart/helper,9 JS tests; Helm lint/template and whitespace checks
passed. Keep integer charges and v2 checkpoints; old fixed12 binaries must not
reinterpret v2. No continuing observation after this bounded window is implied.

### Completion-aware scheduling correction — source-only

The scoped correction prefers eligible stage3 writes, stage2 analysis, stage1
collection, then stage0 matching; ties retain natural created/id ordering.
Claim and dispatcher share effective eligibility/next-wake calculation. Only a
live stage2 retry with `LLM_ADMISSION_DEFERRED` and a matching known ledger
expiry may hold stage0 until its existing jittered due time (expiry to due at
most4s; failure to due at most664s). Expired ledger data cannot extend this
bound. Active requests are not preempted; safe writes/collection and independent
Telegram deliveries are not held. Unknown429/hour backoff, terminal jobs and
out-of-bound/stale deadlines do not freeze healthy new matching. Pending-age
alerts retain original semantics; no durable job deadlines/checkpoints change.

Normal admission remains 3 RPM/30000 TPM/parallel1 with qwen-byte-bound-v1,
256 framing and conservative61s completion retention. Abandoned active ledger
entries use normal expiry, including after restart. This is completion
preference, not a global starvation guarantee under infinite later-stage work.
Stable snapshots, valid analysis and successful publication remain prerequisites;
synthetic tests do not accept the user's three live cards. No paid calls, queue
changes, deployment or endpoint probes are part of this correction. See
`docs/n8n/spi/token-admission.md` for bounds and runbook. Rollback only this
scheduler delta on the v2-capable runtime; never reinterpret v2 checkpoints with
a fixed-12 matcher. Later rollout requires review, fresh backup and fetch/rebase.


## Completion-aware live rollout — 2026-11-06 (bounded, blocked acceptance)

Reviewed scheduler `3309f505` deployed through ordinary SPI autoSync/Recreate;
normalized ConfigMap matches source, pinned image/PVC/container specification
unchanged, GitOps Healthy. Shared priority is write > analyze > collect > match;
only proven local stage2 admission retry holds stage0, bounded664s, expiry
proximity4s. Independent Telegram delivery and 3RPM/30000TPM/parallel1 remain.
The pre-rollout active reservation expired naturally at17:05:18Z; restart quiet
period was conservative crash recovery, not provider429 or scheduler starvation.

Finished natural observation16:54:48–17:39:48Z. One genuine end-to-end report:
https://github.com/alchemmist/homelab/issues/72#issuecomment-6690743660
(job20e7; **not** any requested card). All13 permanent canonical manifest/artifact
links checked in actual GitHub body; scoped Reader matched exact original bytes,
sizes and SHA against stored verified receipts. Telegram revision1 applied the
exact primary with verified expected2/observed2. This is publication proof,
not merely batch counts. Reservations are not exact provider token usage.

All four prepared jobs a16a/c93b/fa45/a92e naturally obtained analysis and reached
stage3 with reports, then publication's mandatory global open-snapshot fence
returned OPEN_SPI_CHANGED, resetting to stage0 and deleting all6 cached reviews
of61 candidates each. First successful publication changed the open snapshot;
this is a real throughput/cache-invalidation limitation, not generic queue wait.
The four exact requested event jobs305b/8c6a/08ba/998b remained queued stage0,
attempt0, with no primary; requested three cards remain unaccepted. One publish
INVALID_UPSTREAM_JSON was a finite upstream JSON parse failure, not invalid model
output; endpoint/status/content-type are not retained, so exact source unknown.

No live fix or weakened fence. Source follow-up should retain validated progress
at reset, reuse only exact candidate-ID/content + event/prompt-contract-bound
unchanged batch proofs on a refreshed snapshot, invalidate changed/new/closed
batches and final selection, and check signature cheaply before expensive analysis.
Preserve primary-intent/S3 reconciliation and post-upload publication fences.
This is a proposal requiring independent review, not deployed behavior.

Fresh SQLite API backup before push passed header/integrity/FK/SHA checks.
All316 original IDs/creation times and terminal results/intents preserved;
119 cancelled whole rows identical. One old completed job received a natural
duplicate delivery (only updated/deliveries changed). Outbox68->69 applied,
7 pending unchanged. No forced claims/reset/revival/probe or unrelated changes.
Observation ended; no ongoing monitoring promised. Rollback remains v2-capable.

## Local implementation: snapshot review reuse (not deployed)

Safe open-snapshot churn now retains the publication backend and matching proofs.
New proofs are explicitly v3 and bind the immutable event digest, actual matching
payload (including model/system/schema), excerpt policy, original full snapshot
and exact batch identities/content digests. The original snapshot/proofs are
validated before transferring only unchanged whole batches. Inserts/deletes/order
changes do not regroup proven batches; uncovered current candidates are reviewed
in adaptive batches of at most 12, with the existing 120-candidate ceiling.
Pairwise selection is invalidated on any full-signature change; same-signature
selection resumes from validated nominee-bound comparison history.

`match_progress_v3` is separate from old progress. Its checkpoint is also stored
transactionally in additive SQLite `match_review_v3`, so an older worker resetting
`jobs.result` cannot erase or reinterpret v3 proofs. Old v1/v2 caches have no
explicit event/prompt/model provenance; this implementation conservatively
re-reviews them rather than manufacturing a binding, even on an equal signature.
No backup caches are restored to jobs. Unknown contract changes re-review.

Before analysis, `GitHub.open_signature()` uses exactly `issues()` (the full
snapshot's universe/filter/order), without fetching comments. A stale snapshot
consumes no analysis call and invalidates safely. Existing pre-primary and
post-upload full fences and intent-first reconciliation remain mandatory.
Legacy artifact checkpoints or ambiguous primary intents are never cleared.
After an S3 upload, safe invalidation moves original evidence and exact storage
binding/verified receipts into `snapshot_audit`; new collection gets a fresh
active binding, never the previous bundle's receipts. Immutable objects are not
rewritten or adopted as new evidence. Public Reader URLs remain `/` + object key.

Only `OPEN_SPI_CHANGED` after a safe stage-zero reset with no intent receives
15–20 second jittered patient retries. Attempts and existing finite failure
budgets are not reset. Unsafe intents, unknown HTTP/JSON/auth/evidence errors and
`WRITE_NEEDS_REVIEW` retain finite/visible handling; LLM admission, claims,
callback scheduling, exclusive leases and token/parallel limits are unchanged.

This is source-only readiness, not live acceptance. The observed 24 reviews/244
candidate checks lost across four jobs are proven; which live candidate contents
changed is unknown (the prior probe timed out). Fake tests cover four prepared
61-issue/six-batch jobs, exact batch reuse, mutations/closures, early fencing,
20 safe deferrals, rollback retention, selection restart, post-upload audit,
and eventual exact-primary publication with two-recipient applied outbox.
The three requested live cards remain unaccepted; no new deployment, inference,
queue mutation, backup restoration or observation window accompanies this change.

### Durable late-snapshot replacement bound

A job has exactly three expensive snapshot generations: the initial generation
and at most two replacements. A stale post-analysis/pre-upload or post-upload
snapshot spends one replacement in the same SQLite transaction as the safe
stage-zero reset and audit retention. The third late invalidation does not reset:
it terminates as `dead` / `WRITE_NEEDS_REVIEW`, preserving the current report,
evidence, backend, active storage binding, verified receipts and previous audit.
There is no fourth generation. At most two historical full bundles plus the
current bundle exist in this job's logical trace; existing overbound/unknown
traces are retained and fail closed, never truncated. Candidate inputs remain
bounded by 120 candidates and twelve per matching batch, unchanged.

The additive `snapshot_budget` ledger is authoritative across restarts/reclaims
and jobs.result replacement. It keeps a bounded independent retained copy of the
current result (including the same at-most-two historical bundles), not another
append-only history. Replacing result with an old marker-less reset causes
operator review before any model/upload; operators must inspect both the job and
ledger retained JSON, not discard the ledger or reset counters to resume work.
Do not manually select replacement jobs, cancel queue entries, or clear receipts.
Stage-zero repeated invalidation does not spend twice. Transaction rollback
cannot commit the budget without the reset or vice versa.

Cheap pre-analysis signature fences may remain patient with zero analysis calls;
this is not permission for infinite new analysis or S3 generations. Primary intent
reconciliation remains ahead of freshness fences; ambiguous/unsafe writes remain
finite and are not reclassified as patient. Both full publication freshness fences
remain. Existing failure counts, 3 RPM / 30000 TPM / parallel-one admission,
Root-plus-key Reader URLs and Telegram delivery semantics are unchanged. This is
source assurance only, not acceptance of the three real user cards or rollout
authorization.


## Snapshot-review reuse rollout — 6 November 2026

Reviewed source `f6f8f101` + `0d27df3`, rebased release `ac6efc01`, deployed through ordinary SPI autoSync/Recreate. Live normalized ConfigMap matched all source files; pinned Python image, container/volume/PVC spec, provider/accounting and 3 RPM / 30000 TPM / one parallel unchanged. Additive `match_review_v3` and `snapshot_budget` tables exist. Legacy reviews deliberately require one fresh v3 review; never restore caches from backups. Late generations remain initial plus two replacements; retain independent proofs/budget on rollback.

Live acceptance is **BLOCKED, not complete**. Bounded observer sampled 18:08:38–18:36:23Z (28 consistent snapshots), then stopped when fresh matching `INVALID_MATCH_PROGRESS` occurred at 18:35:22Z on `a16a0dfcf743…`. One durable v3 batch (12 IDs, original snapshot61) had been saved. Its snapshot/content digests validate; a separate read-only native matcher replay with a fresh62-unique-candidate snapshot reached the deliberately disabled model-call boundary without error. The original failing current snapshot is not persisted: exact cause and cross-snapshot live reuse remain unproved, not established cache corruption. No automatic source repair, cache reset, rollback or queue mutation was performed. Finite failure count for that job was3 (baseline2). Natural worker activity continues independently; this acceptance observer has ended.

Another natural job `45b8168e0cf2…` completed stage4 after a publication-stage `UPSTREAM_NETWORK_ERROR` at18:23:25Z (finite count1, sampled retry had no primary intent), with normal `publication_ok` at18:33:13Z. This is not model-output failure or proof for the requested cards. No endpoint diagnosis or infrastructure repair was attempted. Reserved tokens are not exact provider usage.

Exact requested episodes remain unaccepted, all original jobs queued/stage0/attempt0 at final consistent capture: resolved KubeDeploymentReplicasMismatch episode `83bb101278aba11036f0ce7841eabaeb9ebc00339cd667da626c9beee8e41700` (firing `305b227cdc96…`, resolved `8c6af704b3fd…`); firing SocratContainerRestartsFrequent episode `b5a10f46b0a2ce6ebb6429d78cc9cb13e42f0a562f6b39abc181c2d51a7cae0c` (`08ba1f0938dd…`); stale SPI episode `b201c71c8b2bce1305233bfa7e47cacae545f2435fe6d644fd1df9bdf74cfb31` (`998bcead1720…`). None has an accepted primary/Reader/applied two-copy Telegram proof. Older #72 evidence must not substitute for them. All318 baseline IDs/creation times,119 cancelled whole rows and original terminal results/intents were preserved. No ongoing observation or eventual completion is promised.


## Source-only snapshot consistency correction (2026-11-06)

Live acceptance remains BLOCKED: the three requested cards are unaccepted. The
18:35:22 INVALID_MATCH_PROGRESS historical current input was not retained. The
saved a16a v3 proof and later 62-unique replay were valid; durable corruption is
not established. The unrelated 18:33 publication is not acceptance evidence.

A fake transport reproduces a precise *possible* cause against clean 72ebc5e:
61 created-desc issues, append a new issue after page1/per_page20, then continue
offset pagination: 62 rows but only61 unique identities. The actual baseline
matcher raises INVALID_MATCH_PROGRESS before checking the valid old proof and
before inference. This proves a source defect, **not** the historical cause.

The local correction requests created-ascending pages, canonicalizes by issue
number, rejects duplicates (never dedupes), and reads the same filtered open SPI
universe again around comment collection. Any full metadata change or duplicate
is GITHUB_SNAPSHOT_UNSTABLE: one acquisition attempt, patient15–18s deferral,
zero model calls, no finite failure charge, retained v3 proof/budget. Cheap
open_signature uses the same issues/filter/order and two metadata reads, no
comments. Each issues pass retains the existing100-page bound; candidate ceiling
remains120. Unsupported identities/schema, malformed HTTP/JSON/network errors
and genuine bad durable proofs remain finite. No loop or conditional GitHub PATCH
was added. Consecutive equal reads are an observational consistency fence, not a
transactional GitHub snapshot; changes after the last read remain guarded by the
existing pre-analysis/pre-primary/post-upload fences.

Matcher rejections now emit sanitized diagnostic JSON with fixed reason enums,
count/uniqueCount/identity digest only. CURRENT_INVALID_ID and CURRENT_DUPLICATE
are separate from ORIGINAL_SIGNATURE, BATCH_DIGEST, OVERLAP, DECISION, SELECTION.
No event/issue/comment body, raw identity, credential, URL or exception text is
logged. A duplicate supplied directly to matching is also patient instability;
invalid IDs remain finite. Preserve proofs for diagnosis; do not reset jobs,
leases, budget, counters or restore caches to work around these errors.

Local fake regressions cover insert/close/reopen/reorder for61/62 rows, exact
baseline reproduction, current duplicate versus valid retained proof, metadata
change around comments, malformed response, zero-model engine deferral and
15–18s due-delay without failure consumption. Existing v3 content/ownership,
same-signature selection, changed-signature unchanged-batch reuse, v1/v2
rereview, independent replacement cap/audit and publication tests remain green.
No live probes, inference, queue writes, deployment or push were performed.


## Snapshot consistency live receipt — 2026-11-06

Approved source **598f9fa6b1fb73490e0440aaabbaee255952a4c5** deployed through ordinary
SPI autoSync/Recreate; worker started18:54:20Z, all13 normalized runtime files
match source, unchanged pinned container/PVC spec. 198 SPI+5 helper+9 JS tests,
Helm lint/template and diff checks passed. No source follow-up or synthetic calls.

**Acceptance PENDING.** Original bounded natural window18:54:32–20:09:33Z,
74 private consistent samples; observer ended, no continuing monitoring promised.
16 new batch proofs/158 candidate reviews (12.8 batches/hour), two unrelated
publications19:26:04Z/19:47:52Z (1.6 completions/hour), complete175→177.
All four original target jobs still queued/stage0/attempt0; no target publication,
Reader file proof or independent Telegram2/2 publication acknowledgement exists.
Do not substitute unrelated publications or rerun accepted fixtures as proof.

Exact pending episodes: resolved KubeDeploymentReplicasMismatch uptake-kuma
`83bb101278aba11036f0ce7841eabaeb9ebc00339cd667da626c9beee8e41700`
(firing305b227c…/resolved8c6af704…), firing SocratContainerRestartsFrequent
`b5a10f46b0a2ce6ebb6429d78cc9cb13e42f0a562f6b39abc181c2d51a7cae0c`
(job08ba1f09…), stale SPI
`b201c71c8b2bce1305233bfa7e47cacae545f2435fe6d644fd1df9bdf74cfb31`
(job998bcead…). All still require natural match/collect/analyze/publish, exact
primary+public-origin artifact links, original Reader bytes/SHA and applied TG2/2.

Actual stored v3 same-signature prefix reuse and changed-signature unchanged
partitions were verified by IDs and content digests against current snapshots:
a16a retained3 partitions/35 IDs and c93 retained2/24 across changed signatures;
later same-signature extensions retained exact prefixes. a16a finished6 batch
reviews/63 candidates,4 positive nominees and3 final pairwise comparisons;
c93 finished6/62,0 nominees/0 comparisons. fa453 currently5 reviews/53 of63,
0 nominees/0 comparisons; a92 currently3/29 of63,0/0. N positive nominees may
require N−1 pairwise calls even when a combined payload might fit. Throughput is
not a target ETA:23 queued and3 retry remain, signatures and network vary.

19 admission deferrals, one finite match UPSTREAM_TIMEOUT19:09:12Z and one
patient GITHUB_SNAPSHOT_UNSTABLE19:27:49Z occurred, with subsequent progress.
No new INVALID_MATCH_PROGRESS or live cap exhaustion observed. Snapshot HTTP
count/duration and instability subtype not available in existing telemetry.
Historical18:35 cause remains UNKNOWN; local pagination reproduction is not
proof of that historic cause. Equal double observations are not transactional.

Fresh private SQLite backup API snapshots passed header/integrity/FK checks.
All323 baseline IDs/creation preserved; all119 cancelled whole rows identical.
Terminal state/stage/result/intent preserved; one complete row naturally got a
duplicate delivery14→15 and updated time. Outbox applied70→72/pending7 unchanged;
v3 rows2→4, snapshot_budget0→0. No manual claims/requeue/restore/reset, receipt
reassociation, quota/identity/network changes or model probes. Reservations are
not exact usage. 3RPM/30000TPM/parallel1, durable three-generation bound and
664-second scheduling guard retained. Further natural observation is a parent
scheduling decision, not an ongoing observer from this completed window.

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

### GitHub read timeout patience (source-only correction)

Only a typed `UPSTREAM_TIMEOUT` from semantic `GitHub.request("GET", ...)`
becomes `GITHUB_READ_TIMEOUT`: existing durable patient deferral, 60 seconds
plus 1–3 seconds jitter, independent of historical claims. Total attempts,
unsafe-failure allowance, cached results/v3 proofs, snapshot replacement budget
and fresh-admission ledger are not reset. Snapshot two-pass coherence, outer
request deadline, exclusive claims and leases remain unchanged. Canonical enum
only is persisted/audited; no raw exception, path or token is logged.

POST/PATCH/PUT/DELETE timeouts retain finite failures and durable ambiguous-write
intent/reconciliation fences; this does not authorize write replay or intent
clearing. Auth, JSON/schema/reference failures, unknown network errors and generic
5xx/429 are not newly patient. Existing snapshot-instability delays are unchanged.

Historical 998b bare timeout is consistent with early GitHub signature reads;
the exact historical endpoint/page is unknown, not proven. Model POST timeouts
remain `LLM_UPSTREAM_TIMEOUT`. User authorization is for future audited retries
of 08ba and 998b only after reviewed correction; this source slice performs no
retry, deployment or live write. No cancelled/completed/other dead-job revival,
queue cleanup or counter reset is authorized here.

### Private pull preparation, 2026-11-07

Private Harbor target and actual socrat-1 pull/startup have passed. The SPI-only
pull secret is imagePullSecrets-only; a 90-day pull-only robot must be privately
rotated. Production local-counter activation and two exact-job operator retry
remain separate reviewed actions, not done. See `services/spi-tokenizer/README.md`
for pre-push/pre-retry bounded private SQLite backup and immutable retry audit.
Scanner inventory: **9 TOTAL: 5 High, 3 Medium, 1 Low**, not nine High or zero
vulnerabilities. Independent review found inherited identical pip-vendored
msgpack (pure Python, no C extension), pkg_resources and urllib3; none is imported
by SPI runtime. The pinned original base has identical pip, ensurepip and /usr/lib
hashes. Five High findings have explicit current-runtime trigger exclusions, not
a blanket waiver. zlib is inherited and usable by Python; absent GDAL/infback9
artifacts provide strong advisory-misattribution evidence, but Medium attribution
uncertainty is retained (not universally N/A). No demonstrated newly introduced/
reachable High in current SPI; adding imports or package-install paths requires
re-review. No pin suppression, upgrade or zero-CVE claim is implied.

Source-only helper correction: private full-row manifest binding and end-to-end
CLI backup deadline are prepared, not activated. Original auth time is unknown/
null; only two full IDs 08ba…/998b… are authorized after independent review. See
tokenizer README for canonical manifest, failure cleanup and backup limitations.
