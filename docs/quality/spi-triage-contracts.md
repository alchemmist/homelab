# SPI triage broker contracts

The spi-github-broker CronJob (`charts/spi-triage`, namespace pr-agent) reads
`GITHUB_APP_ID` and `GITHUB_PRIVATE_KEY` from Secret pr-agent via `secretKeyRef`.
That is the GitHub App's environment-only authentication interface; there is no
file-based configuration channel for these values. The secret is managed out of
band.

The `spi-github-token-writer` Role/RoleBinding grants only `patch` on the single
Secret `spi-github-installation`: the broker exchanges the GitHub App private
key for an installation token and must persist that short-lived token in exactly
that Secret. This is least-privilege Secret access, not broad secret read.

Hardening: the SPI require-existing-data init container now has a read-only root
filesystem and resource budget (the pinned spi-triage image was run as uid 1000
under `--read-only` successfully), and the broker CronJob has a pod-template
label plus an ingress-empty NetworkPolicy limited to GitHub HTTPS and DNS.
