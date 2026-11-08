# VPN hardening — configuration-only phase, 8 November 2026

Issue [#83](https://github.com/alchemmist/homelab/issues/83) remains open.
Current [implementation/evidence/runbook](../docs/vpn-hardening-20261108.md).

## Budget and intent

Owner explicitly ruled out a new VPS, public IP or provider purchase. Work on
existing socrat-2 configuration and diagnostics. Original independent-ASN/P1 and
proxy/infrastructure-IP separation/P2 are deferred, not secretly provisioned or
claimed complete. No protocol settings defeat an actual destination-IP/prefix/ASN
block. Cause of the two reported blocks remains unproven; do not reclassify the
separate November7 watchdog fence as a demonstrated TSPU IP ban.

## Observed and implemented

- Fresh internal audit: 3x-ui3.11.0, Xray26.10.21, same pinned image, hostNetwork.
  Panel SQLite owns profiles; Argo owns workload/edge, not inbounds.
- 16 identities and85 inbound links, **not85 people**. Plaintext32063 has7 links;
  per-identity traffic rows do not prove per-inbound use or non-use.
- **32053 corrected via native API:** Yahoo SNI now matches Yahoo target. Verified
  fallback certificate/TLS1.3/H2 and an owned synthetic VLESS/XHTTP/REALITY client
  downloading65536 bytes before and after. Full semantic proxy comparison proved
  only target changed; SNI, keys, short IDs, flow, port and human records preserved.
  Same-node acceptance is not Russian ISP or every real-device acceptance.
- `scripts/vpn-hardening-inventory.py`: read-only consistent SQLite snapshot,
  WAL-aware backup, config hash, sanitized counts. Private backup checked under
  `/var/lib/homelab-vpn-hardening/20261108-phase1`, mode0700/files0600.
- `scripts/vpn-backend-audit.py`: default preview, explicit hash-gated root apply.
  ACCEPT-only passive table installed for12096/32087, no reject/drop/NAT/logging
  or persistence. Observed32087 on lo and wg-socrat;12096 still lacks samples.
  Exact nft1.0.6 readback validates expressions even when JSON omits table comments.
  Interrupted readback finalized without replay. No Xray/pod/node restart occurred.
- Panel18082 guard stays unchanged; its live nb-host allowance is absent in older
  Git rules. Never reinstall that old ruleset over live state as a side effect.
- `scripts/vpn-path-check.py`: bounded DNS/TCP/verified-TLS/complete-HTTPS stages,
  no credentials/retries/autorecovery/tunnel claim. Small workstation responses
  passed but did not qualify as >32KiB. Russian fixed/mobile and tunnel tests open.
- `deploy/vpn-hardening/policy.json` and `scripts/vpn-reality-plan.py` encode intent
  and strict preview, not runtime readiness or an executable SQL migration.

## Approved native access, clean teardown, remaining gates

Owner explicitly approved temporary machine API access. `vpn-panel-session.py`
checks new-name collisions, source version/image/UID and fresh hashes, uses native
CLI only for a uniquely named bootstrap, then TTL-limited admin-cleanup30min and
node-sync worker20min tokens. Actual data operations use node-sync. No SQL writes,
password/MFA reset or human credential impersonation. Native CLI bootstrap has no
TTL: interrupted creation must stop with private evidence, not blind replay.
`-getApiToken` must still NEVER be used as a credential read or on an existing name.

Two sessions ran: the first passed64KiB baseline then stopped before target save on
the modern nested-JSON DTO (now regression-covered); all its changes were cleaned.
The next fresh session completed. **Zero temporary tokens or synthetic client remain;
original two token rows, users and settings matched the pre-session backup.** Pod
remains Ready/restarts0; native Xray child reload is not a pod/node restart.
The post-change target plan is no-op. Private proof under
`/var/lib/homelab-vpn-hardening/vpn83-20261108-target-final`.

All seven plaintext links already have an enabled encrypted alternative; no new
port/listener is needed just to provide one. Configured subscription bases are HTTPS
on the expected hostname. Device/import compatibility and rendered subscriptions
are still unproven. Do not infer actual migration from server-side overlap counts.

Do not close32063 before compatible encrypted replacement/subscription refresh and
client acceptance. Do not enforce raw-backend rejects before consumer/source proof.
Keep WG/AWG peers, inter-node/recovery, NetBird, mandatory Tunnelblick, global routes/
DNS, production Traefik443 and TV profile unchanged. No magic padding/Vision on
XHTTP/gRPC, image bump, broad firewall flush or Argo sync/prune.

Research references/limits are in the linked runbook: net4people671 field anecdotes,
662 attribution withdrawal, Cloudflare2025 byte truncation, FOCI QUIC SNI abstract,
exact upstream Xray/3x-ui source, and incomplete Amnezia/image/PDF extraction.
Do not turn field hypotheses into proven classifiers or ban-prevention guarantees.
