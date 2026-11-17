# Synchronize canonical alert diagnostics with main's PSI split

## Exact prior HEAD evidence

At d0d858d656edae61e40b9f507c7fc466334cd12a:
- fast707passed/1existing skip/329subtests, exit0;
- medium300passed/5existing skips/313subtests, TWO genuine failures, exit1;
- full audit49937blocking (643fewer than bd7f3071's50580), exit1;
- Python41786,YAML6727,shell8,workflow3,secrets5,Ansible384,manifests1024;
- configurationReady=true,snapshotStable=true,blockers=[]; sourceClean=false.

The medium failures were stale generated alert graphs and their inventory, not a
missing-daemon skip. They were retained and repaired. No host daemon/configuration
repair, new skip, fixture bypass or production action was performed.

## Reviewed canonical generation

Main's accepted socrat-4contention change creates two variants of the same alert.
The inventory/dashboard still described the earlier unsplit condition. Called the
canonical generator's inventory()/outputs() functions, inspected its proposed
changes before writing, and wrote ONLY these two differing outputs:
- charts/monitoring-k3s/alert-dashboards/alerts-9943c0b05432b778.json;
- docs/monitoring/alert-graphs.inventory.json.

This is generated diagnostic synchronization against an already merged main
source change, NOT debt/approval baseline recapture. The native11-case PromQL test
still asserts the owner-approved conditions and durations. No alert expression,
routing, threshold, source rule, deployment or Grafana runtime was mutated.

Verified inventory203->204rows is exactly one old monitoring-k3s
SocratNodeResourceContention expression replaced by two main expressions; all other
rows remain identical. All old graph specifications match their new counterparts.
The complete generated panel-ID registry is byte-identical. All other generated
outputs match their current bytes; no n8n JSON or additional chart artifact was
written. The explicit inventory count expectation now accounts for that one added
source variant rather than deleting its coverage assertion.

Added a panel-ID regression proving a condition split keeps the original mapping
and ledger, retains both inventory rows, and preserves both exact condition queries.
This guards against silently keeping only one variant to make generation pass.

## Working-tree validation before commit

Full medium302passed/5existing skips/314subtests, exit0. Scoped Ruff ALL and strict
mypy for panel-ID/native PSI/common helpers pass. Exact committed-head fast,
medium, contracts, guard, graph validation and complete strict audit follow;
this checkpoint alone is not their result and is not a green/merge claim.

Private evidence: d0d858d6-{fast,medium,audit}.txt and
parent-alert-sync-medium.txt under the existing0700private evidence directory,
files0600. Fixed native admission ceilings and every remaining finding remain
blocking. No policy, reviewed exception or native limit was changed.
