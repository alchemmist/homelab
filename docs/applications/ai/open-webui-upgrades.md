# Open WebUI upgrades

## Current owner and data authority

Existing release: `deploy/argocd/apps/open-webui.yaml`; chart/defaults:
`charts/open-webui/`. The authoritative WebUI runs on socrat-5 using
`open-webui-socrat5`, `/mnt/files/homelab/open-webui/data`. The retained original
`open-webui-data` on socrat-0 is stale, not a current rollback copy.
[Accepted handoff and rollback constraints](https://github.com/alchemmist/homelab/blob/2fd1179442b3c7b05c9049dfa4bbaa47bfbc3790/docs/llm-apps-vm105-20261115.md).

`open-webui.yml`, `open-webui-upgrade.yml`, `open-webui-https.yml` and
`open-webui-tool-guard.yml` are retired refusal-only entrypoints, not supported
upgrade or recovery procedures. They stop before key creation, Helm, image pull,
backup/scaling, persisted-setting updates, group DNS/firewall or imported identity
reconciliation. Do not adapt the historical old-node/old-PVC sequence or bypass
its former checks. Original implementation remains in Git history.

Review upstream release/schema notes, native compatibility/patch anchors and
rendered changes before committing the pinned image/version and any required
chart metadata to the owning source. Runtime rollout/maintenance requires its
own authorization and addressed reconcile, not a competing Helm upgrade or
blanket sync. Preserve credentials, users/chats/files/models and native SSO/TLS.
Do not silently reconcile identity or persisted model/retrieval settings merely
to test an upgrade. Existing admin operations are separate from chart deployment.

Backup implementation and restore work remain explicitly deferred by the owner.
This retirement creates no archive/schedule and makes no new recovery claim.
Do not undertake a stateful upgrade that needs an unavailable consistency/recovery
prerequisite. Rollback after schema/data writes is not a Helm revision rewind;
it requires a fresh, separately reviewed consistent data handoff.

The release details below are historical compatibility evidence, not a current
installed-version assertion or permission to replay the original upgrade.

## Version 0.12.3

The upgrade from 0.12.2 uses:

```text
ghcr.io/open-webui/open-webui:v0.12.3-slim@sha256:5adfb0355bbe4a5860c0ba9482cc0b40f573de3749a21a64cf4789391a14fffc
```

The two upstream tags contain identical Alembic migration directories: 66 files
with matching names and blob hashes. This does not replace the backup requirement.
Model-attached skills now include their full instructions on each message and
can increase prompt size. The Redis ACL change does not apply to this deployment,
which does not use Redis.

- [Release notes](https://github.com/open-webui/open-webui/releases/tag/v0.12.3)
- [Upstream update and backup guidance](https://docs.openwebui.com/getting-started/updating/)
