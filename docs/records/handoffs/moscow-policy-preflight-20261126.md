# Moscow private rehearsal: NetworkPolicy preflight, 26 November 2026

At 13:06 UTC, a disposable Pod on `socrat-4` served nonce echoes behind one
ClusterIP on TCP/18443 and UDP/18443. Five tokenless, non-root Pods in a fresh
namespace used no host network or public ports. A policy selected `role=listener`,
denied egress and allowed ingress only from same-namespace Pods labeled
`probe=allowed`. Each client checked the echoed bytes, not merely socket setup.

| Client source | Allowed TCP / UDP | Denied TCP / UDP | Allowed again |
| --- | --- | --- | --- |
| `socrat-4` (same node) | reply / reply | refused / refused | reply / reply |
| `socrat-1` (cross-node) | reply / reply | refused / refused | reply / reply |

Both previously denied Pods then received the allowed label in place. Both
received correct TCP and UDP replies without changing source Pod, destination,
ports or server. An earlier attempt stopped on the first refusal because the
client expected a timeout; that incomplete run was not counted. Both disposable
namespaces were removed. The existing public relay remained Ready and available.

This demonstrates selector enforcement on the observed inbound paths, not
all NetworkPolicy behavior, VPN authentication, NL source identity or public
failover. The operator confirmed the existing VPN through Moscow after reboot;
no separate per-transport baseline was reported. After the private pair starts,
repeat permitted/denied tests on its actual Services, check blog TLS and content,
verify authorized TCP and UDP profiles and observe relay egress at NL. Keep
public sockets, DNS, NL ACLs and the watchdog unchanged.
