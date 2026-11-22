---
name: ready-to-merge
description: Use when opening a project pull request, preparing it for review, or addressing review threads until it is ready to merge. Stop before merging.
---

# Ready to merge

Use English for the PR title, description, commit messages, review replies and status updates.

1. **Draft → ready for review.** Open the PR as a draft. Keep it in draft until the full required CI is green on the current head SHA, including the [Quality Graph](../../../docs/quality/README.md) aggregate. Pending, missing, skipped or cancelled checks do not prove success. Fix failures, push and check the new head. Only then mark the PR ready for review.
2. **Process one review round.** Fetch all unresolved review threads, including bot reviews. Process them one at a time. Keep a local mapping of each actionable thread to its fix commit.
   - **Fully or partly actionable:** implement the applicable change, verify it and make a new local commit for that thread. Do not push, reply that it is fixed, or resolve it yet.
   - **Not applicable:** reply in that thread with a concrete reason supported by the code, contract or test. Then resolve it. If applicability is unclear, ask for clarification and leave the thread open.
3. **Publish the batch.** After processing all threads in the round, push the accumulated commits together. Verify the commits are on the remote PR branch. Then reply **in each fixed thread** with a clickable link to its commit and say what changed. For a partial fix, explain which part was not adopted and why. Resolve the thread after replying; leave it open if any requested work or clarification is still outstanding.
4. **Repeat and stop.** Recheck CI on the latest head and fetch unresolved threads again after reviewers respond. Process new feedback in another round. Report **ready to merge** only when CI is green on that exact head, review rounds are complete, no threads remain unresolved, and required approvals and branch protections are satisfied. Otherwise report the blocker. Do not merge, enable auto-merge or bypass protections.
