# Lenovo tablet: PostgreSQL display and administration

Last verified: 2026-11-27. This is the USB-connected tablet beside the server, **not** the Android TV. See [TV administration](../android-tv/README.md) for the separate television.

## Device and access boundary

- Lenovo Tab M10 FHD Plus, TB-X606F; MediaTek MT8768WT, eight Cortex-A53 cores, ARM64.
- 4 GB RAM; nominal 64 GB flash. Initial inspection: 52 GB data filesystem, 47 GB available.
- Android 10, build `TB-X606F_S301068_230919_BMP`, security patch 2023-08-05, kernel 4.9.190.
- Stock firmware, locked bootloader, no root. USB debugging authorized for socrat-0.
- No Linux installation, Termux, tablet SSH server or Kubernetes worker was configured. Stock kernel lacks namespaces, MEMCG, PID/device cgroups and VETH; root alone would not make k3s work.
- System dark mode is firmware-locked (`mNightModeLocked=true`). The dashboard itself uses a dark theme.

Run commands on socrat-0 through `ssh socrat-0`. Always select the tablet serial explicitly: socrat-0 also administers a television.

```sh
adb devices -l
# Confirm model Lenovo_TB_X606F before any write.
adb -s HA1E1E5A shell getprop ro.product.model
adb -s HA1E1E5A shell dumpsys battery
adb -s HA1E1E5A shell input keyevent KEYCODE_WAKEUP
```

If unauthorized, unlock the tablet and approve the USB debugging prompt. If absent, check a data-capable cable and Developer options → USB debugging. USB MIDI/PTP/tethering selection is not USB debugging. Do not expose network ADB, unlock the bootloader or reset the device as a connectivity workaround.

## Display and launcher

Applied settings (not a reason to reset unrelated settings):

```sh
adb -s HA1E1E5A shell settings put global stay_on_while_plugged_in 7
adb -s HA1E1E5A shell settings put system screen_off_timeout 2147483647
adb -s HA1E1E5A shell settings put system screen_brightness_mode 0
adb -s HA1E1E5A shell settings put secure screensaver_enabled 0
for key in window_animation_scale transition_animation_scale animator_duration_scale; do
  adb -s HA1E1E5A shell settings put global "$key" 0
done
```

The screen stays awake while powered; the unplugged timeout is approximately 24.9 days, not literal infinity. Brightness is manually controlled from the shade. Do not override the user's brightness. USB charging was slow; use adequate power for continuous operation and monitor battery temperature/condition.

Stock launcher `com.tblenovo.launcher` remains installed. All home-screen widgets, folders and dock shortcuts were removed through its UI, including Chrome Search. Applications are still available through the app drawer. Do not uninstall Settings or clear launcher data just to remove shortcuts; clearing data can restore the default clutter.

### Wallpaper

The source used by socrat-0's wallpaper startup script is:
`/home/alchemmist/Pictures/wallpapers/custom/images/frame-50.png`
(resolves into the dotfiles repository). Tablet copy: `/sdcard/Pictures/socrat-wallpaper.png`.

```sh
adb -s HA1E1E5A push ~/Pictures/wallpapers/custom/images/frame-50.png /sdcard/Pictures/socrat-wallpaper.png
adb -s HA1E1E5A shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Pictures/socrat-wallpaper.png
adb -s HA1E1E5A shell am start -a android.intent.action.ATTACH_DATA -d file:///sdcard/Pictures/socrat-wallpaper.png -t image/png --grant-read-uri-permission
```

Choose the wallpaper handler, select home/lock screen and confirm **Set wallpaper**. Merely launching the intent does not apply it. Google Photos was subsequently removed; use the installed Lenovo wallpaper picker or Files if the chooser changes.

## Fully Kiosk and recovery

Installed Fully Kiosk Browser 1.61.4, package `de.ozerov.fully`, from the official Fully website. Fullscreen is enabled; address and action bars are disabled. Chrome is retained but is not the display browser.

- Swipe inward from the **left edge** for Fully's menu.
- **Goto Start URL** reloads the configured dashboard.
- **Settings** edits the start URL and appearance; **Exit Fully** returns to Android.
- If needed, `adb -s HA1E1E5A shell input keyevent HOME` opens the normal launcher.
- Launch Fully with `adb -s HA1E1E5A shell monkey -p de.ozerov.fully 1`.
- Boot autostart, device-owner lockdown and recovery after a power cycle were **not configured or accepted**. Do not claim unattended boot recovery.
- No Plus license was purchased and JavaScript injection is not used. Injection is a Plus feature and can introduce a watermark.

The start URL is private operational state on socrat-0 in `~/tablet-pulse/url.txt`. Do not commit it: native public dashboard URLs contain an access token. Anyone with the link can view the displayed aggregates. Do not enable organization-wide anonymous access or place Grafana admin credentials on the tablet.

Grafana's kiosk parameter alone does not hide native public-scene controls. The dashboard's `timepicker.hidden: true` removes the time/refresh controls. The dashboard title and **Powered by Grafana** footer remain; this is not an entirely chrome-free public scene. The separate TV has a UID-specific server-side policy: do not alter it casually or assume it applies to this tablet.

## PostgreSQL dashboard and collection

- Grafana UID: `socrat-tablet-pulse`; title: **SOCRAT / PostgreSQL Live**.
- Native public share enabled only for this dashboard. Existing TV dashboard is unchanged.
- Range: last hour; refresh: 5 seconds; collector interval: 15 seconds. Faster rendering does not create more samples.
- Three columns: `pg-common`, `pg-critical`, `pg-internal`; consistent cyan, purple and orange colors.
- Four rows: committed transactions/s, database connections, inserted/updated/deleted rows/s, PostgreSQL buffer-cache hit percentage.
- Queries select primary instances and aggregate away database/user/application labels. No SQL text, credentials, client addresses or per-user activity is displayed.
- Buffer-cache percentage is PostgreSQL shared-buffer hits, not OS cache hit rate. Zero traffic can produce an undefined ratio; do not replace missing data with healthy-looking zeros.

[Dashboard JSON](dashboard.json) and [PodMonitor snapshot](pg-monitor.yaml) capture the working configuration. They are **recovery snapshots, not automatically reconciled production resources**. The initial setup was performed live; there is no tablet Ansible playbook or GitOps ownership established yet. Audit current state and move these into the owning deployment before future infrastructure changes; do not blindly apply historical snapshots.

The dashboard was saved through the Grafana API. Local ID/version fields in the snapshot are instance-specific; retrieve the latest version and preserve folder/ownership before updating. Do not recreate the share or overwrite another dashboard when importing.

The PodMonitor is `cattle-monitoring-system/tablet-postgres-pulse`, selecting only the three CNPG clusters in namespace `postgres`. It currently uses the existing Prometheus selector label `homelab.alchemmist.xyz/scrape-owner: retired-legacy-prometheus`. This is an explicit direct-scrape exception to the wider OTel collection design, not a recommended new default. Keep collection ownership in mind when migrating it; avoid duplicate scrapes.

Only an allowlist is retained. Counter names from `cnpg_pg_stat_database_*` are normalized to `*_total` by metric relabeling. Preserve the literal replacement `${1}_total`; shell expansion can accidentally turn it into `_total`, causing collisions and missing counters. Write manifests with quoted heredocs or a serializer, then inspect the live object.

Grafana queries datasource UID `prometheus`, whose URL is **Thanos Query**, not the direct Prometheus TSDB. Validate panels through that datasource. Initial detailed collection started on November 27; normalized counter history began around 21:17 device time. Earlier history was not backfilled. Existing alerts and the previous replication collectors were not renamed.

### Validation and rollback

1. Confirm each of the 12 queries returns data through the Grafana datasource and no counter-name warnings.
2. Wait for at least two successful scrapes before expecting rates; a newly created series has no previous hour of history.
3. Reload Fully and inspect an actual tablet screenshot, not just an XML UI tree. Verify all rows fit, controls are absent and data continues changing.
4. Public read access does not prove authenticated/admin APIs are safe; preserve existing SSO/TLS policies and audit publication independently.
5. To retire collection, remove only the owned PodMonitor after assessing dashboard dependencies. To revoke sharing, disable only this dashboard's native public share. Do not remove the TV share, datasource, PVCs or databases.

Capture a screenshot locally without publishing it:

```sh
ssh socrat-0 'adb -s HA1E1E5A exec-out screencap -p' > /tmp/tablet.png
```

Local setup artifacts are in `~/tablet-pulse/` on socrat-0. `build.py` and `postgres.py` are historical one-shot scripts, **not idempotent provisioning**; do not rerun them as recovery commands. They can recreate shares or revert queries/layout. `previous.json` is the earlier AI dashboard. Keep share URLs and any future credential receipts private.

## Debloat inventory and reversibility

Packages below were removed with `pm uninstall --user 0`, not physically erased from protected system partitions. System packages can generally be restored with `cmd package install-existing --user 0 PACKAGE`; third-party packages may require reinstalling a trusted APK. Do not promise every removed app is recoverable without a download.

```text
com.android.fmradio
com.tblenovo.kidslauncher
com.google.android.youtube
com.google.android.apps.googleassistant
com.google.android.gm
com.google.android.apps.tachyon
com.google.android.apps.wellbeing
com.google.android.apps.docs
com.google.android.apps.maps
com.google.android.videos
com.google.android.apps.youtube.music
com.android.printspooler
com.android.bips
com.google.android.printservice.recommendation
com.motorola.demo
cn.sinoangel.monsterclass
cn.sinoangel.color
cn.sinoangel.kidcamera
com.opera.browser
com.opera.preinstall
ru.yandex.searchplugin
com.yandex.browser
com.tblenovo.lenovoruapps
com.google.android.googlequicksearchbox
com.google.android.calendar
com.android.contacts
com.google.android.deskclock
com.google.android.calculator
com.tblenovo.soundrecorder
com.google.android.contactkeys
com.mediatek.camera
com.google.android.apps.photos
```

Settings, keyboard, stock launcher, Files, Chrome/WebView, Play services/store, networking, updates and core Android providers were retained. A cache-trim request was issued; no significant storage recovery was observed and user media directories were effectively empty. This is not a factory reset or proof that every remaining service is necessary.

Initial settings/list backups: `~/tablet-backup-20261127-200348/` on socrat-0, with the path in `~/tablet-backup-latest`. These are not a firmware/data backup. Original stay-awake setting was `0`, screen timeout `30000`; restore individual settings only after reviewing the saved values.

## Acceptance and known limits

Actual tablet screenshots confirmed fullscreen Fully, populated PostgreSQL panels, hidden time/refresh controls and removal of counter-name warning icons. Root, firmware recovery, cold boot/autostart, battery endurance, public access from an independent external network and a complete disaster restore were not tested. The aged Android security patch remains a risk: keep the device dedicated to the display and avoid storing credentials on it.
