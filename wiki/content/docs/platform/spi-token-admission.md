---
title: SPI token admission live receipt
---

## 6 November 2026 — acceptance pending

SPI runtime revision **48b8161** (reviewed c2d9f57 + 8b933d9, rebased as
bd41901 + 48b8161) rolled out normally at 15:52:51 UTC. SPI Argo was Synced /
Healthy. Existing pinned Python image, ConfigMap delivery, Recreate strategy,
replica count and PVC/container specification are unchanged. Runtime hashes match
ConfigMap and normalized source; shared Store injection/admission methods verified.
No rebuild, provider/key/payment change or unrelated app sync.

Read the authoritative operational detail in
[the token admission runbook](https://github.com/alchemmist/homelab/blob/main/docs/n8n/spi/token-admission.md).
Its deployment-specific qwen-byte-bound-v1 uses NFC UTF-8 message bytes, schema,
256 framing bytes and full output reserve, validated against Qwen revision
91bd022d5b49442a868bc35008f6c21e1860edfa. It is not a generic tokenizer guarantee.
The conservative 3 RPM / 30000 TPM / parallel1 budget is unchanged.

A fresh consistent SQLite backup preceded push (integrity/FK/header valid).
All 315 original IDs/creation times and all 119 cancelled whole rows survived.

Natural observation **15:53:58–16:38:59 UTC**, then stopped: 33 saved batch
reviews / 346 candidate reviews, four jobs reached stage2 (match+collect), zero
new completed jobs/reports/publications. 35 fresh typed admission waits, zero new
HTTP429. Old retained error fields are not fresh errors. Checkpoint prefixes
survived 207 same-signature comparisons. Stage2 reservations 28332–28931 fit but
waited behind older matching work with near-full ledger holds; infinite small
request starvation is not demonstrated. Actual provider usage is not separately
persisted; charges are conservative reservations, not exact live usage.

The requested cards remain queued stage0 attempt0, **not completed**:

- Resolved uptake-kuma KubeDeploymentReplicasMismatch (original17:21MSK), episode
  `83bb101278aba11036f0ce7841eabaeb9ebc00339cd667da626c9beee8e41700`,
  firing job `305b227cdc96…`, resolved `8c6af704b3fd…`.
- Firing SocratContainerRestartsFrequent17:28MSK, episode
  `b5a10f46b0a2ce6ebb6429d78cc9cb13e42f0a562f6b39abc181c2d51a7cae0c`, job
  `08ba1f0938dd…`.
- SPI triage queue is stale17:45MSK, episode
  `b201c71c8b2bce1305233bfa7e47cacae545f2435fe6d644fd1df9bdf74cfb31`, job
  `998bcead1720…`.

All have two native card copies and exact event receipts. None has a primary or
link outbox yet: GitHub narrative, canonical file URL/Reader SHA and Telegram
applied2/2 are pending, not claimed using a different incident. The stale alert
was not muted or retuned. Remaining gate is natural analysis/publication followed
by exact episode/revision acknowledgements; no forced selection or resets.

Rerun:169 SPI,5 chart/helper,9 JS tests; Helm lint/template and whitespace checks
passed. Keep integer charges and v2 checkpoints; old fixed12 binaries must not
reinterpret v2. No continuing observation after this bounded window is implied.

### Completion-aware scheduling correction — source-only

The scoped correction prefers eligible stage3 writes, stage2 analysis, stage1
collection, then stage0 matching; ties retain natural created/id ordering.
Claim and dispatcher share effective eligibility/next-wake calculation. Only a
live stage2 retry with `LLM_ADMISSION_DEFERRED` and a matching known ledger
expiry may hold stage0 until its existing jittered due time (expiry to due at
most4s; failure to due at most664s). Expired ledger data cannot extend this
bound. Active requests are not preempted; safe writes/collection and independent
Telegram deliveries are not held. Unknown429/hour backoff, terminal jobs and
out-of-bound/stale deadlines do not freeze healthy new matching. Pending-age
alerts retain original semantics; no durable job deadlines/checkpoints change.

Normal admission remains 3 RPM/30000 TPM/parallel1 with qwen-byte-bound-v1,
256 framing and conservative61s completion retention. Abandoned active ledger
entries use normal expiry, including after restart. This is completion
preference, not a global starvation guarantee under infinite later-stage work.
Stable snapshots, valid analysis and successful publication remain prerequisites;
synthetic tests do not accept the user's three live cards. No paid calls, queue
changes, deployment or endpoint probes are part of this correction. See
`docs/n8n/spi/token-admission.md` for bounds and runbook. Rollback only this
scheduler delta on the v2-capable runtime; never reinterpret v2 checkpoints with
a fixed-12 matcher. Later rollout requires review, fresh backup and fetch/rebase.
