# SPI token admission

## Live receipt — 2026-11-06

Reviewed c2d9f57 + 8b933d9 rebased to bd41901 + **48b8161** and deployed
through the SPI application's ordinary automatic Recreate rollout at 15:52:51Z.
Argo readback: Synced / Healthy. No image build: the existing pinned Python
3.13 base and ConfigMap remain in use. Runtime file hashes match the ConfigMap;
all normalized source files match (Helm final-newline normalization required).
Actual Model payload/reservation/call/match/analyze and Store reserve_llm/finish_llm
methods and service Store injection were read back. Replicas, complete container
spec, volumes/PVC and strategy are unchanged. Startup recovered one processing job.

Fresh SQLite backup API snapshot before push: header valid, integrity ok, no FK
violations; SHA256 `6d84865261d3415ddd99844e039d22343737739606bfda4f92e2ba47ea6a6d58`.
315 original IDs/creation timestamps survive; all 119 cancelled whole rows remain
identical. Baseline outbox 68 applied / 7 pending, unchanged at observation end.
Private observations are outside git, mode 0600 in a 0700 directory.

**Acceptance PENDING**, not complete. Bounded natural observation ran
15:53:58Z–16:38:59Z (45 minutes plus snapshot completion overhead), 45 samples:
33 completed adaptive batch reviews / 346 candidate reviews across seven jobs;
four jobs naturally completed match+collect and reached stage 2. Zero new complete
jobs, analysis reports or primary publications. Final counts: 119 cancelled,
173 complete, 2 dry_run, 1 processing, 15 queued, 6 retry (one new natural job).
207 same-signature v2 prefix comparisons found no discarded completed reviews.
35 fresh log deferrals were LLM_ADMISSION_DEFERRED; zero fresh HTTP429, invalid
output-length, ordinary oversize or checkpoint errors. Retained jobs.error 429
while processing is historical, not a new provider failure. No generation probes.

Stage-2 requests reconstructed locally with transport intercepted before admission
reserve 28332 / 28811 / 28931 / 28839 tokens including 2500 output. They fit, but
were not admitted in this window: older due matching jobs won created,id claim
order and consumed near-full capacity. Repeated analysis waits occurred while
28080–29929 charges remained held. This is observed head-of-line backlog/claim
competition, not proof of infinite starvation by small requests: matching also
reserves near 30k and its finite snapshot work continues. No fairness guarantee is
claimed. At least 33 successful natural model calls are proven by saved reviews;
19 distinct completion expiries were sampled. Six active-to-finished samples give
16.93–100.63-second durations assuming the source's 600-second request timeout;
these are not complete per-request telemetry. Sampled integer charges 9739–29972
obeyed 3 RPM / 30000 TPM / parallel1. Actual provider usage is not separately
persisted; ledger charges are max(reservation, actual), never refunded, and are
not claimed as exact usage. The prior offline 7866–11780 actual-token measurements
are historical reconstruction, not new live analysis usage.

Exact original cards remain pending, all queued stage0 / attempt0:

| Card | Exact episode | Jobs |
|---|---|---|
| Resolved KubeDeploymentReplicasMismatch, uptake-kuma, original 17:21 MSK | `83bb101278aba11036f0ce7841eabaeb9ebc00339cd667da626c9beee8e41700` | firing `305b227cdc96…`; resolved `8c6af704b3fd…` |
| Firing SocratContainerRestartsFrequent, 17:28 MSK | `b5a10f46b0a2ce6ebb6429d78cc9cb13e42f0a562f6b39abc181c2d51a7cae0c` | `08ba1f0938dd…` |
| SPI triage queue is stale, 17:45 MSK | `b201c71c8b2bce1305233bfa7e47cacae545f2435fe6d644fd1df9bdf74cfb31` | `998bcead1720…` |

Each native receipt has two copies; event receipts are two per event (uptake has
both firing and resolved, four total). No target outbox/primary exists yet, so
there is no exact GitHub narrative/canonical file URL+Reader SHA or Telegram
applied acknowledgement 2/2 to confirm. No substitute #38 receipt is accepted.
Remaining step is natural admission/analysis/publication and exact episode/revision
link acknowledgement. Existing valid stale alert remains active and unmodified.
Observation stopped at the stated boundary; no continued monitoring is promised.

Validation rerun: 169 SPI tests, 5 chart/helper tests, 9 JS ingress tests, Helm lint
and template, diff whitespace check. No forced claims, requeues, manual retries,
lease/budget resets, queue clearing, provider/key/payment/limit/network/IAM changes
or unrelated application sync. Do not roll back to a binary interpreting v2 as
fixed-12. The following sections describe the validated deployment-specific
accounting assumptions, not a universal tokenizer guarantee.

The existing Model constructor accepts `store=`. Service passes its shared PVC
Store. Standalone callers lazily open `SPI_DATABASE` (default `/data/spi.sqlite`).
Every user of this SPI key must share that ledger; unrelated keys are not audited.
The alias/key, 3 RPM, 30000 TPM and single parallel request remain unchanged.
No new background threads, sleeps, inference endpoints or provider fallback.

## Counting and bounds

`qwen-byte-bound-v1` reserves **NFC UTF-8 bytes of the actual SYSTEM and user
message strings + UTF-8 bytes of response_format + 256 framing + max_tokens**.
HTTP JSON escaping, transport keys and duplicate escaped representations are not
model tokens. Evidence JSON inside the user string is real content and is counted.
No runtime tokenizer dependency, pip installation or internet fetch is introduced.

Validated read-only against deployed RedHatAI/Qwen3.8-27B-INT4 revision
`91bd022d5b49442a868bc35008f6c21e1860edfa`: tokenizer.json uses NFC followed by
ByteLevel BPE. Pre-merge normalized byte count bounds content tokens. Its installed
text-only two-message template with enable_thinking=false adds 99 rendered bytes;
256 is a doubled, rounded-up byte bound. Strict schema is additionally charged at
full byte size although guided decoding does not insert it into the chat template.
The method rejects a different alias, roles, tools or thinking settings. This is
not a guarantee for future alias/provider/template changes: revalidate before any
such rollout. The fixed source alias alone cannot detect an operator remapping it.

LiteLLM 1.105.1 authenticated `/utils/token_counter` was inspected and tested with
benign local text using the existing scoped key. It resolves this alias to
qwen3.8-27b but reports `openai_tokenizer`, not the actual Qwen tokenizer. Its schema
does not accept response_format. Therefore it is NOT used in production and an
auth outage/counter failure cannot silently change accounting. Installed v3 limiter
source estimates input from message chars/4 and reserves explicit max_tokens;
our byte bound dominates that heuristic as well as the validated provider BPE.
No claim that the generic counter equals provider usage is made; no paid call was
made. There is no count cache or new ledger data format/version to migrate.

Analysis first tries full context, then 600-byte preliminary candidate/report
scalar excerpts, then explicit 1200/600/300-byte scalar excerpts across context
until the complete request fits. Matching also bounds event scalar text. Lists,
dictionary keys, candidate numbers, artifact IDs, references, missing/truncation
and limitation metadata survive. Each excerpt has original bytes, digest,
unreviewed byte count and a limitation. Full originals in Store/RustFS are not
modified. Model serialization now redacts without core.clean's silent string/list
caps. Irreducible metadata fails visibly as LLM_CONTEXT_METADATA_TOO_LARGE; it is
not called ordinary historic oversize. All seven specified historic samples fit,
with actual offline Qwen prompt+completion counts 7866–11780 and conservative
reservations 20075–29228. This costs throughput/context quality, not extra spend;
it is intentionally less efficient than packaging a reviewed exact tokenizer.

Match output is 768 tokens with compact strict JSON and a 120-word reason request;
report output stays 2500. Truncation, invalid JSON and invalid evidence references
are visible finite failures, never silent success. Local fake responses test
contracts, not actual model quality or actual production token counts.

Matching uses deterministic labeled excerpts (1600 UTF-8 bytes title/body,
400 bytes each comment); the original already-bounded GitHub snapshot is saved
in the checkpoint. It is not claimed to be the full original issue. Up to 12
candidates are added while the complete request fits; all 120 allowed candidates
must be reviewed. Unexpectedly enormous alert/metadata or an impossible analysis
request fails visibly (`LLM_REQUEST_TOO_LARGE` / `LLM_SINGLE_CANDIDATE_TOO_LARGE`),
not an endless admission loop. Analysis evidence is not silently clipped to fit;
operators must explicitly resolve oversized evidence/configuration.

## Durable window and migration

SQLite `BEGIN IMMEDIATE` atomically reserves tokens, RPM and parallel capacity.
Reservations remain charged until 61 seconds **after completion**, deliberately
stricter than a 60-second rolling start window and conservative for the observed
60-second reset. Actual usage can raise, never refund, the reservation. A crash
holds capacity for request timeout +61 seconds. No credentials/payloads enter the
ledger. The checkpoint contains evidence, as the existing job result already does.

Admission never sleeps holding the stage: typed `LLM_ADMISSION_DEFERRED` uses the
next ledger deadline +1–3 seconds jitter and unlimited explicit LLM patience.
429 with valid Retry-After/reset uses that hint+jitter, not claims-based escalation;
unknown quota/timeouts retain conservative patient policy. A 429 alone is not a
claim about upstream cause. Only numeric token/request remaining/reset and retry
hints are allowlisted; no error bodies are persisted.

Version-2 progress binds the full snapshot signature, exact original batch IDs
and content digests; old fixed-12 decisions migrate only for an identical full
signature. Changed snapshots safely restart matching. Pairwise winner reduction
is budgeted, validated and checkpointed; it never skips a nominee. Existing
pre-primary snapshot revalidation stays in place. Completed identical reviews
survive deferral/restart and storage toggles.

## Local validation / rollout gate

Run `python3 -m unittest discover -s tests/spi_triage -q`, related SPI chart tests,
`helm lint charts/spi-triage`, `helm template`, and `git diff --check`.
Synthetic tests cover ledger restart/expiry, limits, whole-payload/schema/output
accounting, 120 candidates, labeled oversized excerpts, migration, final selection
resume and finite invalid outputs. Existing tests cover 20+ LLM deferrals followed
by storage/GitHub publication and exact Telegram receipt links.

Before any separately authorized deployment: independently review code and
counting assumptions, normalize Helm ConfigMap block scalar/final newlines before
comparing runtime source (raw hashes alone are insufficient), back up the PVC,
retain the same PVC/database and sole Recreate worker. Tables are additive; do
not delete ledgers or reset/requeue jobs, especially the 119 cancelled tombstones.
Old binaries cannot consume v2 progress correctly, so rollback must retain new
checkpoints and not reinterpret them as old fixed-12 decisions. Observe the
original three user cards naturally; do not force selection or inject incidents.
The source review itself performed no rollout or inference; the separately authorized
live rollout and worker's actual natural inference are recorded above. No test
inference, credential change or forced job transition was performed.

## Completion-aware scheduler correction (reviewed and deployed3309f505)

Claims now prefer eligible stages in descending pipeline order: stage3 write,
stage2 analysis, stage1 collection, then stage0 new/partial matching. Within
one stage, natural `created,id` ordering is unchanged. Active processing leases
remain exclusive; no active HTTP request is preempted. Independent Telegram
outbox delivery is unchanged. Pending-age alerts still use original creation
age across all pending jobs, not the scheduler's effective due time.

Claim and durable dispatcher wake calculation share one policy. A live stage2
`retry` with exactly `LLM_ADMISSION_DEFERRED` may hold **only stage0** until its
existing jittered available time, if a known ledger expiry lies between failure
and that time and no more than four seconds before it. The hold must end within
664 seconds of failure (normal 600-second abandoned request + conservative61s
ledger retention + at most3s jitter). Expired ledger entries can bridge the
jitter interval but never extend that deadline. No available/attempt/lease,
checkpoint or result fields are rewritten to promote a job. Future wake times
include the hold, so an old due matcher does not produce repeated callbacks
while claim intentionally yields. Safe writes and collection remain eligible.

Unknown upstream429/hour backoff, dead/cancelled jobs, unmatched/stale ledger
entries, or deadlines outside this bound never hold matching. At the deadline,
due analysis wins by stage priority and re-evaluates normal 3 RPM /30000 TPM /
parallel1 admission; this does not bypass quotas. Abandoned reservations recover
through their existing expiry, not a reset. Very large/nonstandard timeouts or
clock discontinuities outside this normal wall-clock bound lose the hold rather
than freezing new work. This is completion preference, not universal fairness
under an unbounded stream of later-stage work. Publication still requires valid
model output, unchanged open-incident snapshot and successful storage/delivery;
fake progress tests do not prove any live card accepted or published.

Rollback: after fresh backup and reviewed fetch/rebase/deployment, reverting this
scheduler-only change restores created/id scheduling without database migration.
Retain the validated v2-capable token-admission runtime; never roll back to a
fixed-12 matcher that reinterprets v2 checkpoints. No deployment, queue mutation,
paid model call or endpoint probe accompanies this source-only correction.


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
