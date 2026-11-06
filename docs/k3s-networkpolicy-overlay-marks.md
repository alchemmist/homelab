# Kubernetes NetworkPolicy: inherited NetBird/VXLAN marks

## Incident and proven mechanism (2026-11-06)

RustFS on socrat-0 had the intended `rustfs-isolation` policy: only the
`identity` namespace AND `app=rustfs-gateway` selector could reach TCP/9000;
console TCP/9001 was not admitted. Nevertheless, unrelated nonprivileged pods
on socrat-1/2/3 reached both ports, through both Pod IP and ClusterIP. A pod on
socrat-0 was correctly rejected. S3 anonymous 403 was authorization, **not**
evidence of network isolation.

Narrow header-only nftables tracing established:

1. The incoming inner packet on `flannel.1` already carried skb mark `0x1bd22`.
2. Native host NetBird reverse-route rules set this mark on new packets whose
   source is one of the selected `10.250.0.x` node addresses. The VXLAN underlay
   uses these addresses. The inner packet inherited the transport mark.
3. `0x1bd22 & 0x10000 != 0`: kube-router's policy-allow bit was already set.
   Its RustFS pod chain skipped rejection despite no matching ingress allow,
   then set the final `0x20000` acceptance bit.
4. `0x1bd22 & 0x2000 != 0` also triggered CNI hostport masquerade. This was not
   the original source pod having an authorized identity.
5. WireGuard `wg-socrat` fwmark was `off` on all four nodes. This was a host
   NetBird / VXLAN / kube-router mark interaction, not a stale public route or
   an incorrectly written namespace/pod selector.

This can undermine other cross-node policy boundaries too; it is not safe to
paper over RustFS with an additional ordinary NetworkPolicy or S3 permissions.

## Durable correction

`scripts/k3s-overlay-marks.py`, role `k3s_overlay_marks` and playbook
`ansible/playbooks/k3s-overlay-marks.yml` own **only** the nftables table
`inet homelab_k3s_overlay_marks`.

At prerouting priority **-175**, between conntrack and normal mangle, the rule
clears a nonzero skb mark only when all of these match:

- ingress interface `flannel.1`;
- IPv4 source in `10.42.0.0/16`;
- IPv4 destination in `10.42.0.0/16`.

Host transport marks are not valid pod authorization. kube-router and kube-proxy
can assign their own marks normally after this boundary. Direct `nb-host`,
WireGuard administration, host traffic and Mac VPN settings are not changed.
The solution does not rewrite NetBird-managed rules or fork its binary.

The root-only oneshot `homelab-k3s-overlay-marks.service` persists the guard and
is ordered before k3s/k3s-agent at boot. The interface need not exist yet because
the rule uses `iifname`. No Kubernetes, WireGuard, NetBird or database restart is
needed. Stopping this oneshot deliberately does **not** remove its live guard.
Do not remove the table while relying on policy isolation with this mark conflict.

The helper defaults to audit, kernel-checks the proposed transaction, refuses a
foreign ownership marker, verifies the exact semantic rule and writes private
before/after records under `/var/lib/homelab-k3s-overlay-marks`. Updating its own
table is one atomic transaction; it never flushes the ruleset. The playbook
preflights all selected nodes before serial application. Do not use `--limit`
for a normal rollout; a limited first canary is an explicitly reviewed exception.

nft 1.0.6 on socrat-2 omits table comments from JSON even though the kernel and
text output retain them. Initial post-write validation stopped on that mismatch;
readback confirmed the correct guard was active. The helper was corrected and
regression-tested: ownership falls back to the exact table-level text comment,
not a matching rule comment; semantic comparison tolerates only that version
representation difference. Subsequent audits/activation converged without
rewriting that already-correct table.

## Operation

From `ansible/`, using the existing private controller credentials:

```sh
CROOT="$HOME/Library/Application Support/homelab/otel-controller"
ANSIBLE_SSH_EXECUTABLE="$CROOT/bin/ssh" ansible-playbook \
  -i inventory/hosts.yml playbooks/k3s-overlay-marks.yml \
  -e @"$CROOT/become.yml"
```

Default: audit only; require `operations: 0` on **all four** nodes before claiming
that the guard is converged. To install/update explicitly add
`-e k3s_overlay_marks_apply=true`. It affects only this owned guard service.
Use the audit after node provisioning, overlay changes or host NetBird upgrades.
Do not assume an IP migration or successful SSO proves NetworkPolicy enforcement.

## Live acceptance

After a socrat-0 canary, and again after all-four-node activation:

| Probe | Result |
|---|---|
| Ordinary untrusted pod on each of four nodes → RustFS Pod IP and ClusterIP, ports 9000/9001 | **16/16 blocked** |
| Same four pods with forged `app=rustfs-gateway`, but wrong namespace → same destinations/ports | **16/16 blocked** |
| Real gateway in `identity` → retained fixture using its mounted reader credentials and stock SigV4 reader | **45 bytes, exact SHA-256** |
| Real gateway → console 9001 | **blocked** |
| Header-only trace of unauthorized remote SYN | mark cleared, then **kube-router REJECT** |

Fixture SHA-256:
`973952a7d502a67bc652d5b67f104d0d6c1756bb4edb713e682e40f1b68e34f0`.

Probe pods were nonroot UID65534, unprivileged, no capabilities, no service-account
token, read-only root filesystem, ordinary pod networking, no mounted secrets.
They had no broadening egress policy. The temporary test namespace and tracing
table were removed. Verification scripts/header-only traces remain private
operational evidence, not a diagnostic bundle uploaded elsewhere.

Final observations: all nodes Ready; RustFS and gateway 1/1 with their original
pod names and zero restarts; Kubernetes `/readyz` OK; fresh SSH to all four nodes
via primary NetBird; recovery WireGuard disconnected; same Tunnelblick process
and sampled internet routes. Reapplying the guard playbook: changed=0 on all nodes.
Focused regression suite: **214 passed, 4 skipped, 138 subtests passed**;
Ansible syntax check passed. This is not a full repository test-suite claim.

No public RustFS/browser routes or SPI switching were activated. No S3 keys,
object permissions, artifacts or existing NetworkPolicies were changed. This
accepts the named network boundary, **not** the remaining browser/SSO/SPI rollout.
Existing established connections were not globally reset; this is not a forensic
claim that no one previously exercised the exposure, nor an exhaustive acceptance
of every application's policy after restoring cross-node enforcement.
