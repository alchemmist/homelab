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
