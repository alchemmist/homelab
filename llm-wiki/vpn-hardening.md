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
- Yahoo SNI / Intel target mismatch on32053 persists. Yahoo target tested from VPS:
  valid certificate, TLS1.3/H2. Source-controlled target-only preview is ready;
  **not applied**. Do not change SNI, keys, short IDs, flow or port incidentally.
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

## Next gate, not an invitation to bypass auth

API tokens in this panel are SHA-256 hashes. `x-ui -getApiToken` **rotates/recreates**
a named token; do not run it to retrieve an existing credential. Existing token
plaintext was not provided. No new token or password/MFA reset was performed.
Obtain a private existing machine token or explicit approval for separately named
temporary automation credentials with cleanup. Upstream node-sync scope permits
inbound operations; full admin is not required for the actual inbound edit.
Then native API target-only save, fresh hash/backup, authenticated client acceptance
and unchanged rendered links. Saving an inbound can reload all Xray listeners.

Do not close32063 before compatible encrypted replacement/subscription refresh and
client acceptance. Do not enforce raw-backend rejects before consumer/source proof.
Keep WG/AWG peers, inter-node/recovery, NetBird, mandatory Tunnelblick, global routes/
DNS, production Traefik443 and TV profile unchanged. No magic padding/Vision on
XHTTP/gRPC, image bump, broad firewall flush or Argo sync/prune.

Research references/limits are in the linked runbook: net4people671 field anecdotes,
662 attribution withdrawal, Cloudflare2025 byte truncation, FOCI QUIC SNI abstract,
exact upstream Xray/3x-ui source, and incomplete Amnezia/image/PDF extraction.
Do not turn field hypotheses into proven classifiers or ban-prevention guarantees.
