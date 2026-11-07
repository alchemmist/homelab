# Android TV administration

The television connected to socrat-0 is MiTV-MOOQ1, device/product `tarzan`, running Android 11 (API 30), build `RTM4.220307.164.8277 release-keys`.

Current LAN address: `192.168.0.19`. Confirm this address if the router changes its DHCP lease.

## Termux SSH

Termux user: `u0_a44`, TCP port `8022`. Key authentication from socrat-0 is configured and verified. The dedicated private key remains only on socrat-0 at `~/.ssh/homelab-tv`; the matching public key is installed in Termux `~/.ssh/authorized_keys`. No passwords or private keys belong in this repository.

From socrat-0:

```sh
ssh -i ~/.ssh/homelab-tv -p 8022 u0_a44@192.168.0.19
```

This shell runs as the Termux application account, not root or Android's ADB shell user. Android settings and TV input service access are restricted. SSH autostart after a TV reboot has not yet been configured or tested.

## ADB

ADB is installed on socrat-0. The TV reports `service.adb.tcp.port=5555`. The user enabled debugging and approved socrat-0. ADB authorization is verified; commands run as Android shell UID 2000.

From socrat-0:

```sh
adb connect 192.168.0.19:5555
adb devices -l
```

Preparation is captured in Ansible:

```sh
cd ansible
ansible-playbook playbooks/tv-admin.yml --ask-become-pass
```

## VPN switching and remote buttons

The retired internal `xiaomi-tv` tunnel/key has been deleted from the TV. Its exact server peer `10.250.0.8/32` is revoked in persistent/runtime WireGuard configuration, and removed from inventory. Other peers and recovery credentials are preserved, with no interface restart. Private historical backups are retained.

WireGuard remains installed with **only `alchemmist-tv`**, the existing global full-tunnel profile for YouTube. Its configuration/key are not read, replaced or deleted. BUTTON_16 still launches `xyz.alchemmist.tvmode`: connect this profile, wait for `VALIDATED`, then launch YouTube. BUTTON_11 still launches `xyz.alchemmist.grafana`: disconnect the global tunnel if active, wait for disconnect, then launch Fully **without bringing up a tunnel**. Both helper APKs retain their package/component identity and compatible signing certificate; their source no longer contains the internal tunnel or writes always-on VPN settings.

The TV always-on VPN app is cleared (lockdown off). `tv-admin.yml` preserves this on-demand design instead of restoring internal auto-connect. Android Private DNS remains `off`, as before; no Wi-Fi/global-profile DNS or routes are reconfigured. BUTTON_10/HDMI, BUTTON_14/Kinopoisk, Home and the private tvQuickActions button database are unchanged. Never reinstall/import the retired internal TV profile.

Live helper transitions were checked: YouTube foreground with a validated global VPN, followed by Fully foreground without a VPN network. Physical remote buttons and cold boot were not retested.

## Fully Kiosk

Fully Kiosk Browser (`de.ozerov.fully`) is the living-room browser. `tv-admin.yml` writes its start URL and clears `injectJsCode`, then imports those values through `/sdcard/fully-once-settings.json`. Fully reads the file on the next start and deletes it. The playbook allows `NO_ISOLATED_STORAGE` and `LEGACY_STORAGE` so that import can see shared storage, and it restarts Fully only when the settings file changes. Force another import with `-e homelab_tv_fully_reapply=true`.

The current start URL is `https://grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>?kiosk=1&hideLogo=1&autofitpanels=true&socratTv=1`. Only the `socrat-traffic-light` dashboard is natively shared; organization-wide anonymous access remains disabled. `tv-admin.yml` reads the approved URL from root-private `/var/lib/homelab-grafana-tv-public/fully-url.json` without changing its hostname. `kiosk=1` hides Grafana navigation. `hideLogo=1` hides the kiosk footer. Leave `injectJsCode` empty: Fully treats injected JavaScript as a Plus feature and paints a “PLUS Features Activated” watermark.

The same import sets `launchOnBoot`, `kioskMode`, `disableHome`, and `disableHomeButton` to false. Fully therefore does not cover the picture after power-on, and the Home button still opens the normal television launcher. Grafana's own `kiosk=1` is only the page chrome.

The 5px screen inset is not a Fully setting. The private Grafana gateway injects `charts/syncthing/files/traffic-light-inset.js` only for `/d/socrat-traffic-light`. That script is enabled by `trafficLightInset: true` on the grafana virtual host and is applied by `playbooks/syncthing-private-ui.yml`. `monitoring_wg_access` keeps the same flag when it rewrites the grafana host.

## Restore HDMI at startup

The inspected firmware exposes **Настройки → Настройки устройства → Входы → Не менять источник сигнала**. Its description says to retain the previous input after power-on or reboot. The setting is `Settings.Global.set_auto_play`: its original value was `0`; it is now `1`.

HDMI 1 maps to `com.mediatek.tvinput/.hdmi.HDMIInputService/HW4`. HDMI 1 was selected via the built-in TV application. This is a last-input policy, not a forced HDMI override: switching to a different input later can change what is restored. The separate `tv_auto_play_input` option controls playback when an input is connected and was left unchanged.

To explicitly select HDMI 1 during application:

```sh
ansible-playbook playbooks/tv-admin.yml --ask-become-pass -e homelab_tv_select_hdmi=true
```

To revert only source restoration:

```sh
adb -s 192.168.0.19:5555 shell settings put global set_auto_play 0
```

## What comes back after power is restored

Power-on shows the last television input. Fully does not start on boot, so an app that was open before the outage does not cover that input. While HDMI 1 stays the selected source, the server picture is what comes up. Home still opens `com.google.android.tvlauncher`. The colored remote buttons are handled by tvQuickActions (`dev.vodik7.tvquickactions.free`); its accessibility service is `KeyAccessibilityService`. Those button mappings live in the application's private data and are not rewritten by the playbook. The playbook only keeps the service enabled and stops `com.xiaomi.android.tvsetup.partnercustomizer` from claiming the same keys.

WireGuard on this television is the userspace VPN. Only `alchemmist-tv` remains, on demand for YouTube. The internal split-tunnel profile is retired. The boot receiver does not restore a userspace tunnel by itself; `tv-admin.yml` clears the always-on VPN app and leaves lockdown off. Fully, tvQuickActions, WireGuard, the Grafana and YouTube helpers, and the HDMI helper are kept on the standby whitelist.

The user verified a real power cycle: the server picture on HDMI 1 comes up, the colored buttons still switch between Grafana and HDMI, and Home still opens the normal launcher. Network ADB is only `service.adb.tcp.port=5555`; `persist.adb.tcp.port` cannot be set without root, so a reboot can drop the debugging connection until it is approved again.

## Public traffic-light closeout (2026-11-06)

- Native share creation/audit: `public-web-maintenance.yml -e public_web_maintenance_task=grafana-tv-public`; apply requires a fresh exact hash. Ownership, unchanged dashboard content, private receipts and uncertain-write stop are enforced. The old TV account/password are not used, changed or removed.
- The temporary `tv.alchemmist.xyz` alias is retired. `grafana-tv-dns.yml` now only removes that name after whole-fleet rendered-record equality checks; `retire-tv-public-alias.py` deletes only the exact owned Ingress/Certificate/Secret, with UID preconditions, private backups, fresh hash and uncertain-write stop. No blanket Argo prune.
- Native public scenes ignore the previous kiosk/autofit behavior. The **server-side** public policy asset `deploy/platform/grafana/public-entry/files/traffic-light-inset.js` restores the five-CSS-pixel inset, hides public header/footer and fits the compacted 24-column layout to the viewport. It validates the shared dashboard UID; it does not modify dashboard JSON or React internals. Raw gridPos can overlap: do not use it as the final rendered layout. Keep Fully JS injection empty (Plus watermark).
- The old private gateway asset/ConfigMap and Syncthing chart were deliberately left unchanged: a cosmetic public asset change must not restart the Syncthing writer.
- For an existing TV, **do not run full provisioning just to change its URL**. Audit `tv-public-dashboard.yml`; apply with `tv_public_apply=true` and the fresh `tv_public_hash`. It requires Fully already foreground and no pending import, changes only `startURL`, verifies consumption and unchanged TV DNS/VPN guard, and retains private before/after receipts. Stop on a `tv-uncertain.json` marker; do not blindly retry.
- The URL-only closeout preserves Fully scale 55%, font size 75%, desktop/kiosk/boot preferences and empty JS injection. The subsequent explicitly requested retirement updates only the two helper APKs, removes the internal TV profile and its server peer, and clears always-on VPN. Remote assignments, HDMI, Android Private DNS and the YouTube profile/key are preserved.
- Acceptance: real TV screenshot with populated live panels and no sign-in/Plus watermark; clean isolated browser with 51 panels, zero overlap, five-pixel inset, hidden footer and recurring native public queries; 24/24 focused verified-TLS two-IP checks, including denied generic/admin/datasource APIs, password/Basic auth and unknown share. These forced-routing checks are not an independent external-provider test. Physical remote buttons/power-cycle were not retested.
- Grafana/public-scene upgrades must recheck semantic DOM selectors, compacted layout and actual TV rendering. Current dashboard refresh remains 5s and stored range now-12h; publication does not change them.

The exact public address is device/private controller state rather than a hardcoded Git token. Anyone with that URL can read the dashboard and its displayed data; normal dashboards and administrative APIs retain native SSO/roles.

Rollback requires an explicit decision: disable only this owned native public share in Grafana (do not delete the dashboard, organization, PVC or existing accounts). If reverting the TV address is also wanted, import only the prior `startURL` after verifying the private baseline/receipts; do not rerun VPN/HDMI provisioning or replace passwords. A disabled/deleted/drifted share is not silently adopted or re-enabled by the audit helper.

### Internal-TV access retirement

`retire-tv-internal-wireguard.yml` audits all four nodes before serial apply. It accepts per-node fresh `tv_peer_hashes`, validates the exact public key/address/comment, retains root-private config backups and stops on uncertainty. Runtime removal uses `wg set ... peer <owned-key> remove`, not service/interface restart or broad sync. The old internal profile is deleted via the official WireGuard UI; never clear WireGuard app data, uninstall it or delete the YouTube profile to retire one key. The canonical public URL is now used by both TV playbooks and the focused public acceptance script.

Retirement closeout: all four node peer audits report operations=0 (three existing owned peers removed; worker already absent), all three authoritative DNS audits report operations=0, and the exact alias resource audit reports operations=0. At that historical closeout `public-web-entry` was Synced/Healthy; its resources now belong to their service Applications (see public-web-migration.md). Canonical public acceptance: 24/24 two-IP checks; 66 focused tests. The real TV displays live data on the canonical hostname with no active VPN network; YouTube's separate helper was verified foreground with one VALIDATED VPN before returning to Grafana. No physical button/power-cycle claim is implied.
