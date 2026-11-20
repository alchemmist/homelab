# Pyroscope shared PVC — active production data

**Do not empty or delete `pyroscope-s1-candidate`.** Despite its historical
name, production uses this `nfs-shared` claim served by socrat-0. One writer,
Recreate, eligible nodes 0/1, prefer 0. This covers the drill for loss of 1,
not loss of 0. Removing the old PVC is neither required nor approved.

After #213 stopped the only writer, a read-only source mount was archived on
1 (75,601,920 bytes). The backup was extracted to staging on the empty target;
all 415 paths including 203 files compared equal by type, size and SHA256 to
the stopped source. The copy pod was removed before #214 started a writer.
The new pod on 0 uses the expected claim, HTTP `/ready` passed, and a fixed
historical CPU flamegraph query matched its original total and symbol count.
A separate query strictly after startup returned nonzero real CPU samples;
no test profile was written to production. The original disk and archive
on 1 are recovery points, not current data. After new writes do not switch
back without reconciling histories. Both PVs have Retain reclaim policy.

## Earlier isolated staging check (not a cleanup instruction)

Using the production 2.4.3 digest, v2 filesystem architecture, args and UID,
two sequential isolated pods with different names mounted the same synthetic
subdirectory. No Service, production labels, secrets or service token. All
network traffic denied except loopback. Pod on 1 ingested and queried a folded
CPU sample; pod on 0 became ready, queried the old stack, then ingested and
queried a distinct new stack. Only the isolated scratch directory was removed;
empty claim verified. This is graceful cross-host recovery, not a crash test.
