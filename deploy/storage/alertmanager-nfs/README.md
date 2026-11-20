# Alertmanager state migration for the socrat-1 drill

**Active after the 2026-11-20 cold migration. Do not re-run the copy or replace the claim.** One Alertmanager,
not an HA pair. The target NFS server is socrat-0, so this does not cover loss
of socrat-0. There is no automatic data merge or rollback after writing to NFS.

Verified 2026-11-20: `pvc.yaml` is Bound (Retain backend). Two sequential,
unprivileged, tokenless pods using Alertmanager UID 1000/GID 2000 tested
write/fsync/rename and directory fsync on socrat-1, then read/cleanup on
socrat-0. No source files were touched. Keep this claim: it has the exact name
for ordinal 0 and template `alert-state-nfs`. An API dry-run of the overlay
checks the CR only, not StatefulSet recreation or persisted state.

Production cutover: Git #189 stopped the single writer; a restricted pod copied
and verified all source files with hashes before unmounting both claims. #190
started the same singleton on socrat-0. The live ordinal mounted the pre-staged
NFS claim, the active silence IDs matched, and Prometheus discovered the new pod.
Both PVs are Retain; the earlier source is a recovery point, not current state.

## Original cutover gates (historical; not a routine restart procedure)

1. Capture live claim/PV UIDs, mount subPath, active silence IDs and alert counts
   privately; don't print receiver configuration or tokens. Verify source PV is
   protected (current local-path policy is Delete; set to Retain before cutover),
   StatefulSet retains claims on scale/delete, both claims remain Bound, and a
   restorable backup is available. Check the **bound target PV itself** has
   `persistentVolumeReclaimPolicy: Retain` and its `claimRef.uid` matches the
   target PVC UID. Preserve originals; never delete either PVC.
2. Keep Prometheus evaluating; pause before the drill itself. Stop the old
   **Alertmanager only** via the owning Git CR (`replicas: 0`). Confirm its pod
   terminated and no writer remains. Notification delivery is interrupted here;
   do not silence alerts or claim continuity during this window.
3. Use one restricted copy pod on socrat-1, source PVC read-only and target PVC
   writable, no service account token. Copy the **whole** `alertmanager-db/`
   directory (including notification log and silences) to the same subPath. Abort
   if target already contains application data. Verify matching relative paths,
   sizes, hashes and readability under UID 1000/GID 2000. Unmount both claims.
4. Only then wire this overlay into the Argo Application **last**; do not live
   patch or delete the StatefulSet/PVC to bypass errors. The Prometheus Operator
   v0.94.1 honors the custom claim-template name. Before activation, compare
   `<rendered CR claim-template name>-<live StatefulSet name>-0` with the staged
   PVC name. After reconciliation check the actual ordinal-0 pod mounts that
   claim and its UID/PV are unchanged from step 1. If not, stop; do not accept
   an empty new claim as restored state.
5. Verify exactly one Ready pod on 0, same silences and healthy restored state,
   and Prometheus `/api/v1/alertmanagers` points to that pod. Verify a clearly
   labeled synthetic firing AND resolved notification reaches the real recipient
   through n8n; lack of webhook errors alone is not proof. Then remove the hostname selector from **both**
   `charts/alertmanager/values.yaml` and `cutover.values.yaml` in the same change.
   Keep the overlay active with its storage settings and Linux selector. Add
   required hostname affinity for `socrat-0/1` and preferred affinity for `0`.
   Render with Argo values in order, check that the merged selector has no hostname
   (not even a null key), and verify live placement before the drill.
6. If migration fails before writes, revert to the original claim/host while
   retaining the target. After writes, stop and preserve **both** copies, decide
   how to handle newer silences/dedup state, never overwrite the source blindly.

During the actual drill monitor the Prometheus `KubeNodeNotReady` rule directly:
its `for` is 15m. Allow node detection, rule evaluation, Alertmanager grouping and
webhook delivery; brief outages need not fire. Do not use a fabricated instance
of the real node-down alert as proof the node actually went down.
