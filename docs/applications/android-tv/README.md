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

The inspected firmware exposes **Settings → Device settings → Inputs → Do not change signal source** (the TV's UI string is in Russian on this firmware). Its description says to retain the previous input after power-on or reboot. The setting is `Settings.Global.set_auto_play`: its original value was `0`; it is now `1`.

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
- The temporary `tv.alchemmist.xyz` alias is retired. Its DNS records and alias-specific Kubernetes resources were removed; TV provisioning uses the canonical Grafana hostname.
- Native public scenes ignore the previous kiosk/autofit behavior. The **server-side** public policy asset `deploy/platform/grafana/public-entry/files/traffic-light-inset.js` restores the five-CSS-pixel inset, hides public header/footer and fits the compacted 24-column layout to the viewport. It validates the shared dashboard UID; it does not modify dashboard JSON or React internals. Raw gridPos can overlap: do not use it as the final rendered layout. Keep Fully JS injection empty (Plus watermark).
- The old private gateway asset/ConfigMap and Syncthing chart were deliberately left unchanged: a cosmetic public asset change must not restart the Syncthing writer.
- For an existing TV, **do not run full provisioning just to change its URL**. Audit `tv-public-dashboard.yml`; apply with `tv_public_apply=true` and the fresh `tv_public_hash`. It requires Fully already foreground and no pending import, changes only `startURL`, verifies consumption and unchanged TV DNS/VPN guard, and retains private before/after receipts. Stop on a `tv-uncertain.json` marker; do not blindly retry.
- The URL-only closeout preserves Fully scale 55%, font size 75%, desktop/kiosk/boot preferences and empty JS injection. The subsequent explicitly requested retirement updates only the two helper APKs, removes the internal TV profile and its server peer, and clears always-on VPN. Remote assignments, HDMI, Android Private DNS and the YouTube profile/key are preserved.
- Acceptance: real TV screenshot with populated live panels and no sign-in/Plus watermark; clean isolated browser with 51 panels, zero overlap, five-pixel inset, hidden footer and recurring native public queries; 24/24 focused verified-TLS two-IP checks, including denied generic/admin/datasource APIs, password/Basic auth and unknown share. These forced-routing checks are not an independent external-provider test. Physical remote buttons/power-cycle were not retested.
- Grafana/public-scene upgrades must recheck semantic DOM selectors, compacted layout and actual TV rendering. Current dashboard refresh remains 5s and stored range now-12h; publication does not change them.

The exact public address is device/private controller state rather than a hardcoded Git token. Anyone with that URL can read the dashboard and its displayed data; normal dashboards and administrative APIs retain native SSO/roles.

Rollback requires an explicit decision: disable only this owned native public share in Grafana (do not delete the dashboard, organization, PVC or existing accounts). If reverting the TV address is also wanted, import only the prior `startURL` after verifying the private baseline/receipts; do not rerun VPN/HDMI provisioning or replace passwords. A disabled/deleted/drifted share is not silently adopted or re-enabled by the audit helper.

### Internal-TV access retirement

The one-time fleet peer removal is complete; it is not part of TV provisioning or recovery. Preserve the private per-node configuration backups. Never clear WireGuard app data, uninstall it or delete the separate YouTube profile. Both TV playbooks and the focused public acceptance script use the canonical public URL.

Retirement closeout: all four node peer audits report operations=0 (three existing owned peers removed; worker already absent), all three authoritative DNS audits report operations=0, and the exact alias resource audit reports operations=0. At that historical closeout `public-web-entry` was Synced/Healthy; its resources now belong to their service Applications (see public-web-migration.md). Canonical public acceptance: 24/24 two-IP checks; 66 focused tests. The real TV displays live data on the canonical hostname with no active VPN network; YouTube's separate helper was verified foreground with one VALIDATED VPN before returning to Grafana. No physical button/power-cycle claim is implied.

## Living room: the TV as a monitor and a Grafana traffic light

Snapshot for **November 6, 2026** (the remote/cold boot were checked by the user on
October 22). A memo on how the living-room Xiaomi is set up and what survives a
power loss. The operational instructions in English:
`docs/applications/android-tv/README.md`. The playbook:
`ansible/playbooks/tv-admin.yml`. This is not a replacement for a live check: the
DHCP address may change.

The overall VPS/DNS/NetBird/Mac/public-access summary:
[network-access.md](../../network/README.md). This TV setup is the final version
after removing the temporary TV domain and the internal WG, not an intermediate
publication.

## Why it is needed

Two roles that must be switchable with one button:

1. Server monitor. The picture comes over HDMI 1.
2. The Grafana traffic-light panel in a browser. Kinopoisk and YouTube remain an
ordinary television: the Home button opens the stock launcher, and they can be
started from there as usual.

After power-on, the last source comes up by itself. While that is HDMI 1, the
server picture appears on screen immediately. Grafana does not take over the
screen by itself. You switch to it with a colored remote button when needed.

The user verified a real power-off and power-on: HDMI, both colored buttons and
Home behave as described below.

## Hardware and access

| | |
| --- | --- |
| Model | MiTV-MOOQ1, device `tarzan`, Android 11 |
| LAN | `192.168.0.19`, screen 1920×1080 |
| ADB | from socrat-0: `adb connect 192.168.0.19:5555`, port `service.adb.tcp.port=5555` |
| Termux SSH | `u0_a44`, port `8022`, the key only on socrat-0: `~/.ssh/homelab-tv` |

ADB is shell UID 2000, not root. `persist.adb.tcp.port` cannot be set without
root, so after a cold reboot network debugging may not return until it is
allowed again on the TV. Termux SSH autostart is not configured.

The playbook installs `adb` on socrat-0, sets up the key, checks the model and
brings the settings below to the described state. It installs no applications
and does not bypass the debugging confirmation. The applications are already
installed manually.

```sh
cd ansible
ansible-playbook playbooks/tv-admin.yml --ask-become-pass
```

To force-select HDMI 1 in this run: `-e homelab_tv_select_hdmi=true`. To re-push
the Fully start URL: `-e homelab_tv_fully_reapply=true`.

## The remote

The colored buttons are neither a firmware setting nor a Git record. They are
intercepted by **tvQuickActions** (`dev.vodik7.tvquickactions.free`, build
`3.3.2-free`), the `KeyAccessibilityService` accessibility service. While the
service is enabled, pressing the physical button does not go to Kinopoisk, Okko
or IVI but runs the action from the application's private database.

The Xiaomi system application `com.xiaomi.android.tvsetup.partnercustomizer` is
disabled. If it is enabled, it will grab these keys again: tvQuickActions will
stop opening and seeing presses. The playbook keeps it disabled and re-enables
the accessibility service if it was reset. It does not rewrite the
“button → action” rows themselves.

Home is not part of this. It is a system button; the launcher remains
`com.google.android.tvlauncher`. Kinopoisk and YouTube still start from it. Do
not make Fully the home screen.

### What is assigned right now

Single press. Double and long presses exist in the application but are not used
on these buttons.

| Button | Android code | Action |
| --- | --- | --- |
| BUTTON_11 | 198 | open `xyz.alchemmist.grafana` (“Grafana”): disconnect the YouTube VPN if enabled, and open the public traffic light in Fully Kiosk without bringing up a VPN |
| BUTTON_10 | 197 | open `xyz.alchemmist.hdmi`, which is HDMI 1 |
| BUTTON_14 | 201 | open Kinopoisk (`ru.kinopoisk.tv`) |
| BUTTON_16 | 203 | open `xyz.alchemmist.tvmode` (“YouTube VPN”): switch WireGuard to the `alchemmist-tv` profile for the global network and open YouTube |
| Home | — | the stock launcher; tvQuickActions does not catch it |

All assigned shortcuts are set as “open an application”, not as a shell command.
So they live without network debugging. The `xyz.alchemmist.grafana` helper
disconnects only `alchemmist-tv`, waits for the VPN network to disappear and
opens Fully with the saved public URL. It connects no tunnel. `xyz.alchemmist.hdmi`
selects HDMI 1. The `xyz.alchemmist.tvmode` helper connects the single remaining
profile `alchemmist-tv`, waits for `VALIDATED` and opens YouTube. The settings/key
of that global profile were not changed. Both helper APKs are updated with the
compatible old signature and no longer contain `xiaomi-tv` or always-on VPN
writes. The button assignments were not rewritten.

### Helper sources and installation

The YouTube and Grafana sources are Smali code with manifests in
`deploy/tv/android/tv-mode/` and `deploy/tv/android/tv-grafana/`. They can be
rebuilt on a machine with Java via `./deploy/tv/android/build.sh`: Apktool and
uber-apk-signer are pinned by version and SHA-256; the script verifies that the
signature is compatible with the APKs installed on the TV. The APKs go into
`deploy/tv/android/releases/`. `tv-hdmi.apk` is the saved original signed APK:
the HDMI helper's original signing key is absent from the repository.

The playbook `ansible/playbooks/tv-admin.yml` installs/updates all three
homelab helpers and grants the VPN/secure-settings permissions, keeps the
needed applications on the standby whitelist and removes Happ. It does not
install Fully, tvQuickActions or WireGuard. WireGuard profiles are imported on
the TV manually; their private keys are not stored in the repository. The
playbook also does not rewrite tvQuickActions' private button-assignment
database — those are set manually per the instructions above.

BUTTON_16 only needs the free tvQuickActions “open application” action →
`YouTube VPN`. Paid macros, ADB commands and custom actions are not used. You
must not assign the button directly to YouTube: then the VPN would not switch
before it launches.

HDMI 1 is `com.mediatek.tvinput/.hdmi.HDMIInputService/HW4` to the firmware. The
**Do not change signal source** setting is
`settings get global set_auto_play`, value `1`. This is a last-input memory, not
a hard binding to HDMI: if a different source was selected before power-off, that
one returns after power-on.

### How to change it

Change it inside tvQuickActions itself, with the remote. It is not committed to
Git: the database lives in the application's private data and survives reboots.
Re-running `tv-admin.yml` does not erase the assignments.

1. Home, then the application list, open tvQuickActions. You cannot open it with
a colored button: that is already taken by an action.
2. Press the button you want to reassign on the remote. The application will
show it as the current one.
3. Set the single-press action. For Grafana — launch `Grafana`
(`xyz.alchemmist.grafana`), not Fully directly. For HDMI — `xyz.alchemmist.hdmi`.
For YouTube — `YouTube VPN` (`xyz.alchemmist.tvmode`), not YouTube directly.
Double and long press can be assigned separately if a second action on the same
button is needed.
4. Exit and check with a physical press. `adb shell input keyevent` does not
exercise the accessibility service: computer input may not reach tvQuickActions
even though the remote works.

A new free colored button is assigned the same way: open the application and
press it. The free build is installed. If it will not let you add another
button, that is the limit of this build, not of the playbook.

The application also has other action types: intent, menu, ADB command. For
these assignments an application launch is enough; an ADB command depends on
debugging, and network debugging may not return after a power-off.

If a button must open the traffic light, the target is Fully, not an address in
an ordinary browser. The scale, the `tv` login and the kiosk mode are stored in
Fully. If a button must return the server picture, the target is
`xyz.alchemmist.hdmi`. For YouTube with VPN the target is the `YouTube VPN`
application; it performs the tunnel switch itself. The same HDMI input without
the helper, should the application have to be set up again:

```sh
am start -n com.mediatek.wwtv.tvcenter/com.mitv.livetv.tv.MainActivity \
  -a android.intent.action.VIEW \
  -t vnd.android.cursor.item/channel \
  -d content://android.media.tv/passthrough/com.mediatek.tvinput%2F.hdmi.HDMIInputService%2FHW4
```

### If the buttons went silent

First, do not reassign them. The usual breakage: the accessibility service is
off or Xiaomi grabbed the keys again. From socrat-0:

```sh
adb connect 192.168.0.19:5555
adb -s 192.168.0.19:5555 shell settings get secure enabled_accessibility_services
adb -s 192.168.0.19:5555 shell pm list packages -d
```

The service list must contain
`dev.vodik7.tvquickactions.free/dev.vodik7.tvquickactions.KeyAccessibilityService`.
Among the disabled packages must be `com.xiaomi.android.tvsetup.partnercustomizer`.
The playbook restores both conditions while the button assignments stay in
place:

```sh
cd ansible
ansible-playbook playbooks/tv-admin.yml --ask-become-pass
```

After that tvQuickActions opens again from the application list and shows the
same actions.

## Grafana on screen

The browser is Fully Kiosk `de.ozerov.fully`. The start address:

`https://grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>?kiosk=1&hideLogo=1&autofitpanels=true&socratTv=1`

This is native public sharing of **only** `socrat-traffic-light`, without a
login and without anonymous Viewer for the whole organization. The exact URL is
taken, without substituting the hostname, from the root-private
`/var/lib/homelab-grafana-tv-public/fully-url.json` on socrat-0. The separate
`tv.alchemmist.xyz` is retired and removed. The internal profile `xiaomi-tv` is
deleted from WireGuard on the TV; its peer is revoked on the servers, and the
inventory no longer creates it. Ordinary dashboards and the API keep SSO/roles.

- `kiosk=1` — full Grafana kiosk, without the top time-range bar and Refresh.
- `hideLogo=1` — without the Powered by Grafana footer. A bare `?kiosk` left
the top bar in place.
- `injectJsCode` is empty. JavaScript through Fully is considered a Plus feature
and draws a PLUS Features Activated watermark. Do not return the script there.
- `launchOnBoot`, `kioskMode`, `disableHome` and `disableHomeButton` are false.
The kiosk here is only a Grafana page parameter. Fully does not become the
launcher and does not start with power, otherwise it would cover the HDMI
picture.

The playbook writes this into `/sdcard/fully-once-settings.json`. Fully reads the
file on the next start and deletes it. For the file to be visible, Fully has
`NO_ISOLATED_STORAGE` and `LEGACY_STORAGE` permissions. Fully restarts only if
the file changed or `-e homelab_tv_fully_reapply=true` is passed.

The public traffic light needs **no login**. The former user `tv` / Secret
`socrat-grafana-tv` were not used or changed; that is historical private access,
not a public password.

The dashboard is UID `socrat-traffic-light`, JSON
`charts/monitoring-k3s/dashboards/traffic-light.json`, ConfigMap
`socrat-traffic-light-dashboard`. Refresh: 5 seconds. The current live window is
`now-12h` (verified November 6), not the refresh interval; the earlier memo
described `now-3h`. The dashboard JSON was not changed by the publication. On
the left are service tiles, on the right CPU, memory, disk and temperature, the
nodes `socrat-0` … `socrat-3` in ascending name order. socrat-2 has no CPU
temperature sensor.

The private old route `/d/socrat-traffic-light` keeps its JS
`charts/syncthing/files/traffic-light-inset.js` and `trafficLightInset: true`.
Its ConfigMap/Pod and Syncthing were not changed. The public policy nginx mixes
in `deploy/platform/grafana/public-entry/files/traffic-light-inset.js`. Only for
the public URL with `socratTv=1` and the verified UID does it move the 5px inset,
hide header/footer and restore autofit: the native public scene does not apply
the old kiosk/autofit parameters. The geometry comes from the **compacted**
native layout, not from potentially overlapping `gridPos`; the 51 panels were
the November 6 acceptance result; the current composition/layout was changed on
November 7 and is determined by the dashboard JSON, not by that old count. The
JS/CSS stay server-side; Fully's `injectJsCode` is empty.

For **URL-only**, without full TV provisioning, use
`ansible/playbooks/tv-public-dashboard.yml`: first an audit, then
`tv_public_apply=true` with a fresh `tv_public_hash`. It requires an already
authorized ADB, Fully in the foreground and the absence of a foreign pending
import; it imports exactly `startURL`, restarts only Fully and verifies that the
DNS/VPN guard is unchanged. With a `tv-uncertain.json` marker, do not retry
without checking the private receipts. On November 6 the file was successfully
read by Fully; the public page with live data was checked by a real ADB
screenshot. The remote, HDMI and cold boot were not retested or reconfigured.

The Fully page scale is set by the playbook as 55% via `initialScale`, the web
font size as 75% via `fontSize`; desktop mode remains enabled manually.

## Network to Grafana

The traffic light works through the ordinary public
`grafana.socrat.alchemmist.xyz`. The internal tunnel/key `xiaomi-tv` (formerly
`10.250.0.8`) was deleted via the WireGuard UI, and the server-side public peer
was removed from the persistent/runtime configuration of all nodes where it
existed. The other peer bindings are preserved; the interfaces were not
restarted. The private historical backups were not destroyed.

Only `alchemmist-tv` for YouTube, `10.0.0.10`, remains on the TV: its
key/configuration was not read or replaced. The profile is enabled by the
YouTube helper on demand. `always_on_vpn_app` is cleared, lockdown is off; the
new setup does not restore the internal-network auto-connect. Android Private
DNS stays `off`, as before, for YouTube compatibility; the DNS/routes of the
global profile itself were not changed. For Grafana, after disconnecting the
YouTube VPN, Wi-Fi and ordinary public name resolution are used.

The helper transition was checked: YouTube started with a `VALIDATED` VPN;
Grafana then opened without an active VPN network. This is not a check of the
physical remote or cold boot — the assignments/HDMI were not changed.

## What is not automated

The playbook installs only the homelab HDMI/Grafana/YouTube VPN helpers and
removes Happ. Third-party Fully, tvQuickActions, WireGuard and the VPN profiles
must be set up separately. The global VPN profile for YouTube is imported into
WireGuard as `alchemmist-tv` from a private configuration file; the original
`tv.conf` and its key must not go into Git. The internal profile for Grafana is
no longer needed and is not imported. The playbook does not set the 65% scale
and desktop mode, does not log in the `tv` user (the public traffic light needs
no login) and does not write button assignments. On a new television the
applications, VPN profiles and the buttons themselves will need manual setup;
for the public traffic light a created native share and its URL are needed, not
a Grafana password.

## TV dashboard rollout, November 7, 2026

`208e2ea` was released via GitOps: CPU shows busy logical cores, RAM and the root
disk an absolute volume (GiB), and the bar length is normalized to the specific
node's capacity. The VPN CPU history was replaced with p95 of the home HTTP
Traefik; below, a list of up to three active critical/warning issues was added.
The current VPN Stat with sparkline is preserved. Argo CD confirmed Synced /
Healthy. The public URL was opened and visually checked in Chromium at
1920×1080; this is not a check of the physical TV with the Fully scale.
Details: `docs/applications/android-tv/traffic-light-tv-design.md`. A direct
ConfigMap patch would revert via Argo CD; publish through Git. Access to the
public URL does not require WireGuard.

## The current layout after the visual edit of November 7

Releases `832e341` (dashboard) and `757dc18` (kiosk presentation): a **24×16**
grid, CPU/Memory/Disk **8 rows** tall each. Absolute values, relative bar
lengths and thresholds preserved. RPS and n8n stand side by side, each `w=7,h=4`;
the new blocks have no headers, info, legends or range chips. Below them, three
separate readable n8n Stats. Instead of per-application Argo bars there are two
state-timeline tracks: Git / Apps. The service names are kept for now:
anonymizing the tiles was not needed for space.

Check **both** routes: the actual
`/public-dashboards/<token>?...&socratTv=1` and
`/d/socrat-traffic-light?kiosk=1&hideLogo=1&autofitpanels=true`. The ordinary
kiosk had an independent native autofit bug that squeezed resources and left
empty gaps. Only for this opt-in mode does the active policy asset
`deploy/platform/grafana/public-entry/files/traffic-light-inset.js` now apply
the same uniform fit grid; edit/viewPanel are not intercepted. The auth hover is
preserved. The shared scene still uses the compacted layout; the authenticated
fit accepts only a whole collision-free saved grid. The editing UI, auth and
Fully were not changed.

A real browser check of four combinations (both routes × 1920×1080 / 1440×900):
55 panels, equal pixel height of CPU/Memory/Disk (531 / 441 px), a common lower
boundary of Disk/VPN, no overlaps and no clipped Stats. Script:
`scripts/check-traffic-light-tv-layout.cjs`; the URL and session state are
passed via private files and are not committed. Details and limitations:
`docs/applications/android-tv/traffic-light-tv-design.md`.

## Dashboard ownership and the fresh layout — November 7, 2026

After the monitoring split, the public policy/TV assets belong to the
Application **grafana**, `deploy/platform/grafana/public-entry`, not the former
kube-prometheus-stack app. The headerless/full-height disk layout was changed in
`832e341`; do not change the canonical share URL, Fully55%/font75%, the empty
injectJsCode and the separate YouTube VPN according to the old panel
coordinates. [Monitoring ownership](../../observability/monitoring/observability-current.md). A source
update and an Argo check do not replace a physical remote/cold-boot test.

## The Argo bar and the layout update — November 11, 2026

The new owner layout is stored in Git; the909 bar at the bottom is x0,y19,w12.
The native bar/group width is already1 (the maximum), so for a visible
thickening the module itself was enlarged h1→h2. The TV fit is now21 rows
instead of20: the other gridPos entries did not change; the overall auto-fit
may slightly change their pixel height. Fully55%/font75%, the public URL, the
server-side presentation JS/CSS, VPN and the remote were not changed. On the
fresh public URL at1920×1080 the bar was27px before the change. This is a
browser measurement, not a physical TV screenshot.

In this run, the address192.168.0.19:5555 was unreachable from socrat-0;
neither ADB5555 nor Termux8022 listeners were found on the LAN. We did not
bypass authorization or force debugging on. Physical acceptance/reloading Fully
is therefore unavailable. Refresh5s updates the metrics but does not guarantee
that a page already open picks up the new geometry. After a layout rollout,
refresh the page in Fully; do not consider a constantly open tab updated merely
because the values move. Do not rescale the whole dashboard for the sake of one
bar and do not run full TV provisioning just to reload.

After the rollout9a47ee49, a fresh anonymous public browser was verified: canvas
27→76px at1920×1080 (≈2.8×). An emulated55%
viewport3491×1964,DSF0.55: canvas72→160CSSpx; that is only a scale emulation,
not a device measurement. The Public909 query gave HTTP200.
32 tests passed, the scoped Helm diff touched only the canonical ConfigMap,
Argo Synced/Healthy. A live exact dashboard comparison (excluding the version)
confirms only909.h changed. The physical TV / its open tab is still unchecked
and not reloaded.

### Superseding Argo design: per-Application Bar gauge, h1

Owner rejected thick h2 continuous strip. Captured live h1 and replaced only909
with native Bar gauge: one equal vertical block per Application, stable alphabetical
name order, state colors, hidden names/values/legend, transparent, no unfilled area.
Min size0; built-in Grafana spacing remains (not configurable without CSS). Gradient
mode + fixed color mappings gives solid borderless blocks; Basic's2px cap and LCD
multiple-cells-per-Application deliberately avoided. One instant latest-status
query with same root/freshness/completeness guards; categorical positive codes,
NOT counts/percentage. Geometry x0,y19,w12,h1; grid back20 rows/102 empty cells.
Native panel only: existing TV public URL/Fully/VPN/presentation scripts untouched.
Physical-TV ADB still unavailable at last check. New viz needs reload in Fully.

### Latest correction:49 apps, h2, native hover, no clipped blocks

Argo live inventory49; previous public blocks48 differed only byroot. Include root
now in current per-app query (not a fabricated extra block), so totals match.
Changed native Bar gauge sizingAuto→manual withminimum width0: Auto had ignored
zero and used8px, clipping last blocks in narrower signed-in panels. Acceptance
must check bounds of all blocks, not just DOM count. Native10px gaps unchanged.
Height2 restored atowner request, x0,y19,w12;114 empty cells/21 rows. Names/values
still hidden. Single native data link gives browser-title Application name on
hover and opens the matching Argo Application on click. Works on normal signed-in
and kiosk routes; TV public opt-in remains noninteractive by existing policy.
No Fully settings, public share URL, presentation assets, VPN or other panels changed.
After deployment reload Fully for geometry/query changes; no claim of physical TV
verification while documented ADB access is unavailable.

Acceptance eb7cd6a3:49 actual query frames=49 named K8s Applications.
Signed-in normal and kiosk: 49 resolved native browser-title links each,
the hover checked on EVERY one of the 49 blocks at1920×1080 and1440×900,
all bounds inside the panel. Public1920 and the 55%-emulation: 49 fully
visible blocks; native height76.66px.32 tests, ArgoSynced/Healthy; the live
diff is only909. This is browser acceptance, not a physical TV screenshot.

15:16MSK11Nov: the address from the wiki, 192.168.0.19:5555, now responds, but
`adb devices` shows unauthorized (socrat-0 SSH user alchemmist); the model is
not yet confirmed. We did not bypass authorization, did not reset
keys/settings, did not reload Fully via ADB. A real device screenshot requires
an authorized ADB; the new geometry of an already open page requires a Fully
reload. The address by itself is not proof of the model.
## Real TV diagnosis: subpixel Bar gauge, November 11, 2026

ADB is now authorized; getprop confirms MiTV-MOOQ1/tarzan, Fully foreground.
Real screencaps were taken before and after reloading only Fully (no pending
import). The reload did not fix the 49 blocks that looked like sparse hairs.
Important: native screencap writes 65 bytes of vendor diagnostics before the
PNG; strip down to the PNG signature before opening the picture.

A UI audit: Fully initialScale55%, font75%, desktop=true, wideViewport=true,
overview=false preserved. The real WebView is 156.0.8078.47, Android
density320/DPR2. For an exact read-only DOM audit, the free Webview Contents
Debugging was temporarily enabled (originally false); CDP goes through the
authorized ADB and an SSH loopback-only tunnel, not a public port, not Fully JS
injection. After acceptance, return debug to false and remove the forward.

The actual viewport: innerWidth1024, innerHeight575; screen960×540CSS,
visualScale0.9375. Do not emulate the TV as 3491CSSpx/DSF0.55: that was a wrong
model. In the old w12,h2: the panel is 503CSSpx, content 485; 49 bars with 48
native gaps×10px left only 5px for the colored parts: each one 0.10156CSSpx
(≈0.19 physicalpx). The DOM count of 49 and the bounds check passed, but
rasterization made most invisible. It is not a data or height problem;
lowering minVizWidth to 0 only prevented clipping, it did not ensure visibility.

Scoped native fix: 909 width 12→24 into the empty right half of the bottom row, x0,y19,h2
unchanged. Other panels/settings untouched, no CSS/JS/plugin/zoom/DPI changes.90
empty cells remain. New regression requires≥8CSSpx per49 bars atviewport1024.

Acceptance 0a5f53fb was performed ON THE PHYSICAL TV after a Page.reload of
its WebView: 49 native bars/49 app links, panel1014CSSpx, each bar 10.523CSSpx
vs 0.10156 before; height 28.578CSSpx unchanged. The final ADB screenshot
1920×1080, taken after debug was switched off, was checked visually and by PNG
scanline1025: 49 separate colored areas 18–20physicalpx wide. This is not a
fixture/emulation. The screenshots/DOM evidence is private/tmp:
`tv-actual-gauge-before.png`, `tv-actual-gauge-final.png`,
`tv-dom-before-width.json`, `tv-dom-after-width.json`.33 tests pass; the exact
live dashboard diff is only909.w, the scoped Helm only the canonical CM,
ArgoSynced/Healthy. No unrelated dirty VPN files touched.
Cleanup verified: Webview Contents Debugging was returned to the original false
via the UI; /proc/net/unix no longer shows the debug socket; the ADB forward
19222 was removed, the SSH loopback tunnel closed, our own temporary
uiautomator XML deleted. Fully foreground, the actual updated dashboard already
loaded: the owner's reload is not needed for this release.
Fully zoom/fonts/desktop/wideViewport, DNS/VPN/remote keys/HDMI unchanged. An
initial scale of 55 is not a substitute for measuring the actual viewport/DPR
on the device.
### Moscow IP cube —11November2026

NativeStat928 added belowHomeIP atx23,y8,w1,h1; target91.189.82.238:443 (socrat-4),
service_id=edge-moscow, alertSocratServiceEdgeMoscowUnavailable. Green0=TCP reachable,
orange pending/red firing/grey-2 missing or stale telemetry as otherpublicIP tiles.
Not whole-node or authenticatedVPN health. Frozen nativeCollector needed additive
scrapejob too; sourcehelper inotel-scrape-config.py persists it through rebuilds.
Stable /edge-moscow poolname avoids historicalnumeric endpointindex collision.
Scoped native activation complete: actual panelquery0, probe_success1/fresh~5sec;
one Collectorcontainer graceful restart with native validation+SHA/identityguards,
samePod/volumes/allothercontainerIDs, allReady.41tests pass. SeeprototypeREADME
receipt; no TVsettings/CSS/JS or networkchanges. Owner manual compactlayout captured
separately3150cbd:909w12/h1, preserve that geometry (not oldforcedw24/h2). Compact
nativeBarGauge gap limitation was still unresolved at that stage; the subsequent
owner-approved CSS fix and physical acceptance are documented below.

### Current TV Argo spacing — owner-approved exception,11November2026

The former blanket noCSS restriction is superseded ONLY for native909 on actual
publicTVopt-in socratTv=1 + canonicalUID. Existingtraffic-light-inset.js verifies
nativeverticalGradient/hidden-label DOM, then scopes padding8→3CSSpx/gap10→2CSSpx
and flex width redistribution (including linkwrapper) tothatpanel. Normal private
view/edit/kiosk, otherpanels/globalgrid gaps/Fullysettings unchanged. No plugin,
FullyinjectJsCode, syntheticbars/statecolors/metric/JSON/layout mutations. Failclosed
for unsupportedDOM/noData; dynamicnativeAppcount, not hardcoded49. Existingowner
w12/h1 retained; TVdisplay no longer requires fullwidth orh2.

ActualTV acceptancef37bdda6: viewport1024×575,DPR2,visualScale0.9375; same panelrect
before/after;49bars0.10156→8.14CSSpx wide and2.64→12.65CSSpx high. Real finalADB
screenshot1920×1080 shows49 separate14–15physicalpx fills (PNG scanline1050), visual
inspection complete. Native colors/names/order preserved; separatemixed-state
browserfixture also passes.76focusedtests, scopedHelm onlyGrafana-policyTVasset and
proxyDeploymentchecksum; otherowners/SSO/routes/backend/resources unchanged.
TemporaryWebviewdebugoriginalfalse restored, socket/ADBforward/SSHtunnel closed,
ownuiautomatorXMLdeleted. Fullyforeground, pagealreadyreloaded—ownerreload notneeded.
Private/tmp/tv-compact-actual-final.png and pairedDOMreceipts are realdevice evidence,
not browseremulation. A privatepublic-share URL was emitted by temporaryPlaywright
errorlogging; ownerinformed, no unapprovedshare rotation, verifiercleanedup.


## Maintaining the Argo TV stylesheet

**The currently agreed solution:** the native Bar gauge909 stays at the manual
size `x0,y19,w12,h1`. Targeted styling is applied only on the public TV page
with `socratTv=1`. This is an explicitly owner-approved exception, not
permission to change the whole dashboard with CSS edits.

- **Git source:** `deploy/platform/grafana/public-entry/files/traffic-light-inset.js`,
  the `compactArgoRules()` function. It is delivered by the existing Grafana
  policy proxy, not by Fully's `injectJsCode` setting. The CSS is scoped to
  `.socrat-tv-public-grid [data-viz-panel-id="panel-909"]`.
- **Parameters:** inner padding 8→3 CSSpx; gaps 10→2 CSSpx. Flex re-distributes
  the cell widths; the native data-link wrapper and the colored fill are
  stretched separately. Reducing only the margin is not enough: Grafana has
  already computed the subpixel bar widths accounting for its own 10px gaps.
- **Why the TV differed:** the physical screen is 1920×1080, but the real page
  is 1024CSSpx, DPR2/visualScale0.9375. Do not use the old emulation of
  3491CSSpx/0.55 scale as proof. With 49 applications, the former 48 gaps took
  480CSSpx out of roughly 485 available, leaving each bar only 0.10CSSpx.
- **Boundaries:** ordinary signed-in view/editor/kiosk are unchanged; the
  common grid, other panels, native colors/data/links, Fully's 55% scale and
  75% font are untouched. Classes are added only after checking the UID, type
  and structure of the native DOM. No data / unsupported DOM — refuse to
  modify, do not paint green blocks. The application count is dynamic, not a
  fixed 49.
- **Regressions:** `tests/test_grafana_tv_public.py` checks the scope, the
  guard conditions and the preservation of native data. When the asset changes,
  a scoped Helm diff is required; the policy ConfigMap and the checksum of its
  proxy Deployment are allowed. Check and update only the corresponding two
  reviewed hashes in `tests/fixtures/public-entry-handoff.json`; do not rewrite
  other owners' hashes.
- **Acceptance:** verify the presence of all applications, the actual
  width/height of the fills, and that they are fully inside the panel. The
  number of DOM elements by itself does not prove visibility. A real ADB
  screenshot plus measurements in the WebView are needed; a
  preview/mixed-state fixture must not be passed off as the physical TV. Latest
  result: 49 visible blocks 14–15physicalpx wide in the original half of the
  row.
- **Update:** Git→Argo Application `grafana`→the existing policy proxy; do not
  restart the Grafana/Prometheus backend for the sake of CSS. After delivery,
  re-read the TV page: the metric refresh of 5s does not replace loading the
  new JS/model version. Return temporary WebView debugging to its original
  state and close the ADB/SSH forwards.

### Freshness and the exact meaning of the Argo colors

This is an instant latest-state, not history and not an average. Argo metrics
are collected every 15s, the dashboard re-runs queries every 5s: typically
several–20s after a change already reflected by Argo itself; this is not an
instant push and not a strict maximum delay. The freshness of 90s and the
up/inventory guards must not pass off a stale/incomplete set as a fresh green
one. Ready = Healthy+Synced; blue = Progressing; red = Degraded/Missing;
orange = OutOfSync/Suspended; gray = Unknown. The Syncing operation is not
tracked separately; a short transition can slip between collections. All green
means the latest fresh Application states, not proof that all services are
reachable.

The TV-fix code: `c6121e19`, integration with concurrent main: `f37bdda6`,
physical acceptance/cleanup: `f459af38`. The MoscowIP and the manual layout
are also stored in Git; do not restore the old forced w24/h2 sizes at the next
generation.
## Quality panels in owner-approved free space —11November2026

Owner authorized research-based additions; code7e77376, integrated0218340f and
TVreadability8091d22b. Sixnativepanels930–935 use88of93emptycells, leaving5;
old57panels, manualpositions/publicshare/Argo909 anditsCSS unchanged.20rows,63panels.
Generator `scripts/build-traffic-light-quality.py` aborts on overlap, preserves
unrelatedmodel and newownergeometry. Updated layoutfixture and55focusedtests.

-930(x12,y10,w4,h4): worst-node PSI some CPU/RAM/I/O5m, NOTutilization; require
 complete freshnodeinventory/up/pressurecollector. LabelsCPU·4 etc use node digits
 to avoid nativeellipsis; full labels retained. Amber25%CPU/10%RAM+I/O matches
 existingresourcecontentionboundary, NOT its10m firingduration.
-931/932/933(x12/16/20,y14,w4,h4): localvLLM currentwaiting+1htrend, estimatedTTFTp95
 over15m with≥20observations, outputtokens/s5m+1htrend. Low sample vsNo telemetry
 distinct; lateststatus with up/sample90sguards, no missing→healthyzero. Bluequeue
 andthroughputinformational. TTFT10/60s bands guidance, not agreedSLO. Notremote
 LiteLLMmodels, perrequestgeneration speed or fullstreamedHTTPduration/billing.
-934/935(x12/18,y18,w6,h2): LMS/n8n lastsuccessfulCronJobage; bands6/8h and24/26h.
 Missingjob/never succeeded/staletelemetry distinct. SuccessfulJob does NOT prove
 archive integrity/offhostcopy/restore. No unnecessarybackup-age sparkline.

ScopedHelmONLYcanonicalTrafficLightCM; no exporter/Collector/backend/alert/CSS
changes orsyntheticproductionactivity. Nativequeriesaccepted; actualTVall6panels
andtext bounds fit;49Argo fills visible. Nativeleftlabels originallyellipsized,
fixedwith shortlabels andmanualsizing, noextraCSS. ConfigMapsizeguard<240000 retained.
Real final screenshot `/tmp/tv-quality-final-fit.png`, pairedDOMreceipt
`/tmp/tv-quality-dom-safe.json`; finalPNG also independently counts49Argo fills.

Cleanup originaldebugfalse verified, socket/forwards/UIXMLremoved. Fullysettings
return briefly reset visualzoom/cropped page; savedpreferences untouched. One
Fully-onlyrestart with fresh NO_PENDING_IMPORT check restoredfit; FINALscreenshot
was rechecked afterrestart. SavedFully55%/font75%/network/VPN unchanged. Do not
finish acceptance on a pre-cleanup screenshot: check finaldevice after closingmenus.

## Current service-diverse layout — owner correction11November2026

Supersedes preceding AI-heavy/PSI expansion. Owner rejected blue for newgraphs
(VPN already blue) and wanted RustFS/Harbor/other applications, not threeAIcards.
Featurec84e31dd: ONLY previouslyadded930–935 scope changed. Original57panels,
Argo909/nativecolors/CSS/share/VPN and alloriginalpositions/settings exact unchanged.
62panels,20rows,5emptycells. No exporter/backend/alert/CSS/Fullypreference changes.

Current additions:
-930 x12,y10,w4,h4: estimatedHTTP5xx/1h worst3 observed businessbackends, allowlist10:
 Monori,LMS,Harborcore,Wiki,Evidencegateway,Authentik,Blog,Cats,Umami,SearXNG. Explicitly
 excludesGrafana/VPN/infrastructure. Zero only from fresh observedrequestcounter;
 missingbackend omitted, NOT healthy0; Traefikup/fresh90s. Nonzero red,0neutralgray.
 Zero ties arbitrary; not an availability guarantee or exacteventcount/SLO.
 RustFS-labelled HTTPbackend means Evidencegateway, NOT internalS3.
-931 x12,y14,w6,h4: RustFS podeth0RX/TX, purple#B877D9.
-932 x18,y14,w6,h4: HarborREGISTRYpod eth0RX/TX, teal#2EBFA5 (notallHarborcomponents).
 BothnativeStats with separateRX/TX names/numbers and1harea sparklines;5m byte rate,
 includesinternaltraffic/protocol/probes, NOTobjectcount/S3operationcount/pullpush
 count orservicehealth. Individual sparkline auto-scales: compare values, notheights.
 cAdvisor metrics lackcontainer label (sandbox counters); don't filtercontainer=POD.
 Bothdirectionseries and freshcurrentPodinventory coverage90s required. label_join
 preservesmetricidentity before timestamp(): rawRX/TXotherwisecollapse identical
 labelsets when timestamp drops__name__. Latestmissing sentinel-2 per direction and
 last reducer prevents stale-lastgood/absent→zero. Read-only missing/partialcounter
 negativequeries both returned2×-2 as expected; no syntheticproduction activity.
-934/935backupages remain x12/18,y18,w6,h2, unchangedmeaning/thresholds.933retired;
 reservedIDS retains933 so generator removes its oldownedAIpanel. PSI930was replaced
 byserviceerrors to permit readable6-column networkblocks aligned withbackupcolumns.

No native RustFS/Harbor businessmetrics scrape exists on inspected datasource;
never fabricate object counts, scanstatus, OCIpullpush counts orPVCquota percent.
Do NOT enable exporters/restart workloads or use privileged app credentials merely
because a dashboard expansion was approved. Those require separate scoped work.

FreshmanualAPIcheck matched sourcebeforeedit. ScopedHelm onlyTrafficLightCM.
42dashboardtests +18TVstyle tests=60 focusedpasses, unchanged <240000CMsizeguard.
Generator preserves ALLfuturemanualgeometry, including a return toprior4-column
sizes; expansion changed OWNEDdefaultcoordinates once, not a permanentforce rule.

ActualTVacceptance: WebView1024×575,DPR2; all5widgets/everytextrange contained;
62panels,49Argo fills. Private `/tmp/tv-services-dom-safe.json` and FINALactual
`/tmp/tv-services-final-fit.png`: inspected afterdebugfalse restoration/Fully-only
restart (pendingimportcheck), no clippedlabels/valueunits/backupbottomrow. Native
UIXML verifies all4RX/TX names. IndependentPNGscanline counted49Argo runs; pixels
confirm purpleRustFS/tealHarbor. Originaldebugfalse restored/socketabsent, forwards
closed/ownXMLremoved; saved55%/font75%/networksettings unchanged. TVforeground.

## Current compact AI restoration —11November2026, eb238f5e

Owner explicitly removedHTTPworst3 and approved ONEcompactAIblock inits place.
ONLY930changed; other61panels/modelsettings/geometry exact unchanged.62panels,
5holes. RustFS purple/Harborteal/backups/Argo909/publicshare/VPN retained.
930 x12,y10,w4,h4 nowNativeStat withtwo instantaneous targets, no extra sparkline:
- AI · queue: current localvLLM waitingrequests, per-seriesfresh/up filtering.
- AI · TTFTp95: estimatedlocalfirst-tokenp95 over15m, require≥20estimatedhistogram
 observations; otherwiseLow sample. NotremoteLiteLLM/fullstreamduration. Up/count/
 bucketfreshness90s; negative/NaN/infinitequantile excluded. Missing=-2No telemetry,
 lowsample=-1; no absent→healthy0. Unitseconds onTTFTonly; queueplaincount.
 Pink#E0A6DC informational, no inventedSLO/alert; graymissing/lowsample. Lastreducer.
 HTTPquery/allowlist removedfromgenerator, notmerelyhidden. Generatorpreservesmanual
 geometry; no newCSS/exporter/backend/Collector/restart changes.

NativeGrafanaAPIacceptedbothqueries; queue0/TTFTLow sample onacceptance, not a
claimofzerolatency. Read-only missing-source negativequeryboth-2.42dashboardtests
+18TVstyle=60focusedpasses; ConfigMapsizeguardunchanged. Freshmanualcapture matched
sourcebeforeedit. ScopedHelmONLYTrafficLightCM. ArgoSynced/Healthy and liveGrafana
model930Stat/2targets independentlyverified (revisionfieldalone initiallypreceded
Synced; waited foractualSynced beforefinalacceptance).

ActualTV reloadedviaFully-onlyrestart afterpendingimportcheck, preferences55%/
font75%/debugfalse unchanged. NoCDP/debug toggle needed. NativeUIXMLhasbothAIlabels,
all4RustFS/HarborRXTX labels, bothbackupages, HTTPtitleabsent. FinalactualPNG
`/tmp/tv-ai-final-fit.png` visuallyinspected, independent49Argo-run count andpink
AIpixelcheck. OwnUIXMLdeleted, socketabsent, Fullyforeground. No otherpanels moved.

## Metrics cascade numeric footer —11November2026,94ff1c6/f24f7e12

Owner asked for more cascade numbers in the backupfooter, keepingAIas-is. Studied
live `socrat-metrics`/Metrics (37panels), source JSON, currentThanos values/cascade.py
and nativeCronJob/deployments. Existing pipeline: Collector→Prometheus0(12h local)
→sidecar/raw0→rawcompactor5m/1h→hourlyCronJob(:30Europe/Moscow,Forbid)→5mshelf1/
1hshelf3. Raw5d/5m30d/hour730d intent; coarse-copy coverage gates before cleanup.
Age of CronJob success is NOT live-sample freshness, lastsidecarupload or proof
of DR/archiveintegrity. No jobs manuallyrun, no pipeline/exporter/retention changes.

Finalfooter SAME y18/h2/12-column area,6numbers instead of2:
-934LMSbackup x12,w2;935n8nbackup x14,w2. Names shortened, fonts11/20, existing
 queries/thresholds/meaning preserved. Graystate labels shorter: No data/Never/
 Missing; no missing→0. Last successfulJob remains NOTproof of restore.
-936 x16,w8,h2: fourfieldsNativeStat, gold#E0B860, fonts11/20:
 Cascadeage = seconds since hourlyCronJob success (warn3h/red6h asMetrics);
 Downsample = rawcompactor todo blocks (informational, NOTbytes/ETA);
 Halted = sum(max per stage halt flag) only with ALL3 fresh stages (red≥1);
 Samples/s = maxPrometheusappend rate5m, NOTall-producer/end-to-end delivery.
 Everyfield fresh90s/up gated, missing=-2→grayNo data, latest last reducer.
 Rawcompactor intentionally pauses during copy; missing duringthat period is NOT
 fabricatedhalt/failure. Missingone stage must never yield healthy0.

Tried owner-suggested RustFS/Harborh3: nativeStat automaticallyhid sparklines.
Therefore retainedh4 ANDoriginalfonts/queries/colors; no newCSS. Got all6footer
numbers through WIDTHpacking/groupedStat instead. AI930 and ALL60 other existing
panels/settings exact unchanged.63panels/20rows/5holes;only934/935 resized/relabeled,
936added. Generator preserves futuremanualgeometry/aborts onoverlap. Generated
OWNEDwidgets930–936 compact-JSONencoded ONLY to retain actualConfigMapbyte budget;
original57panel formatting intact, unchanged <240000renderedsize regressionguard.
Human-readable authoritative expressions/options remain in generator. Otherassets
and Metricsdashboard itself untouched; scopedHelmONLYcanonicalTrafficLightCM.

43dashboardtests+18TVstyle=61focusedpasses. NativeAPIpositive values verified;
fourmissing-sourcequeriesall-2, two-stagecompactorquery-2 (not0). Freshmanualmodel
captured/matched beforeedit. ConcurrentSPIcommits merged normally, VPNdirtyfiles
untouched. ArgoSynced/Healthy atfeaturemergef24f7e12; no blanket sync/prune.

PhysicalTV: actualWebView1024×575/DPR2 allnewlabel/value/unit ranges fit; final
NativeUIXML has6footernames, all4trafficnames, AIlabels. Inspected actualPNG AFTER
originaldebugfalse restore/Fully-onlyrestart withpendingimportcheck:
`/tmp/tv-cascade-final-fit.png`; DOM `/tmp/tv-cascade-dom-safe.json`.49Argo fills
independently counted, goldnumericpixels confirmed; nativeRustFS/Harbor curves
stillvisible, no scroll/clipping. Fully55%/font75%/network unchanged; socketabsent,
forwards closed, ownXMLremoved, Fullyforeground. At finalimage age48min/todo0/
halted0/~48.3ksamples/s are time-bound observations, not all-clusterhealthy/DR claims.

## Owner compact capture + model timelines — 18November2026

Owner manually removed930AI and923/924/925n8nreadouts, compacted network/backup/
service tiles, then explicitly requested capture followed by two model timelines.
Captured fresh live59panels in a461f58b before additions. Other concurrent primary
worktree files left untouched; isolated worktree /tmp/homelab-tv-model-charts.
Final61panels: ALL59owner panels/settings preserved exactly (database id omitted).
937qwen3.8-27b x6,y14,w6,h5;938venice-deepseek x16,y16,w8,h4. No existingblock moved.
Both nativeTimeSeries, nolegend, perkeycolorsbyname, nativehover, fixedrolling1m
completedrequests, actualmodelselectors fromLLMkeydashboard. No in-flightclaim,
no zero-fill, acceptancefixturesexcluded. Inheritdashboard12h (no1hoverride).
Bottom20 remains exactlyArgo909bottom;Qwenends19,Veniceends20. NoCSSchange.

Nativepublicquery12h both panels successful withliveframes. Isolated1024×575/DPR2
browser preview inspected:61panels, scrollheight575, Qwen bounds x260.48/y406.09/
w247.5/h135.25;Venice x686.33/y463.39/w332.66/h106.59. Venicebottom569.98 EXACT
Argo bottom569.98. Preview /tmp/tv-models-browser-preview.png is NOTphysicalTV.
TVADB saved192.168.0.19:5555 currently No route to host; physicalacceptance and
Fullyreload BLOCKED. No device/settings/VPN changes or restarts performed. Owner
must refresh existingTV page to receive updatedmodel. Do not claimactualTVfit.

CMbudget preserved (<240000 unchanged): compactJSONformatting ONLY for21/22/23/
909 and ownedwidgets, final235814bytes measuredUTF8. Initial sizechecks failed;
fixed formatting, not modelorlimit. Generator scripts/build-traffic-light-models.py
preserves futuremanualgeometry and rejects overlap/belowArgobottom. Qualitybuilder
now preserves EXISTINGownerwidgetcontent/order/deletions ratherthanresurrectingAI;
Argo builder retains absent emptyoverrides. Ownerlayoutfixture/tests updated;
50traffic-light tests pass. ExistingdirectIPfixture updated for priorwishlistjob.
Publicshare UID unchanged. No instrumentation/inference/plugin/silence changes.

### Gold footer split —18November, a8fb6abc/6419721b

Owner accepted two model charts, requested removing Downsample/Halted entirely,
splitting age/ingest to two goldcards underbackupcards and expandingVeniceupwards.
Freshlive model matchedGit before edit.936nowCascadeage x12,y18,w2,h2;939Samples/s
x14,y18,w2,h2. Both retain EXACTformerA/D expressions, freshness/missing guards,
units/agewarningbands; no fabricatedzero. Removed formerB/C queries. Nativefont9/
15 fits names+value+units inside77.17×49.30CSSpx cards (11/20wrapped/clipped in
preview; fixed ONLY newcards). Backups unchanged. Venice938 y14,h6 (wasy16,h4),
useswholefreed2-rowblock, samebottom20; all59otherpanels exact.62panels/5holes.
51traffic-light tests pass, ConfigMapbudget<240000 unchanged. Updated ownerfixture;
modelbuilder preserves order and futuremanualgeometry. Inspected isolatedbrowser
1024×575/DPR2 screenshot /tmp/tv-split-browser-preview.png: newcardlabel/value/unit
rectangles fullycontained, Venicebottom569.98=Argo569.98, no scroll. This is NOTan
actualTVscreenshot; TVstillNo route to host at192.168.0.19. No deviceprefs/restart/
CSS/pipeline changes. Physicalacceptance blocked; owner refresh needed.
