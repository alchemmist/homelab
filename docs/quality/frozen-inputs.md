# Exact frozen compatibility inputs, not a lint-debt exemption

Local strict cleanup update: `core.py`, `durable_wait.py`, `service.py`,
`s3_evidence.py`, `dispatcher.py`, `integrations.py` and `telemetry.py` are fully
renovated to
the ruff select=ALL and mypy strict gate without behavior change (verified by the full
`tests/spi_triage` suite; deterministic jitter now runs through a
`random.SystemRandom` instance on the `_RETRY_JITTER` seam, the Store owner
methods `reconcile_owners`/`owned_priority_until`/`schedule` are public
cross-module API, `service.py` keeps the reviewed HTTP surfaces and stage
pipeline factored into typed helpers with the same wire contract,
`s3_evidence.py` keeps the storage exception names and the SigV4 `sign()`
arity shared with the reviewed rustfs_gateway reference implementation, and
`dispatcher.py` keeps its test-pinned positional constructor arity, its
reviewed tail `except Exception` trust boundary and its stdout JSON log
contract, and `integrations.py` keeps its exact LOM system prompt bytes, the
v3 checkpoint/replay contracts pinned by the spi_triage suite, its bounded
rate-limit parsing and its fixed GitHub/observability adapter origins, and
`telemetry.py` keeps its reviewed bounded-read collector contract with the typed
telemetry window, trace-span projector, per-source request gate and the exact
Grafana link surface pinned digest-exactly by the spi_triage suite, and
`local_token_counter.py` keeps its golden chat-template render, its bounded
raw_fits budget walk and its digest-pinned tokenizer reservation contract
pinned by the spi_triage suite, and `card_correlation.py` keeps its exact
receipt SQL and fail-closed copy validation, `grafana_links.py` keeps its
reviewed Explore forceLogin seam and `storage_runtime.py` keeps its fail-closed
projected-Secret inode validation, `github_broker.py` keeps its one-hour
repo-scoped token mint seam and `queue_admin.py` keeps its audited atomic
cancellation seam, all pinned by the spi_triage suite).
Together
with the older `telegram_delivery.py`/`telegram_links.py` patches this marks
**fifteen locally patched modules**, not pristine upstream files.
All 17 deployed inputs still have pinned SHA-256 digests; only the 2 unpatched
modules are excluded from owned-source checks. The earlier boundary below
describes the snapshot before those local patches.

Earlier local compatibility update: commits `a6c666af` and `dec487d0` changed
card discovery, the guarded POST timeout and its retry lease. `telegram_delivery.py`
and `telegram_links.py` are therefore **local patches**, not pristine upstream
files. All 17 deployed inputs still have pinned SHA-256 digests; only the 15
unpatched modules were excluded from owned-source checks. The original boundary
below describes the snapshot before those two commits.

## Original snapshot

`charts/spi-triage/LEGACY-SOURCE-MANIFEST.json` predates this strict cleanup
(commit `de6f81e8`). It declares the separate canonical repository
`https://github.com/alchemmist/spi-triage`, says these are frozen compatibility
inputs that must not be developed here, and already records17backend SHA-256
values. The manifest and all17source files remain byte-identical. No checksum
was regenerated to bless this cleanup.

The strict ownership boundary now recognizes precisely those existing files.
`ci/quality/strict-policy.json` pins the existing manifest bytes; the checker then
validates the canonical repository, fixed directory,17file count, safe basenames,
no symlinks/path escapes and every preexisting source digest. Validation runs
before exclusion in `owned()`, in graph-integrity contracts and in strict_guard.
Any missing or modified input fails closed rather than disappearing from lint.

This does **not** exclude the SPI chart, its file directory, its locally maintained
UI/backend integration, Helm output, or a newly added neighbouring Python file.
The root continues to validate/render its actual manifests. The secrets scanner
continues staging **all tracked files**, including vendor and frozen source.
Unlisted local code remains subject to owned-code checks. Frozen-input provenance
is not an authenticity/signature claim or a third-party vulnerability exemption.

Mutation tests verify changed bytes, missing input, a symlink, changed manifest,
an added manifest entry, path traversal even with a changed fixture digest, and
that new neighbours remain owned. Temporary test fixture changes are not updates
to the actual provenance pin. An upstream source update requires a separately
reviewed version/provenance change and tests; never automatically recapture the
manifest/digest merely to silence a linter.

This is the operator's narrow third-party-code scope, not acceptance of historical
owned-code findings. Other byte mirrors/content-addressed local inputs remain
owned and still need coordinated fixes; this document does not exempt them.
