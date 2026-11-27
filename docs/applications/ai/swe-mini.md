# SWE Mini retirement

The owner requested permanent removal of the Monori maintenance queue from Socrat,
not an image upgrade. Git no longer declares an Application, chart, values,
credential provisioning script or release workflow for it. The retired service source and its queue/policy tests were removed as well. [PR #462](https://github.com/alchemmist/homelab/pull/462) was
closed without merging: its lock audit findings are **not** resolved by retirement.
The former deployment instructions and November 17–18 acceptance receipts remain
in Git history. They are not a recovery procedure.

## Live verification is separate from Git intent

1. Verify the Socrat `argocd/root` follows `main:deploy/argocd/apps`. Before
   removing the Application from Git, observe the foreground resource finalizer
   on the child. Let the parent reconcile normally. Do not blanket prune or
   bypass a stuck finalizer.
2. After root reconciles the removal, check its resource list, the actual child
   Application and its namespace. The chart deliberately protected both the
   namespace and `swe-mini-state` with `Delete=false`; ordinary cascade need not
   remove them. Re-inventory **all** namespaced resource kinds before cleanup.
3. Preflight found just one queue claim: `swe-mini/swe-mini-state`, 2Gi RWO,
   dynamic `local-path` on `socrat-5`, reclaim policy `Delete`. Match the claim UID,
   PV claimRef, provisioner and node-local path again. Deletion destroys the
   queue, reports and review state. Stop if ownership or usage has changed. Do
   not remove host directories or touch shared storage, upstream credentials,
   registry artifacts, Monori or OpenHands. Only dedicated namespace copies of
   the GitHub signer, Harbor pull secret and model credential are in scope.
4. Verify absence of the namespace, claim/PV and Application, root at a revision
   containing the removal, no Argo tracking entry or release publisher, then
   repeat after another reconciliation. A merged PR is not evidence that these
   live checks passed.
