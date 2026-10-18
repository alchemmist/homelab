# Public ingress through two addresses

Public cluster HTTP services have two entrance addresses: home `109.173.40.247` and VPS `176.98.185.59`. REG.RU is configured with two A records for each of these 15 names:

| Name | Current application placement |
| --- | --- |
| `alchemmist.xyz`, `www.alchemmist.xyz` | Blog replicas on socrat-0 and socrat-3 |
| `cats.alchemmist.xyz` | Both replicas on socrat-0 |
| `fq.alchemmist.xyz`, `img.alchemmist.xyz` | socrat-0 |
| `llm.alchemmist.xyz`, `chat.alchemmist.xyz` | socrat-0; model and database dependencies also at home |
| `lms.alchemmist.xyz`, `monori.alchemmist.xyz`, `umami.alchemmist.xyz` | socrat-0 |
| `remark42.alchemmist.xyz`, `status.alchemmist.xyz` | socrat-2 |
| `socrat.alchemmist.xyz` | socrat-1 and socrat-3 |
| `wiki.alchemmist.xyz` | socrat-3 |
| `vpn.alchemmist.xyz` | socrat-2 |

Placement is the observed baseline on 2026-10-18, not a scheduling guarantee. Most applications still have a single site or persistent-volume dependency. Two entrance addresses do not replicate application state or make every service survive the loss of its backend site. In particular, Kuma and VPN still depend on socrat-2, and local GPU inference depends on socrat-0.

Both Traefik controllers consume the shared `traefik` ingress class. The VPS controller watches an explicit list of public application namespaces. They use the same ingress resources, service endpoints and TLS Secrets. The VPN ingress also uses the shared class so its HTTPS routes work through either entrance. Connections from home to the VPN backend still require the VPS. Non-HTTP VPN ports are not covered by this HTTP ingress setup.

Certificate ownership remains with cert-manager. Native HTTP-01 solver ingresses must be visible to both controllers so ACME validation can reach a challenge through either address. Existing certificate Secrets are reused; certificates must not be copied manually into a second independently renewed setup.

The VPS HTTPS entry point enables TLS by default, matching the home controller. The home controller remains responsible for ingress status updates; the VPS controller has no status-write permission. Adding a public application namespace requires updating `charts/traefik-edge/values.yaml` before publishing its second address.

All 15 active primary VPN subscriptions were checked during deployment: transport destinations use the literal VPS address, including Trojan, VLESS, WireGuard and AmneziaWG. The hostname serves HTTPS subscription and panel requests. Compatibility subscriptions were not independently verified. Manually configured clients must not use the dual-address hostname for non-HTTPS ports that are available only on the VPS.

## Apply and verify

Run the managed edge deployment from the Ansible directory:

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml playbooks/vpn-edge.yml --ask-become-pass
```

Before adding DNS records, verify both addresses directly from the repository root:

```sh
python3 scripts/check-public-ingress.py
```

The checker uses `curl --resolve` with certificate validation enabled and at most four concurrent requests. It checks all 15 names at both addresses, including dedicated health paths for Remark42, LiteLLM and the status page. The VPN root intentionally returns 404; this check confirms TLS and the established HTTP baseline, not a successful VPN tunnel. The checker does not change DNS, send inference requests or access authenticated endpoints.

After saving the records in REG.RU, also check the authoritative server:

```sh
python3 scripts/check-public-ingress.py --check-dns
```

No external-dns or automatic DNS failover controller manages these records. Both addresses remain published during a failure. Clients choose an address and may retry another after a connection failure; HTTP error responses and interrupted requests do not guarantee a retry. Application clients need suitable connection timeouts and safe retry behavior.

Before this change, the authoritative TTL was 86400 seconds. Resolvers can retain the previous single address for up to that period after their last lookup. Lowering TTL does not invalidate existing caches. DNS propagation is separate from trying alternate addresses already present in a cached answer.

## Excluded names

Rancher, Grafana, private LLM aliases and numbered Syncthing interfaces remain private to socrat-wg. A public wildcard record is not authorization to expose those services; do not expand the VPS namespace allowlist to their private gateways.

The wiki is intentionally public under its current runtime configuration, with authenticated editing; it is included above. Its separate WireGuard route does not make the public hostname private.

`quality-graph.xyz`, `lazy-tmux.xyz`, `devsyringe.xyz` and `obscuravim.xyz` are served by GitHub Pages, with the four existing `185.199.108.153` through `185.199.111.153` addresses. They have no cluster ingress and are excluded. Node SSH names, WireGuard endpoint names, mail records and other non-HTTP services must retain their individual routing.
