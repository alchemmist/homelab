# SPI token admission (source-only; not a deployment receipt)

The existing Model constructor accepts `store=`. Service passes its shared PVC
Store. Standalone callers lazily open `SPI_DATABASE` (default `/data/spi.sqlite`).
Every user of this SPI key must share that ledger; unrelated keys are not audited.
The alias/key, 3 RPM, 30000 TPM and single parallel request remain unchanged.
No new background threads, sleeps, inference endpoints or provider fallback.

## Counting and bounds

No tokenizer is fetched at runtime. Fallback reservation is the **entire actual
`json.dumps(payload)` UTF-8 byte length + 2048 framing tokens + max_tokens**.
It counts system, escaped nested user JSON, JSON schema and serialized overhead.
This is deliberately much more conservative than chars/4: byte-level BPE starts
with byte units and merges cannot increase their number. The 2048 framing margin
assumes the deployed Qwen chat/schema template adds no more than that many tokens;
it is not a measured tokenizer count. Verify that assumption and tokenizer family
against the deployed alias before rollout. A model/template change requires review.
This is not an unconditional bound for arbitrary proprietary tokenizers/templates.

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
No live writes, key changes, paid inference or rollout were performed for this fix.
