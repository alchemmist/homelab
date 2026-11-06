# SPI token admission (source-only; not a deployment receipt)

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
No live writes, key changes, paid inference or rollout were performed for this fix.
