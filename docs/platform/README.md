# Platform guides

Start with the [system overview](system-overview.md) for topology and sources of truth. Before changing the cluster, check the [operational boundaries](operational-boundaries.md).

| Task | Guide |
| --- | --- |
| Understand control-plane availability or pod placement | [K3s HA](kubernetes/k3s-ha.md), [workload placement](kubernetes/workload-placement.md), [resource budgets](kubernetes/resource-budgets.md) |
| Add a node or troubleshoot the socrat-3 host | [Node bootstrap](nodes/node-bootstrap.md), [socrat-3 provisioning](nodes/socrat-3/socrat-3-provisioning.md), [network recovery](nodes/socrat-3/socrat-3-network-recovery.md) |
| Follow a release or find its configuration owner | [Cluster delivery](delivery/cluster-deploy.md), [infrastructure contracts](delivery/infrastructure-contracts.md) |
| Operate the image registry | [Harbor](harbor/harbor.md), [HA capacity stage](harbor/harbor-ha.md) |
| Choose a storage tier or locate object storage | [Storage tiers](storage/storage-tiers.md), [RustFS](storage/rustfs-foundation.md) |
| Reach Rancher or diagnose a stale node list | [Private access](rancher/rancher-private-access.md), [cache recovery](rancher/rancher-cache-recovery.md) |
| Connect an agent to a platform service | [Official MCP connections](agent-access/official-mcp.md) |
