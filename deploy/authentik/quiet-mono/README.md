# Socrat / Quiet Mono v5 — native Authentik branding

The owner-approved visual reference is frozen in [`reference/`](reference/), with file sizes and SHA-256 in `reference/manifest.json`. Open `reference/05-typewriter.html` locally for the reference; do not use its demonstration JavaScript as a production authentication implementation.

Production target: **Authentik 2026.8.5**, **https://auth.socrat.alchemmist.xyz/**. Current parity and outstanding owner acceptance are in [ACCEPTANCE.md](ACCEPTANCE.md).

## Implementation

- `theme.css`: native Brand CSS, injected through Authentik's own mechanism. Uses supported drawer parts plus version-specific shadow-root selectors. The latter must be reviewed on upgrade; reconciliation refuses an unreviewed version.
- `assets.json`: seven checksum-pinned public images/fonts from the approved reference. No session data or credentials.
- `static-image.json`: digest-pinned non-root nginx image provenance.
- `ansible/roles/authentik/files/branding_static.py`: deterministic ConfigMap/Deployment/Service/Ingress renderer. CLI emits separate YAML documents (JSON is a YAML subset), preserving kubectl Strict OpenAPI-v3 validation instead of a `List` wrapper's OpenAPI-v2 fallback. Use server-side apply: client-side last-applied annotations exceed the annotation-size limit for this asset bundle.
- `ansible/roles/authentik/files/branding.py`: prepare/apply/rollback with asset digest checks over verified HTTPS, domain-specific Brand, protected pre-change backups and identity guards. Native combined identification/password and eye settings are the only stage presentation changes.
- `ansible/playbooks/authentik-branding.yml`: explicit separate rollout, defaulting to `prepare`. It does not restart/upgrade Authentik, alter DNS/WireGuard or modify application OIDC providers.

Do not persist Authentik media API signed URLs in CSS. They expire, unlike the content-hashed paths below.

### Static endpoint

`https://auth.socrat.alchemmist.xyz/-/quiet-mono/v1/<sha256-prefix>-<filename>`

The endpoint serves only the explicitly reviewed `.webp`, `.svg` and `.woff2` files, with immutable caching and `nosniff`. It shares the existing TLS secret and domain, not an external CDN. Ingress matches only this prefix; native login, executor, token and API routes continue to the IdP.

Static deployment: namespace `identity`, name `socrat-authentik-theme`, node `socrat-0`, one replica; 5m/16Mi requests, 100m/64Mi limits. Read-only filesystem, non-root, dropped capabilities, no privilege escalation or mounted service-account token, bounded `/tmp`. This is **not HA**; loss of the node can affect branding, and the IdP itself is also single-node.

## Reconcile

Run from `ansible/` using the existing owner SSH identity and protected server-side deployment credentials. Never print or pass the bootstrap token on the command line.

```sh
ansible-playbook playbooks/authentik-branding.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e authentik_branding_action=apply
```

Without `authentik_branding_action=apply`, the playbook copies/verifies the bundle and reconciles only the isolated static server; it does not change the Brand or flow settings. `prepare` is not an entirely read-only cluster dry run.

The public-edge override applies only to this process's DNS resolution. Certificate and hostname verification stay enabled. Other nodes, system DNS and WireGuard are unchanged.

## Recovery / rollback

Backups and journal are private (`0700` directories / `0600` files) under:

- `/home/alchemmist/.cache/homelab-authentik/theme-backups/`
- `/home/alchemmist/.cache/homelab-authentik/quiet-mono-brand-journal.json`

The journal identifies the last changed Brand and its preceding backup. To undo **the entire initial rollout**, the current installation also has `theme-backups/quiet-mono-original-baseline.json`, assembled from the earliest retained pre-theme snapshots: no domain-specific Brand, original flow title, separate password stage and original eye setting. Do not replace it with a later v5-to-v5 backup.

```sh
ansible-playbook playbooks/authentik-branding.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e authentik_branding_action=rollback \
  -e authentik_branding_backup=/home/alchemmist/.cache/homelab-authentik/theme-backups/quiet-mono-original-baseline.json
```

Rollback checks the Brand UUID before deleting/restoring it, restores only the changed native presentation fields and requires no browser session or owner MFA reset. It retains the harmless static server and old immutable asset ConfigMaps for recovery; cleanup is a separate explicit action after acceptance. Rollback logic is present, but a live rollback/reapply interruption has **not** been performed solely as a test.

## Checks

Offline:

```sh
python3 -m unittest discover -s tests -p test_authentik_branding.py -v
cd ansible && ansible-playbook playbooks/authentik-branding.yml --syntax-check
```

Explicit live acceptance (Python with Playwright/Chromium, owner SSH access):

```sh
python3 scripts/identity-branding-smoke.py --run
# Optional: run through the other trusted public edge.
python3 scripts/identity-branding-smoke.py --run --public-edge 176.98.185.59
```

This creates a random temporary observer, sets only that fixture's password, enrolls a real temporary TOTP in the native browser UI, accepts native consent, verifies its Grafana identity is not server admin, checks observer inspection is denied, and removes the Authentik/Grafana fixtures in `finally`. No real human password/MFA is read or reset. No QR, TOTP seed, callback URLs, screenshots or browser session traces are saved.

The owner's actual inspector/history acceptance remains pending: do not create a fake owner MFA or grant inspection to ordinary users to make a screenshot possible. Static login can be reviewed in a private browser window; an existing authenticated session may go directly to the application library.

### Neutral authorization transition title

`flow_titles.py` reconciles only the `title` field of the default explicit/implicit provider authorization flows to `Redirecting`. It saves the first pre-change titles and flow IDs to protected `authorization-flow-titles-original.json` in the deployment directory. Branding apply/rollback invokes this helper; it does not change stage bindings, policies, MFA, redirects, consent or spinner behavior. This replaces the raw `%(app)s` placeholder seen on the transient screen.
