# Monori issue 509 — author `alchemmist`, human-only merge

From Canvas use plain anonymous HTTPS for clone, issue, comments, checks and PR reads. Do not use a token-bearing git remote, `gh auth login` or request_secret. To publish send JSON with `Content-Type: application/json` to `http://monori-publisher:8081/v1` (inside the Canvas pod only). No credential from the caller. All shared owner conversations have the same limited interface; not per-conversation isolation.

- `{"action":"capabilities"}` is read-only.
- `create`: `action`, `head` (current full main SHA), `title`, `files` (object mapping changed repo-relative paths to full UTF-8 contents). Test locally first. Allowed Python files under `server/tests/` or `server/app/`, max12 files and250000-byte JSON. A new server-selected branch, commit and non-draft PR for review; no merge. At most5 open publisher PRs. No deletes, workflow files or arbitrary refs.
- `update`: same plus `pr` number; `head` must be the current SHA of an open publisher PR. No force pushes. Check existing branches/PRs after a lost response; a multi-call create may leave a branch without a PR.
- `report`: `action`, `pr`, `head`; posts a fixed progress comment on issue509, never edits the issue.
- `reply_then_resolve`: `action`, `pr`, `head`, `thread` (GitHub GraphQL PRRT node ID), `decision` (`fixed` or `declined`), `reason` (specific single-line explanation,30–2000 characters). Assess each finding first. For fixed findings, push the tested fix first. Checks ownership, replies with head SHA, rechecks head, then resolves. Re-inspect before retry after partial failure.

A published PR is not Ready to Review: require green CI on latest head, actual independent reviews, all comments assessed/replied/resolved. Timeout is not a review. A conflicting main change or any unexpected error means reassess, not retry blindly. Do not publish a dummy PR just to test access.

Operator: `openhands/monori-publisher-user` contains one fine-grained token, only `alchemmist/monori`; deployed separately from Canvas. Expires 2027-02-16; rotate out of band before expiry. No raw token in workspace, profile, chat, Git or runbook. Removing this token on GitHub revokes service access. Verified authenticated user and issue read, Canvas capabilities and denial of merge; first real write remains task acceptance. No change to paused automation/SWE or the 1.41.0 runtime image.
