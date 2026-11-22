# Theme changes, rollback and upgrade checks

## 11. Как применить / откатить theme

Из `ansible/`:

```sh
ansible-playbook playbooks/authentik-branding.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e authentik_branding_action=apply
```

Default `prepare` **не read-only dry-run**: копирует и apply/verifies static server,
но не меняет Brand/flow settings. `apply` меняет reviewed presentation. Никакого
IdP restart, DNS/WG modification или replacement authentication JS.

Private root `/home/alchemmist/.cache/homelab-authentik/`: `quiet-mono/`, rendered
CSS/media map, `theme-backups/`, `quiet-mono-brand-journal.json`. Journal указывает
последний pre-change snapshot; не путать последний CSS backup с baseline всего rollout.

Полный original baseline `theme-backups/quiet-mono-original-baseline.json` собран
из самых ранних snapshots: отсутствие domain Brand, старые title/separate password/
eye settings. Для полного rollback использовать именно его, не более поздний v5 backup:

```sh
ansible-playbook playbooks/authentik-branding.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e authentik_branding_action=rollback \
  -e authentik_branding_backup=/home/alchemmist/.cache/homelab-authentik/theme-backups/quiet-mono-original-baseline.json
```

Rollback identity-guarded и не удаляет static assets. Live rollback/reapply ради
демонстрации намеренно не выполнялся: не прерывать owner login только ради теста.

## 12. Проверка и upgrade checklist

```sh
python3 -m unittest discover -s tests -p test_authentik_branding.py -v
python3 -m unittest discover -s tests -p test_authentik_flow_titles.py -v
# Python environment с Playwright/Chromium; readonly, без fixture identities:
python3 scripts/identity-branding-controls-check.py --run
python3 scripts/identity-branding-controls-check.py --run --public-edge 109.120.141.97
```

Controls check использует fresh anonymous context, требует отказ inspector API и
local-only native redirect challenge с заблокированным benign `.invalid` target.
Это **не owner auth acceptance**, не fake API history и не server configuration.
Проверяет реальные native components: geometry, контраст, font, arrow/hover,
reduced motion, focus и click handler; не сохраняет sessions/screenshots.

Actual auth test — `identity-branding-smoke.py --run`: временный observer + native
TOTP/consent/Grafana, cleanup в finally. Реальные человеческие factors не трогать.
Owner inspector осматривался по предоставленным им HTML; не брать его browser
session и не выдавать fixtures owner/debug privileges для красивого screenshot.

Saved HTML **не сохраняет все adopted shadow stylesheets**, поэтому не считать
локальный рендер файла точной production screenshot. Для анализа держать его
private, отключить scripts/network, не публиковать context/callback code/state.
Использовать фактический live DOM/computed style для визуальной приёмки.

Перед новым Authentik release: encrypted backup; release notes и schema migration
review; source diff native components/parts/locale/redirect/inspector; staging/checks;
оба edges, 320/390/desktop, password eye, invalid input, Tab, MFA, consent, anchor,
inspector denial, reduced motion и owner existing-session check. Не снимать version
guard прежде этой проверки. После push отдельно проверить фактический rollout.
