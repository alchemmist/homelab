# Pyroscope socrat-1 drill — staging only

Production still uses `pyroscope-data` on 1. The UID-guarded JSON patch retained
its PV; never delete this claim or mutate its storage class. Local Retain is
not a backup. The empty 5Gi RWO candidate is `nfs-shared`, Retain, served by
0, not HA against loss of 0. No production pod mounts it.

Using the production 2.4.3 digest, v2 filesystem architecture, args and UID,
two sequential isolated pods with different names mounted the same synthetic
subdirectory. No Service, production labels, secrets or service token. All
network traffic denied except loopback. Pod on 1 ingested and queried a folded
CPU sample; pod on 0 became ready, queried the old stack, then ingested and
queried a distinct new stack. Only the isolated scratch directory was removed;
empty claim verified. This is graceful cross-host recovery, not a crash test.

The production historical gate is a fixed positive CPU window verified with
`SelectMergeStacktraces`; retain bounds and numeric reference privately, not
stack frames. For migration: stop the sole writer, archive and restore/compare
the complete `/data` tree including metastore state, preserve both PVs, verify
one writer on the new claim and the same historical window before declaring
success. No guarantee of new production samples when producers are idle; do
not wake a hibernated LMS workload. Verify new ingestion separately.
