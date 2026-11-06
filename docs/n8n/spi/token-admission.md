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
