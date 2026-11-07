# Operator preservation hashing: transaction-local streaming

The operator helper streams every selected SQLite table's full `SELECT *` rows,
except the audit table, which retains its separate exact-content/schema checks.
Ordinary tables use an unshadowed, quoted rowid alias; WITHOUT ROWID tables use
declared primary-key order. Identifiers are quoted; table introspection and the
actual EXPLAIN QUERY PLAN must succeed without any temporary btree. Virtual
and shadow tables, all-three-shadowed rowid aliases, missing introspection, and
plans requiring a sort fail closed. There is no all-column/Python-sort fallback.

This is a transaction-stable preservation fingerprint, not an externally
persistent canonical logical hash. Comparisons run inside the same BEGIN
IMMEDIATE. Different insertion order/root rowids, VACUUM or another database
copy need not have the same hash. No persisted authorization digest changes:
original full-row manifests, original-file SHA, nonce, and authorization checks
remain intact. Only the two already verified target rows are normalized after
updates; all other rows/columns/tables remain covered. Serialization memory is
bounded by a row (including its blob/JSON representation), not total table size.
No global temp_store pragma or memory-limit increase is introduced.

## Offline reproduction (no worker/cluster access)

The failed live dry-run stopped before fetch/backup/push and never established
eligibility. Read-only diagnostics reported /data free 226392649728 bytes,
DB 56561664 bytes (54 MiB), page_count 13809, page_size 4096, freelist 178,
WAL mode, temp_store=0; /tmp is 64 MiB tmpfs with 36732928 bytes free.
This is not evidence of PVC disk exhaustion. Full-row temporary sort pressure
is a credible explanation, not conclusively proven on the live database.

A synthetic host-private 64536576-byte fixture, 14000 rows with 4096-byte text
payloads, was bind-mounted read-only in existing test image 87741b7b6a39... .
With read-only root, no network, 384 MiB / one CPU, and a test-only 1 MiB /tmp
plus SQLITE_TMPDIR=/tmp, the old SELECT * ORDER BY 1,2 raised SQLITE_FULL;
the corrected full-data hash completed twice in the same transaction.
SQLITE_TMPDIR constrains only the test process, not operator/runtime settings.
Without that explicit test environment, SQLite selected a different temp
location and the initial reproduction did not fail; it is not counted as proof.

Run tests/test_spi_operator_hash.py with SPI_SORT_FIXTURE pointing at that
read-only synthetic fixture and SQLITE_TMPDIR=/tmp in that constrained container.
The fixture is not repository content. No production rows or private manifests
were copied, printed, regenerated, or modified. Do not rerun the failed live
CLI until fresh source review and all unchanged operational gates are cleared.
