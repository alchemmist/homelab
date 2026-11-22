# Immutable pre-migration source inputs

These inert `.txt` files are exact historical source blobs supporting the existing unchanged public-entry migration SHA-256 fixture. They are not new current-state baselines, deployment code or test executables.

Provenance: `c6121e1975eb6218804a9be43d7c2a8e99584838`, `deploy/platform/grafana/public-entry/files/`:

- `grafana-policy.conf`: Git blob `843f21304c914bf70378b71e8c05172d83bd1f75`.
- `traffic-light-inset.js`: Git blob `27ec9fe426ee10f74d35bc7be55556a53e72e762`.

The historical `charts/uptime-kuma/files/kuma-policy.conf` at the same commit is stored as `kuma-policy.conf.txt`, Git blob `40a9cac2fe30cf52ad89785f940c73cc49f5655c`. It preserves the original migration comparison after the read-only Gatus transition; it is not active policy.

The test checks these identities using read-only local `git hash-object --stdin` (no `-w`, network, repository history or credential helper). It separately checks current live text/checksum and every other field against the unchanged original complete SHA-256 handoff fixture. Never refresh these blobs or fixture hashes to approve application changes. They are data only and are never executed.
