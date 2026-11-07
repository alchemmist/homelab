# Source-only experimental local counter — CODE_READY, not activated

Do not activate this image as part of this source phase. All remaining source validation gates are complete; see VALIDATION.md for the actual seven-row installed-reference oracle, zero-skip 206-test local-mode run at 384Mi/1CPU, computed-cost durable-clock proof and legal provenance. Peak process RSS 277800 KiB with 24 Models sharing one native counter. Do not increase resources. Final pairwise selection and live three-card acceptance are unchanged.

Build locally: `sh services/spi-tokenizer/build-local.sh /tmp/spi-tokenizer-assets.YxjQRa`. No push is performed. Base Python 3.13 Alpine digest is pinned in Dockerfile. Wheel URL is pinned in wheel-url.txt; wheel SHA256 is checked before no-index/no-deps installation. Asset revision: https://huggingface.co/RedHatAI/Qwen3.8-27B-INT4/resolve/91bd022d5b49442a868bc35008f6c21e1860edfa/ . Asset hashes are in local_token_counter.py and checked during build and runtime. Build requires pre-fetched assets, not runtime internet. Assets and wheel are not tracked.

Model card attribution is retained in MODEL-README.md and image README.md; it declares Apache-2.0. Official Apache text from https://www.apache.org/licenses/LICENSE-2.0.txt has SHA256 cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30. Wheel inspection alone is not licensing proof. Matching immutable upstream v0.22.2 commit LICENSE and Rust LICENSE pointer are preserved under legal/ and copied to the image; the recursive upstream tree contains no NOTICE. See legal/PROVENANCE.md for exact URLs/hashes and limited internal-image attribution scope, not certification of all transitives.

Default `tokenAccountingMode: byte-bound-v1` remains compatible. Experimental `local-qwen-v1` is explicit, fail-closed, offline and validates before store recovery. No chart activation is authorized. Remote alias remapping requires operator revalidation of the pinned tokenizer/template; local validation cannot verify remote configuration. Reservation uses max(rendered prompt tokens + full response-format UTF-8 bytes + 256, ceil(raw HTTP message characters / 4) + 256) + explicit completion cap (native-qwen-plus-proxy-floor-v1; installed LiteLLM 1.105.1 source); this is reservation utilization, NOT exact provider usage. Existing durable charges remain untouched and actual-usage upward adjustment remains unchanged. Rollback selects byte-bound-v1 and original pinned base image; retain cache, database and budget ledger without refunds.

## Native lifetime and filesystem contract

One process-global native tokenizer is initialized under a lock on first local-mode Model. Every subsequent constructor re-streams all asset/library hashes before reuse; missing files and drift still fail closed. Root path, asset pins and full installed-file manifest must match the first contract. A different valid contract requires process restart: there is no keyed cache, eviction or second native lifetime. Initialization and encode are serialized; the application creates no counter threads/queues. TOKENIZERS_PARALLELISM=false and RAYON_NUM_THREADS=1 are retained. Request bodies, rendered strings and encodings are call-local, never cached. 24 simultaneously retained Models and largest allowed ASCII input were exercised in the same process as all 203 discovered SPI tests, including SQLite, evidence bundles and snapshot-v3 code.

Assets, manifest, installed library and their parent directories must be immutable/read-only for the entire process lifetime. Verification is streamed with hashlib.file_digest. This assumes trusted image construction and no privileged concurrent filesystem mutation between verification and native load; hashes do not defend against a writable manifest plus writable library. Do not mutate the native tokenizer returned by the inspection property. No runtime asset updates are supported.

Rebuild input is a strict preloaded context, **not** a claim that the private directory is universally available. Runtime assets and wheel are checked against fixed hashes; source URL and revision above identify the public provenance. No downloads, weights or assets are placed in Git or ConfigMaps.

Completed source gates and pins: VALIDATION.md. The build intentionally requires a strictly verified preloaded context; public source URLs are recorded, not a claim of a universal downloader. Node/git exist only in ephemeral validation images. No activation, production acceptance or live throughput claim.

P1 proxy-floor correction: see the final section of VALIDATION.md for the installed-source rounding/check/refund proof, raw-input bound, adaptive analysis, refreshed seven-case table and 211-test zero-skip constrained runs. Earlier native-only formulas and 3586-token synthetic costs are superseded; no activation is authorized.

## Private pull readiness (prepared, not activated)

On 2026-11-07 the dedicated private Harbor `spi-triage/runtime` manifest
`sha256:4cd6a12c1b046c03b74195b2d93aff183d8465230d364b527fa116fd25624a91`
was verified through Registry V2 and pulled on `socrat-1`. Its dedicated
`automation/spi-harbor-pull` Secret is referenced only by imagePullSecrets,
never mounted or exposed to application env. Robot permission metadata grants
only target repository pull; push and `homelab/spi-triage` pull were absent.
The 90-day project robot requires private rotation before expiry (1801812182).
Do not export credentials to Git, logs, browser cookies or command arguments.

The deny-egress, no-service/no-PVC preflight validated pinned assets and library,
then one benign public reservation: 1072, peak RSS 229024 KiB. This is startup
measurement, **not** steady-state memory proof. Temporary Pod/policy removed.
Source Harbor scanner reported nine fixable High vulnerabilities: runtime
vulnerability baseline/dependency attribution remains UNTRIAGED and is an
explicit activation-review gate. Do not blindly update pinned dependencies.

`values-off-live.yaml` prepares the private image/local counter; default chart
still uses original Python/byte-bound-v1. No production activation or job retry
has occurred. Operator CLI `scripts/n8n/spi_operator_retry.py` is dry-run unless
`--execute`, restricted to two exact approved job IDs, transactionally audited,
and preserves spent failure allowances. It requires separate independent review
before execution. Other dead/cancelled/completed jobs are not authorized.

Before **every** Git push (auto-Argo) and before future retry, use reviewed
`scripts/n8n/spi_private_backup.py` inside the worker with a private PVC temp
directory, streaming stdout directly to an operator host file under umask 077.
Verify host mode 0600, SQLite integrity, original terminal whole-row hashes,
all 119 cancelled rows, cache/intents/upload receipts/ledger and whole-table
hashes before permitting the change; retain the private backup. The helper uses
online backup, a 512 MiB/60 s bound, 64 KiB streaming, and finally removes private
PVC temp files. No serialize, restore, lease release or promotion is allowed.
A failed/truncated stream is not a valid backup. Future authenticated HTTPS
fetch/rebase is mandatory before any push; functional upstream delta/conflict
requires new review. Rollback uses original pinned Python and byte-bound-v1,
with DB/cache/ledger/history untouched. These preparations do not mean three
cards are complete.
