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

The playbook prepares ADB and a dedicated SSH key, checks the authorized TV model, and enables restoration of the last input. It also points Fully Kiosk Browser at the living-room dashboard. It does not bypass TV authorization, install Fully, or install the public key on a new television automatically.

## Fully Kiosk

Fully Kiosk Browser (`de.ozerov.fully`) is the living-room browser. `tv-admin.yml` writes its start URL and clears `injectJsCode`, then imports that pair through `/sdcard/fully-once-settings.json`. Fully reads the file on the next start and deletes it. The playbook allows `NO_ISOLATED_STORAGE` and `LEGACY_STORAGE` so that import can see shared storage, and it restarts Fully only when the settings file changes. Force another import with `-e homelab_tv_fully_reapply=true`.

The start URL is `https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light?kiosk=1&hideLogo=1`. `kiosk=1` hides Grafana navigation. `hideLogo=1` hides the kiosk footer. Leave `injectJsCode` empty: Fully treats injected JavaScript as a Plus feature and paints a “PLUS Features Activated” watermark.

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

Cold-power-cycle and TV reboot validation remain pending. The TV itself was not rebooted. User-selected sleep/power timeout settings were preserved. No rooting, launcher replacement, or custom startup application was needed.
