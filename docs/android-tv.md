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

The TV uses one WireGuard app with two mutually exclusive profiles:

| Profile | Purpose | Expected tunnel address |
| --- | --- | --- |
| `xiaomi-tv` | Split-tunnel access to Grafana and the homelab | `10.250.0.8` |
| `alchemmist-tv` | Full-tunnel global internet access for YouTube | `10.0.0.10` |

The global profile is imported from the private client configuration supplied as `tv.conf`. Keep its private key out of this repository and Ansible inventory. On a replacement TV, securely copy the file to the TV, import it in WireGuard, and name the profile `alchemmist-tv`. The homelab profile must be named `xiaomi-tv`.

tvQuickActions (`dev.vodik7.tvquickactions.free`) opens the local helper apps, which own the VPN handoff:

| Button | Helper | Sequence |
| --- | --- | --- |
| BUTTON_11 | `xyz.alchemmist.grafana` | Stop both WireGuard profiles, start `xiaomi-tv`, wait for Android network validation, then open Fully Kiosk |
| BUTTON_16 | `xyz.alchemmist.tvmode` | Stop both profiles, start `alchemmist-tv`, wait for validation, close Fully from the foreground, then open YouTube |
| BUTTON_10 | `xyz.alchemmist.hdmi` | Select HDMI 1 |
| BUTTON_14 | `ru.kinopoisk.tv` | Open Kinopoisk |

The same WireGuard client is used for both routes because Android permits only one active `VpnService` tunnel at a time. The helper does not identify the current profile by the generic Android VPN network; it explicitly requests both profiles down before bringing the desired one up. The WireGuard remote-control permission must remain granted to both helpers. Android's always-on VPN application remains `com.wireguard.android`, with lockdown disabled. Happ has been removed and the Ansible playbook removes it if it is reinstalled.

Android Private DNS is set to `off` by `tv-admin.yml`. With Private DNS in automatic mode, YouTube's Cronet requests failed with `ERR_NAME_NOT_RESOLVED` over the global tunnel; the affected host resolved after Private DNS was disabled. Each WireGuard profile still supplies its own DNS resolver, and while the VPN is active those DNS packets travel inside the encrypted tunnel. When no VPN is active, DNS uses the current Wi-Fi network without Android DoT.

The TV profile configuration and tvQuickActions button database are private device state. Neither is recreated from this repository: after importing profiles on a replacement TV, assign BUTTON_11 and BUTTON_16 to the corresponding helper apps in tvQuickActions. Never map those buttons directly to Fully or YouTube, because that bypasses tunnel selection.

The playbook prepares ADB and a dedicated SSH key, checks the authorized TV model, and enables restoration of the last input. It points Fully Kiosk Browser at the living-room dashboard without starting it on boot, keeps the TV helpers alive across reboot, removes Happ, and sets WireGuard as the always-on VPN with lockdown off. It does not bypass TV authorization, install Fully, tvQuickActions, WireGuard, or the HDMI helper, and it does not install the public key on a new television automatically.

## Fully Kiosk

Fully Kiosk Browser (`de.ozerov.fully`) is the living-room browser. `tv-admin.yml` writes its start URL and clears `injectJsCode`, then imports those values through `/sdcard/fully-once-settings.json`. Fully reads the file on the next start and deletes it. The playbook allows `NO_ISOLATED_STORAGE` and `LEGACY_STORAGE` so that import can see shared storage, and it restarts Fully only when the settings file changes. Force another import with `-e homelab_tv_fully_reapply=true`.

The current start URL is `https://tv.alchemmist.xyz/public-dashboards/<accessToken>?kiosk=1&hideLogo=1&autofitpanels=true&socratTv=1`. Only the `socrat-traffic-light` dashboard is natively shared; organization-wide anonymous access remains disabled. `tv-admin.yml` reads the approved URL from root-private `/var/lib/homelab-grafana-tv-public/fully-url.json`, replacing the canonical Grafana hostname with `tv.alchemmist.xyz` to avoid the TV’s legacy private DNS path without reconfiguring its VPN or DNS. `kiosk=1` hides Grafana navigation. `hideLogo=1` hides the kiosk footer. Leave `injectJsCode` empty: Fully treats injected JavaScript as a Plus feature and paints a “PLUS Features Activated” watermark.

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

WireGuard on this television is the userspace VPN. `xiaomi-tv` is split-tunnel, so the homelab network uses it and ordinary traffic stays on Wi-Fi. `alchemmist-tv` is full-tunnel for YouTube. The boot receiver does not restore the userspace tunnel by itself; `tv-admin.yml` sets WireGuard as the always-on VPN app and leaves lockdown off. Fully, tvQuickActions, WireGuard, the Grafana and YouTube helpers, and the HDMI helper are kept on the standby whitelist.

The user verified a real power cycle: the server picture on HDMI 1 comes up, the colored buttons still switch between Grafana and HDMI, and Home still opens the normal launcher. Network ADB is only `service.adb.tcp.port=5555`; `persist.adb.tcp.port` cannot be set without root, so a reboot can drop the debugging connection until it is approved again.

## Public traffic-light closeout (2026-11-06)

- Native share creation/audit: `public-web-maintenance.yml -e public_web_maintenance_task=grafana-tv-public`; apply requires a fresh exact hash. Ownership, unchanged dashboard content, private receipts and uncertain-write stop are enforced. The old TV account/password are not used, changed or removed.
- Public `tv.alchemmist.xyz` A records follow the existing HOME/VPS health selection. `grafana-tv-dns.yml` preflights rendered-record equality for the whole authoritative fleet and refreshes only the owned zone, without DNS service restarts.
- Native public scenes ignore the previous kiosk/autofit behavior. The **server-side** public policy asset `charts/public-web-entry/files/traffic-light-inset.js` restores the five-CSS-pixel inset, hides public header/footer and fits the compacted 24-column layout to the viewport. It validates the shared dashboard UID; it does not modify dashboard JSON or React internals. Raw gridPos can overlap: do not use it as the final rendered layout. Keep Fully JS injection empty (Plus watermark).
- The old private gateway asset/ConfigMap and Syncthing chart were deliberately left unchanged: a cosmetic public asset change must not restart the Syncthing writer.
- For an existing TV, **do not run full provisioning just to change its URL**. Audit `tv-public-dashboard.yml`; apply with `tv_public_apply=true` and the fresh `tv_public_hash`. It requires Fully already foreground and no pending import, changes only `startURL`, verifies consumption and unchanged TV DNS/VPN guard, and retains private before/after receipts. Stop on a `tv-uncertain.json` marker; do not blindly retry.
- Existing Fully scale 55%, font size 75%, desktop/kiosk/boot preferences, APKs, remote buttons, VPN profiles, HDMI and Android Private DNS were not configured by the URL-only closeout.
- Acceptance: real TV screenshot with populated live panels and no sign-in/Plus watermark; clean isolated browser with 51 panels, zero overlap, five-pixel inset, hidden footer and recurring native public queries; 24/24 focused verified-TLS two-IP checks, including denied generic/admin/datasource APIs, password/Basic auth and unknown share. These forced-routing checks are not an independent external-provider test. Physical remote buttons/power-cycle were not retested.
- Grafana/public-scene upgrades must recheck semantic DOM selectors, compacted layout and actual TV rendering. Current dashboard refresh remains 5s and stored range now-12h; publication does not change them.

The exact public address is device/private controller state rather than a hardcoded Git token. Anyone with that URL can read the dashboard and its displayed data; normal dashboards and administrative APIs retain native SSO/roles.

Rollback requires an explicit decision: disable only this owned native public share in Grafana (do not delete the dashboard, organization, PVC or existing accounts). If reverting the TV address is also wanted, import only the prior `startURL` after verifying the private baseline/receipts; do not rerun VPN/HDMI provisioning or replace passwords. A disabled/deleted/drifted share is not silently adopted or re-enabled by the audit helper.
