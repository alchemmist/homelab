# LMS database HA chart — outstanding manifest decisions

The backup PVC now explicitly follows Helm's release namespace, as does the
CronJob. This preserves the existing effective destination (the production
release is rendered in `lms`) while making the chart's resource ownership
unambiguous.

Three backup-Pod findings remain intentionally unresolved pending owner
approval:

- **Liveness/readiness probes:** this is a bounded, one-shot `pg_dump` / verify /
  encrypt CronJob (`activeDeadlineSeconds: 300`, `restartPolicy: Never`), not a
  serving process. A made-up probe could not represent backup success. Decide
  whether a meaningful preflight/health contract is required; Job completion and
  the existing overdue alert currently report success/failure.
- **Network isolation:** before adding a NetworkPolicy, approve and verify the
  exact permitted backup-Pod ingress and egress peers, including PostgreSQL
  service/endpoint traffic and required cluster DNS. No policy is added with
  guessed selectors or ports, and existing database access is not removed.
- **Credential delivery:** the backup container consumes the existing
  `lms-ha-app/password` as `PGPASSWORD` and mounts the independent encryption
  passphrase read-only. Choose a supported PostgreSQL password-file flow and
  confirm credential rotation behavior before changing delivery; do not claim
  that moving the same value through an intermediate shell variable removes
  secret exposure.

No backup job or cluster operation was run to resolve these design decisions.
