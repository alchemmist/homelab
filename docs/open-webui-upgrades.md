# Open WebUI upgrades

> **15Nov migration supersedes node0 data assumptions below.** The authoritative
> WebUI now runs on socrat-5 with `open-webui-socrat5`, dedicated data path
> `/mnt/files/homelab/open-webui/data`. Original node0 `open-webui-data` is a STALE
> retained recovery copy. The existing upgrade playbook is node0/old-PVC-specific
> and fails closed against the current deployment; adapt its backup path/execution
> for VM105 before using it. Never bypass its assertions, back up the old claim as
> if current, or repoint a writer to the old copy. [Current handoff/rollback](llm-apps-vm105-20261115.md).

The Helm chart pins the official `ghcr.io/open-webui/open-webui` slim image by
version and manifest digest. Update `charts/open-webui/values.yaml` and the chart
version and `appVersion` in `Chart.yaml` together.

From `ansible/`, run:

```sh
ansible-playbook -i inventory/hosts.yml playbooks/open-webui-upgrade.yml --ask-become-pass
```

The upgrade playbook targets the existing single-replica deployment in namespace
`llm` on socrat-0. It validates the chart and downloads the image before downtime,
stops the application, and archives the complete local PVC in a root-only
directory under `/var/backups/homelab-open-webui/upgrade-*`. Each directory contains
`data.tar.gz` and `release.json`, recording the previous Helm revision.

After archive validation, Helm applies the chart and waits for readiness. The
playbook checks `/api/version`. Existing authentication Secrets, model defaults
and DNS configuration are not recreated by this workflow. A backup failure
restarts the original deployment; an upgrade failure stops the playbook for
supervised recovery rather than automatically rolling application code back
against a potentially migrated database.

Before deployment, compare the rendered chart with the installed Helm manifest
and inspect upstream release notes. After deployment, check HTTPS, database
integrity, preserved user/chat/file/model counts and the configured inference
connection. Backups contain private chats and credentials and must stay private.

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
