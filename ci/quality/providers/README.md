# Cross-source provider and binding contract registry

Offline kube-linter sees only the objects rendered from one chart in one
target. The cluster is nevertheless provisioned from several reviewed sources
that a single Helm render cannot observe: secrets provisioned out-of-band by
reviewed scripts, services deployed from registered external charts,
control-plane providers such as the kubelet, and node-level binding contracts
for infrastructure daemons.

Each entry pins one exact rendered object that legitimately references or
binds the out-of-band source (its consumer release target, rendered kind,
namespace and object name), the kube-linter checks that are covered for that
object, and a specific, verified evidence pointer into the repository that
actually names the out-of-band object. The registry is strictly positive
evidence:

- an entry whose evidence path does not exist, or whose evidence does not
  name the referenced object, fails the run at load time;
- an entry that stops matching a real finding of its consumer target fails
  the run (no orphaned, anticipatory or accidentally broad pins);
- any finding not covered by an exact entry is still reported;
- kube-linter checks outside the approved registrable set can never be
  registered.

Loading and every one of these guarantees is enforced by controls in
`ci/quality/check_monitoring_selector.py`, which run inside the
`Manifest validation` job.

The control fixture consumed by `ci.quality.check_monitoring_selector.py`
names the synthetic object `quality-check-evidence-provider`; no real
registry entry may use that name.
