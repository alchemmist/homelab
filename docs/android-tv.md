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

The start URL is `https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light?kiosk=1&hideLogo=1`. `kiosk=1` hides Grafana navigation. `hideLogo=1` hides the kiosk footer. Leave `injectJsCode` empty: Fully treats injected JavaScript as a Plus feature and paints a “PLUS Features Activated” watermark.

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
