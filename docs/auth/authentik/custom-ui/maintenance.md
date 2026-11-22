# Theme changes, rollback and upgrade checks

## 11. How to apply / roll back the theme

From `ansible/`:

```sh
ansible-playbook playbooks/authentik-branding.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e authentik_branding_action=apply
```

The default `prepare` is **not a read-only dry-run**: it copies and apply/verifies the static server,
but does not change Brand/flow settings. `apply` changes the reviewed presentation. No
IdP restart, DNS/WG modification or replacement authentication JS.

The private root `/home/alchemmist/.cache/homelab-authentik/`: `quiet-mono/`, a rendered
CSS/media map, `theme-backups/`, `quiet-mono-brand-journal.json`. The journal points to
the last pre-change snapshot; do not confuse the last CSS backup with the baseline of the whole rollout.

The full original baseline `theme-backups/quiet-mono-original-baseline.json` was assembled
from the earliest snapshots: the absence of a domain Brand, the old title/separate password/
eye settings. Use exactly it for a full rollback, not a later v5 backup:

```sh
ansible-playbook playbooks/authentik-branding.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e authentik_branding_action=rollback \
  -e authentik_branding_backup=/home/alchemmist/.cache/homelab-authentik/theme-backups/quiet-mono-original-baseline.json
```

The rollback is identity-guarded and does not delete static assets. A live rollback/reapply for
demonstration was deliberately not performed: do not interrupt the owner login just for a test.

## 12. Check and upgrade checklist

```sh
python3 -m unittest discover -s tests -p test_authentik_branding.py -v
python3 -m unittest discover -s tests -p test_authentik_flow_titles.py -v
# A Python environment with Playwright/Chromium; readonly, without fixture identities:
python3 scripts/identity-branding-controls-check.py --run
python3 scripts/identity-branding-controls-check.py --run --public-edge 109.120.141.97
```

The controls check uses a fresh anonymous context, requires an inspector API refusal and
a local-only native redirect challenge with a blocked benign `.invalid` target.
This is **not owner auth acceptance**, not fake API history and not server configuration.
It checks the real native components: geometry, contrast, font, arrow/hover,
reduced motion, focus and the click handler; it does not save sessions/screenshots.

The actual auth test is `identity-branding-smoke.py --run`: a temporary observer + native
TOTP/consent/Grafana, cleanup in finally. Do not touch real human factors.
The owner inspector was examined from the HTML they provided; do not take their browser
session and do not grant fixtures owner/debug privileges for a pretty screenshot.

Saved HTML **does not save all adopted shadow stylesheets**, so do not consider a
local render of the file an exact production screenshot. To analyze it, keep it
private, disable scripts/network, do not publish context/callback code/state.
Use the actual live DOM/computed style for visual acceptance.

Before a new Authentik release: an encrypted backup; a release-notes and schema-migration
review; a source diff of native components/parts/locale/redirect/inspector; staging/checks;
both edges, 320/390/desktop, password eye, invalid input, Tab, MFA, consent, anchor,
inspector denial, reduced motion and the owner existing-session check. Do not lift the version
guard before this check. After push, separately verify the actual rollout.
