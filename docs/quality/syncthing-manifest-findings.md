# Syncthing manifest findings: implementation and residual decisions

The Syncthing chart's two missing-probe findings are fixed with TCP readiness and
liveness checks on its named GUI listener. These checks only mark the workload
ready/live while the configured Syncthing GUI socket is accepting connections;
they do not claim folder synchronization or peer health. The Syncthing pod also
opts out of API-token automount because this workload does not use the Kubernetes
API. The rendered chart test verifies both behaviors.

The remaining findings are intentionally not cleared by speculative policy or
identity changes:

- **Two dangling GUI Services:** each selectorless Service has a node-pinned
  Endpoints address so requests reach one independent Syncthing identity rather
  than a load-balanced peer. Before changing this contract, compose the chart
  render with the actual registered node workloads and prove each endpoint maps
  to the intended ready Syncthing pod. Do not replace it with a broad selector.
- **Default ServiceAccount:** token automount is disabled. Decide whether a
  dedicated no-permission ServiceAccount is required for identity separation;
  there is no current API permission requirement to grant.
- **Host networking, writable host mount, and two non-isolated workload
  findings:** host networking exposes the native sync/discovery listeners and
  `/srv/syncthing` holds the node's established identity, database and folders.
  Any replacement requires an approved sync/discovery/GUI address and peer
  matrix plus offline positive/negative network tests; host-network behavior
  must be tested separately because Kubernetes NetworkPolicy does not isolate
  host-network traffic. A storage/identity change additionally requires a
  verified copy/restore and device-ID/folder continuity test. No such change is
  approved here.
- **Non-root and read-only-root-filesystem findings:** do not assert a UID or
  read-only root until the pinned image's supported UID and every config,
  database, temporary and runtime write path are established, and a disposable
  restart/reconnect test confirms existing host data remains writable and the
  device identity is unchanged. Do not recursively change ownership of the
  existing data directory as a workaround.

No network policies, selectors, host-network settings, image identity, service
account binding, storage paths or permissions were changed. The remaining
items require the evidence/owner decisions above; their findings remain open.
