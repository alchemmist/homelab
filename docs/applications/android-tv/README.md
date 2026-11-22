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

The one-time fleet peer removal is complete; it is not part of TV provisioning or recovery. Preserve the private per-node configuration backups. Never clear WireGuard app data, uninstall it or delete the separate YouTube profile. Both TV playbooks and the focused public acceptance script use the canonical public URL.

Retirement closeout: all four node peer audits report operations=0 (three existing owned peers removed; worker already absent), all three authoritative DNS audits report operations=0, and the exact alias resource audit reports operations=0. At that historical closeout `public-web-entry` was Synced/Healthy; its resources now belong to their service Applications (see public-web-migration.md). Canonical public acceptance: 24/24 two-IP checks; 66 focused tests. The real TV displays live data on the canonical hostname with no active VPN network; YouTube's separate helper was verified foreground with one VALIDATED VPN before returning to Grafana. No physical button/power-cycle claim is implied.

## Гостиная: телевизор как монитор и светофор Grafana

Срез на **6 ноября 2026** (пульт/холодное включение проверялись пользователем 22 октября). Памятка, как устроен Xiaomi в гостиной и что переживает выключение питания. Операционная инструкция на английском — `docs/applications/android-tv/README.md`. Плейбук — `ansible/playbooks/tv-admin.yml`. Это не замена live-проверке: адрес по DHCP может смениться.

Общий итог VPS/DNS/NetBird/Mac/public access: [network-access.md](../../network/README.md). Этот TV setup — окончательный вариант после удаления временного TV домена и внутреннего WG, не промежуточная публикация.

## Зачем он нужен

Две роли, между которыми нужно переключаться одной кнопкой:

1. Монитор сервера. Картинка идёт по HDMI 1.
2. Светофорная панель Grafana в браузере. Кинопоиск и YouTube остаются обычным телевизором: кнопка Home открывает штатный лаунчер, оттуда их можно запустить как обычно.

После включения питания сам поднимается последний источник. Пока это HDMI 1, на экране сразу картинка с сервера. Grafana сама экран не занимает. На неё переключаются цветной кнопкой пульта, когда она нужна.

Пользователь проверил реальное выключение и включение: HDMI, обе цветные кнопки и Home ведут себя так, как описано ниже.

## Железо и доступ

| | |
| --- | --- |
| Модель | MiTV-MOOQ1, устройство `tarzan`, Android 11 |
| LAN | `192.168.0.19`, экран 1920×1080 |
| ADB | с socrat-0: `adb connect 192.168.0.19:5555`, порт `service.adb.tcp.port=5555` |
| Termux SSH | `u0_a44`, порт `8022`, ключ только на socrat-0: `~/.ssh/homelab-tv` |

ADB — это shell UID 2000, не root. `persist.adb.tcp.port` без root не ставится, поэтому после холодной перезагрузки сетевая отладка может не вернуться, пока её снова не разрешат на телевизоре. Автозапуск SSH в Termux не настроен.

Плейбук ставит `adb` на socrat-0, заводит ключ, проверяет модель и приводит настройки ниже к описанному виду. Он не ставит приложения и не обходит подтверждение отладки. Приложения уже установлены вручную.

```sh
cd ansible
ansible-playbook playbooks/tv-admin.yml --ask-become-pass
```

Принудительно выбрать HDMI 1 в этом прогоне: `-e homelab_tv_select_hdmi=true`. Заново залить стартовый URL Fully: `-e homelab_tv_fully_reapply=true`.

## Пульт

Цветные кнопки — это не настройка прошивки и не запись в git. Их перехватывает **tvQuickActions** (`dev.vodik7.tvquickactions.free`, сборка `3.3.2-free`), служба доступности `KeyAccessibilityService`. Пока служба включена, нажатие физической кнопки не уходит в Кинопоиск, Okko или IVI, а выполняет действие из приватной базы приложения.

Системное приложение Xiaomi `com.xiaomi.android.tvsetup.partnercustomizer` выключено. Если его включить, оно снова заберёт эти клавиши: tvQuickActions перестанет открываться и видеть нажатия. Плейбук держит его выключенным и заново включает службу доступности, если та сбросилась. Сами строки «кнопка → действие» он не перезаписывает.

Home сюда не входит. Это системная кнопка, лаунчер остаётся `com.google.android.tvlauncher`. Из него по-прежнему запускаются Кинопоиск и YouTube. Fully не делать домашним экраном.

### Что нажато сейчас

Одиночное нажатие. Двойное и долгое в приложении есть, но на этих кнопках не используются.

| Кнопка | Код Android | Действие |
| --- | --- | --- |
| BUTTON_11 | 198 | открыть `xyz.alchemmist.grafana` («Grafana»): отключить YouTube VPN, если включён, и открыть публичный светофор в Fully Kiosk без подключения VPN |
| BUTTON_10 | 197 | открыть `xyz.alchemmist.hdmi`, это HDMI 1 |
| BUTTON_14 | 201 | открыть Кинопоиск (`ru.kinopoisk.tv`) |
| BUTTON_16 | 203 | открыть `xyz.alchemmist.tvmode` («YouTube VPN»): переключить WireGuard на профиль `alchemmist-tv` для глобальной сети и открыть YouTube |
| Home | — | штатный лаунчер, tvQuickActions её не ловит |

Все назначенные горячие клавиши заданы как «открыть приложение», не как shell-команда. Поэтому они живут без сетевой отладки. Помощник `xyz.alchemmist.grafana` отключает только `alchemmist-tv`, ждёт исчезновения VPN-сети и открывает Fully с сохранённым публичным URL. Он не подключает никакой туннель. `xyz.alchemmist.hdmi` выбирает HDMI 1. Помощник `xyz.alchemmist.tvmode` подключает единственный оставшийся профиль `alchemmist-tv`, ждёт `VALIDATED` и открывает YouTube. Настройки/ключ этого глобального профиля не менялись. Оба helper APK обновляются совместимой прежней подписью и больше не содержат `xiaomi-tv` или записи always-on VPN. Назначения кнопок не переписывались.

### Исходники и установка помощников

Исходники YouTube и Grafana — Smali-код с манифестами в `deploy/tv/android/tv-mode/` и `deploy/tv/android/tv-grafana/`. Их можно пересобрать на машине с Java командой `./deploy/tv/android/build.sh`: Apktool и uber-apk-signer закреплены по версии и SHA-256; скрипт проверяет, что подпись совместима с установленными на ТВ APK. APK попадают в `deploy/tv/android/releases/`. `tv-hdmi.apk` — сохранённый оригинальный подписанный APK: исходный ключ подписи HDMI-помощника в репозитории отсутствует.

Плейбук `ansible/playbooks/tv-admin.yml` устанавливает/обновляет все три homelab-помощника и выдаёт VPN/secure-settings разрешения, поддерживает нужные приложения в whitelist standby и удаляет Happ. Он не устанавливает Fully, tvQuickActions или WireGuard. WireGuard-профили импортируются на ТВ вручную; их приватные ключи не хранятся в репозитории. Плейбук также не переписывает приватную базу назначений кнопок tvQuickActions — их задают вручную по инструкции выше.

Для BUTTON_16 достаточно бесплатного действия tvQuickActions «открыть приложение» → `YouTube VPN`. Платные макросы, ADB-команды и custom actions не используются. Нельзя назначать кнопку напрямую на YouTube: тогда перед его запуском не переключится VPN.

HDMI 1 для прошивки — `com.mediatek.tvinput/.hdmi.HDMIInputService/HW4`. Настройка **Не менять источник сигнала** — это `settings get global set_auto_play`, значение `1`. Это память последнего входа, а не жёсткая привязка к HDMI: если перед выключением выбран другой источник, после включения вернётся он.

### Как поменять

Менять в самом tvQuickActions с пульта. В git это не коммитится: база лежит в приватных данных приложения и переживает перезагрузку. Повторный прогон `tv-admin.yml` назначения не стирает.

1. Home, затем список приложений, открыть tvQuickActions. Цветной кнопкой его не открыть: она уже занята действием.
2. Нажать на пульте ту кнопку, которую нужно переназначить. Приложение покажет её как текущую.
3. Задать действие одиночного нажатия. Для Grafana — запуск `Grafana` (`xyz.alchemmist.grafana`), не Fully напрямую. Для HDMI — `xyz.alchemmist.hdmi`. Для YouTube — `YouTube VPN` (`xyz.alchemmist.tvmode`), а не YouTube напрямую. Двойное и долгое нажатие можно занять отдельно, если нужно второе действие на той же кнопке.
4. Выйти и проверить физическим нажатием. `adb shell input keyevent` службу доступности не проверяет: ввод с компьютера может не дойти до tvQuickActions, хотя пульт работает.

Новая свободная цветная кнопка назначается тем же путём: открыть приложение и нажать её. Стоит сборка free. Если она не даст добавить ещё одну кнопку, предел у этой сборки, а не у плейбука.

Внутри приложения есть и другие типы действий: intent, меню, ADB-команда. Для этих назначений достаточно запуска приложения; ADB-команда завязана на отладку, а сетевая отладка после выключения питания может не вернуться.

Если кнопка должна открывать светофор, цель — Fully, не адрес в обычном браузере. Масштаб, вход `tv` и киоск хранятся в Fully. Если кнопка должна вернуть картинку сервера, цель — `xyz.alchemmist.hdmi`. Для YouTube с VPN цель — приложение `YouTube VPN`; оно само выполняет смену туннеля. Тот же вход HDMI без помощника, если приложение придётся заводить заново:

```sh
am start -n com.mediatek.wwtv.tvcenter/com.mitv.livetv.tv.MainActivity \
  -a android.intent.action.VIEW \
  -t vnd.android.cursor.item/channel \
  -d content://android.media.tv/passthrough/com.mediatek.tvinput%2F.hdmi.HDMIInputService%2FHW4
```

### Если кнопки замолчали

Сначала не переназначать их заново. Обычная поломка: служба доступности выключена или Xiaomi снова забрала клавиши. С socrat-0:

```sh
adb connect 192.168.0.19:5555
adb -s 192.168.0.19:5555 shell settings get secure enabled_accessibility_services
adb -s 192.168.0.19:5555 shell pm list packages -d
```

В списке служб должна быть `dev.vodik7.tvquickactions.free/dev.vodik7.tvquickactions.KeyAccessibilityService`. Среди выключенных пакетов должен быть `com.xiaomi.android.tvsetup.partnercustomizer`. Оба условия возвращает плейбук, назначения кнопок при этом остаются:

```sh
cd ansible
ansible-playbook playbooks/tv-admin.yml --ask-become-pass
```

После этого tvQuickActions снова открывается из списка приложений, и в нём видны те же действия.

## Grafana на экране

Браузер — Fully Kiosk `de.ozerov.fully`. Стартовый адрес:

`https://grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>?kiosk=1&hideLogo=1&autofitpanels=true&socratTv=1`

Это native public sharing **только** `socrat-traffic-light`, без входа и без anonymous Viewer всей организации. Точный URL берётся без подмены hostname из root-private `/var/lib/homelab-grafana-tv-public/fully-url.json` на socrat-0. Отдельный `tv.alchemmist.xyz` отменён и удалён. Внутренний профиль `xiaomi-tv` удалён из WireGuard на ТВ; его peer отозван на серверах, а inventory больше его не создаёт. Обычные дашборды и API сохраняют SSO/роли.

- `kiosk=1` — полный киоск Grafana, без верхней полосы диапазона и Refresh.
- `hideLogo=1` — без нижней плашки Powered by Grafana. Голый `?kiosk` верхнюю полосу оставлял.
- `injectJsCode` пустой. JavaScript через Fully считается Plus-функцией и рисует водяной знак PLUS Features Activated. Туда скрипт не возвращать.
- `launchOnBoot`, `kioskMode`, `disableHome` и `disableHomeButton` — false. Киоск здесь только параметр страницы Grafana. Fully не становится лаунчером и не стартует вместе с питанием, иначе закрыл бы картинку HDMI.

Плейбук записывает это в `/sdcard/fully-once-settings.json`. Fully читает файл на следующем старте и удаляет его. Чтобы файл был виден, у Fully разрешены `NO_ISOLATED_STORAGE` и `LEGACY_STORAGE`. Перезапуск Fully — только если файл изменился или передан `-e homelab_tv_fully_reapply=true`.

Для публичного светофора вход **не нужен**. Прежний пользователь `tv` / Secret `socrat-grafana-tv` не использовались и не менялись; это исторический приватный доступ, не публичный пароль.

Дашборд — UID `socrat-traffic-light`, JSON `charts/monitoring-k3s/dashboards/traffic-light.json`, ConfigMap `socrat-traffic-light-dashboard`. Обновление 5 секунд. Текущее live-окно — `now-12h` (проверено 6 ноября), не интервал обновления; прежняя памятка описывала `now-3h`. JSON дашборда при публикации не менялся. Слева плитки сервисов, справа CPU, память, диск и температура, ноды `socrat-0` … `socrat-3` по возрастанию имени. У socrat-2 нет датчика температуры CPU.

Приватный старый маршрут `/d/socrat-traffic-light` сохраняет свой JS `charts/syncthing/files/traffic-light-inset.js` и `trafficLightInset: true`. Его ConfigMap/Pod и Syncthing не менялись. Публичный policy nginx подмешивает `deploy/platform/grafana/public-entry/files/traffic-light-inset.js`. Только для public URL с `socratTv=1` и проверенным UID он переносит 5px inset, скрывает header/footer и восстанавливает autofit: native public scene не применяет старые kiosk/autofit-параметры. Геометрия берётся из **скомпактированного** native layout, а не из потенциально пересекающихся `gridPos`; 51 панель была результатом приёмки6 ноября; текущий состав/layout изменён7 ноября
и определяется dashboard JSON, а не этим старым количеством. JS/CSS остаются серверными, `injectJsCode` Fully пустой.

Для **только URL**, без полного TV provisioning, использовать `ansible/playbooks/tv-public-dashboard.yml`: сначала аудит, затем `tv_public_apply=true` и свежий `tv_public_hash`. Он требует уже авторизованный ADB, Fully на переднем плане и отсутствие чужого pending import; импортирует ровно `startURL`, перезапускает только Fully и проверяет неизменность DNS/VPN guard. При `tv-uncertain.json` повторять нельзя без проверки приватных receipts. 6 ноября файл успешно прочитан Fully, public page с живыми данными проверена реальным ADB screenshot. Пульт, HDMI и холодное включение повторно не тестировались и не перенастраивались.

Масштаб страницы Fully задаётся плейбуком как 55% через `initialScale`, размер веб-шрифта — 75% через `fontSize`; desktop mode остаётся включённым вручную.

## Сеть до Grafana

Светофор работает через обычный публичный `grafana.socrat.alchemmist.xyz`. Внутренний туннель/ключ `xiaomi-tv` (бывший `10.250.0.8`) удалён через UI WireGuard, а серверный public peer удалён из persistent/runtime конфигурации всех узлов, где он существовал. Остальные peer bindings сохранены; интерфейсы не перезапускались. Приватные исторические backups не уничтожались.

На ТВ остался **только** `alchemmist-tv` для YouTube, `10.0.0.10`: его ключ/конфигурация не читались и не заменялись. Профиль включается YouTube-помощником по требованию. `always_on_vpn_app` очищен, lockdown выключен; новый setup не восстанавливает автоподключение внутренней сети. Android Private DNS остаётся `off`, как раньше, для совместимости YouTube; DNS/маршруты самого глобального профиля не менялись. Для Grafana после отключения YouTube VPN используются Wi-Fi и обычное публичное разрешение имени.

Проверен переход помощниками: YouTube запустился с `VALIDATED` VPN; Grafana затем открылась без активной VPN-сети. Это не проверка физического пульта или холодного включения — назначения/HDMI не менялись.

## Что не автоматизировано

Плейбук устанавливает только homelab-помощники HDMI/Grafana/YouTube VPN и удаляет Happ. Сторонние Fully, tvQuickActions, WireGuard и VPN-профили нужно завести отдельно. Профиль глобального VPN для YouTube импортируется в WireGuard как `alchemmist-tv` из приватного файла конфигурации; исходный `tv.conf` и его ключ нельзя класть в git. Внутренний профиль для Grafana больше не нужен и не импортируется. Плейбук не задаёт масштаб 65% и desktop mode, не логинит пользователя `tv` (публичному светофору вход не нужен) и не записывает назначения кнопок. На новом телевизоре приложения, VPN-профили и сами кнопки потребуют ручной настройки; для публичного светофора нужны созданный native share и его URL, а не пароль Grafana.

## TV dashboard rollout, 7 ноября 2026

В GitOps выпущен `208e2ea`: CPU показывает занятые логические ядра, RAM и корневой
диск — абсолютный объём (GiB), длина полосы нормализована к ёмкости конкретной ноды.
История CPU над VPN заменена на p95 домашнего HTTP Traefik; внизу добавлен список
до трёх активных critical/warning проблем. Текущий VPN Stat со sparkline сохранён.
Argo CD подтвердил Synced / Healthy. Публичный URL открыт и визуально проверен
в Chromium 1920×1080; это не проверка физического ТВ с масштабом Fully. Детали:
`docs/applications/android-tv/traffic-light-tv-design.md`. Прямой patch ConfigMap откатывает Argo CD;
публиковать нужно через Git. Доступ к публичному URL не требует WireGuard.

## Актуальная раскладка после визуальной правки 7 ноября

Релизы `832e341` (dashboard) и `757dc18` (kiosk presentation): сетка **24×16**,
CPU/Memory/Disk по **8 строк** высотой. Абсолютные значения, относительная длина
полос и пороги сохранены. RPS и n8n стоят рядом, каждый `w=7,h=4`; у новых блоков
нет шапок, info, легенд и плашек диапазона. Под ними три отдельных читаемых Stat
n8n. Вместо полосок по приложениям Argo — две state-timeline дорожки: Git / Apps.
Сервисные имена пока сохранены: анонимизация кубиков не понадобилась для места.

Проверять **оба** маршрута: фактический `/public-dashboards/<token>?...&socratTv=1`
и `/d/socrat-traffic-light?kiosk=1&hideLogo=1&autofitpanels=true`. У ordinary kiosk
был независимый баг native autofit, сжимавший ресурсы и оставлявший пустоты. Только
для этого opt-in режима активный policy asset
`deploy/platform/grafana/public-entry/files/traffic-light-inset.js` теперь применяет
такую же равномерную fit-сетку; edit/viewPanel не перехватываются. Auth hover сохранён.
Shared scene по-прежнему использует compacted layout, authenticated fit принимает
только целую collision-free сохранённую сетку. UI редактирования, auth и Fully не менялись.

Реальная браузерная проверка четырёх комбинаций (оба маршрута × 1920×1080 / 1440×900):
55 панелей, одинаковая pixel-высота CPU/Memory/Disk (531 / 441 px), общая нижняя
граница Disk/VPN, без пересечений и обрезания Stat. Скрипт:
`scripts/check-traffic-light-tv-layout.cjs`; URL и session state передаются приватными
файлами, не коммитятся. Детали и ограничения — `docs/applications/android-tv/traffic-light-tv-design.md`.

## Владение dashboard и свежая раскладка — 7 ноября 2026

После monitoring split public policy/TV assets принадлежат Application **grafana**,
`deploy/platform/grafana/public-entry`, не прежнему kube-prometheus-stack app.
Headerless/full-height disk layout изменён в `832e341`; canonical share URL,
Fully55%/font75%, empty injectJsCode и отдельный YouTube VPN не менять по старым
координатам панелей. [Monitoring ownership](../../observability/monitoring/observability-current.md). Source update
и проверка Argo не заменяют физический remote/cold-boot тест.

## Полоска Argo и обновление раскладки — 11 ноября 2026

Новый owner layout хранится в Git; полоска909 внизу x0,y19,w12. Native bar/group
width уже1 (максимум), поэтому для заметного утолщения увеличен сам модульh1→h2.
TV fit теперь21 строка вместо20: прочие gridPos не менялись; общая авто-подгонка
может немного изменить их pixel-высоту. Fully55%/font75%, public URL, серверный
presentation JS/CSS, VPN и пульт не изменялись. На свежем public URL при1920×1080
до изменения canvas полосы27px. Это браузерный замер, не физический TV screenshot.

В этом прогоне с socrat-0 адрес192.168.0.19:5555 недоступен; ни ADB5555, ни
Termux8022 listeners в LAN не обнаружены. Не обходили авторизацию и не включали
отладку принудительно. Физическая приёмка/reload Fully пока недоступны.
Refresh5s обновляет метрики, но не гарантирует подхват новой геометрии уже открытой
страницей. После layout rollout обновить страницу в Fully; не считать постоянно
открытую вкладку обновлённой только по движению значений. Не менять масштаб всего
дашборда ради одной полосы и не запускать полный TV provisioning для reload.

После rollout9a47ee49 fresh anonymous public browser verified: canvas27→76px при
1920×1080 (≈2.8×). Emulated55% viewport3491×1964,DSF0.55: canvas72→160CSSpx;
это только эмуляция масштаба, не замер устройства. Public909 query HTTP200.
32 tests passed, scoped Helm diff only canonical ConfigMap, Argo Synced/Healthy.
Live exact dashboard comparison (excluding version) confirms only909.h changed.
Физический TV/его открытая вкладка по-прежнему не проверены и не перезагружены.

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

Приёмкаeb7cd6a3:49 actual query frames=49 named K8s Applications. Signed-in normal
и kiosk: по49 resolved native browser-title links, наведение проверено на КАЖДОМ
из49 блоков при1920×1080 и1440×900, все bounds внутри панели. Public1920 и55%-
emulation:49 целиком видимых блоков; native высота76.66px.32 tests, ArgoSynced/Healthy;
live diff only909. Это browser acceptance, не физический TV screenshot.

15:16MSK11Nov: адрес из wiki192.168.0.19:5555 теперь отвечает, но adb devices
показываетunauthorized (socrat-0 SSH useralchemmist); модель ещё не подтверждена.
Не обходили авторизацию, не сбрасывали ключи/настройки, не reload Fully через ADB.
Для реального device screenshot требуется разрешённый ADB; для новой геометрии
уже открытой страницы — reload Fully. Не считать адрес сам по себе проверкой модели.

## Реальный TV diagnosis: subpixel Bar gauge, 11 ноября 2026

ADB теперь авторизован; getprop confirmsMiTV-MOOQ1/tarzan, Fully foreground. Сняты
реальные screencap before и после reload толькоFully (pending import отсутствовал).
Reload не исправил49 блоков, выглядевших как редкие волоски. Важно: native screencap
пишет65 bytesvendor diagnostics передPNG; strip доPNG signature до открытия картинки.

Аудит через UI: Fully initialScale55%,font75%, desktop=true, wideViewport=true,
overview=false сохранены. РеальныйWebView156.0.8078.47, Android density320/DPR2.
Для точного read-only DOM audit временно включена бесплатная Webview Contents
Debugging (originalfalse); CDP идёт через authorized ADB и SSHloopback-only tunnel,
не public port, не Fully JS injection. После приёмки вернутьdebugfalse и снятьforward.

Фактический viewport innerWidth1024,innerHeight575; screen960×540CSS,visualScale0.9375.
Не эмулироватьTV как3491CSSpx/DSF0.55: это была неверная модель. В старомw12,h2:
панель503CSSpx, content485;49 баров с48 native gaps×10px оставляли всего5px на
цветные части:каждый0.10156CSSpx (≈0.19 physicalpx). DOM count49 и bounds check
проходили, но rasterization делала большинство невидимыми. Не проблема данных или
высоты; уменьшениеminVizWidth до0 только предотвращалоclip, не обеспечивало видимость.

Scoped native fix:909 width12→24 в пустую правую половину нижней строки, x0,y19,h2
unchanged. Other panels/settings untouched, no CSS/JS/plugin/zoom/DPI changes.90
empty cells remain. New regression requires≥8CSSpx per49 bars atviewport1024.

Приёмка0a5f53fb выполнена НА ФИЗИЧЕСКОМ ТВ после Page.reload его WebView:
49 native bars/49 app links, panel1014CSSpx, eachbar10.523CSSpx vs0.10156 before;
height28.578CSSpx unchanged. Final ADB screenshot1920×1080 после выключенияdebug
проверен визуально и поPNG scanline1025:49 отдельных цветных участков шириной
18–20physicalpx. Это не fixture/emulation. Скриншоты/DOM evidence private/tmp:
`tv-actual-gauge-before.png`, `tv-actual-gauge-final.png`, `tv-dom-before-width.json`,
`tv-dom-after-width.json`.33 tests pass; exact live dashboard diff only909.w,
scoped Helm only canonical CM, ArgoSynced/Healthy. No unrelated dirty VPN files touched.

Cleanup verified: Webview Contents Debugging вернули в исходноеfalse через UI;
/proc/net/unix больше не показываетdebug socket; ADB forward19222 removed, SSH
loopback tunnel closed, own temporaryuiautomator XML deleted. Fully foreground,
actual updated dashboard already loaded: owner reload not needed for this release.
Fully zoom/fonts/desktop/wideViewport, DNS/VPN/remote keys/HDMI unchanged. Initial
scale55 is not a substitute for measuring actual viewport/DPR on the device.

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

**Текущее согласованное решение:** native Bar gauge909 остаётся в ручном размере
`x0,y19,w12,h1`. Только на public TV-странице с `socratTv=1` применяется адресное
оформление. Это явно одобренное владельцем исключение, не разрешение менять весь
дашборд CSS-правками.

- **Git-источник:** `deploy/platform/grafana/public-entry/files/traffic-light-inset.js`,
  функция `compactArgoRules()`. Доставляется существующим Grafana policy proxy,
  а не настройкой `injectJsCode` Fully. CSS ограничен
  `.socrat-tv-public-grid [data-viz-panel-id="panel-909"]`.
- **Параметры:** внутренний padding8→3 CSSpx; промежутки10→2 CSSpx. Flex заново
  распределяет ширину ячеек; отдельно растягивается native data-link wrapper и
  цветная заливка. Уменьшить только margin недостаточно: Grafana уже вычислила
  субпиксельную ширину баров с учётом своих10px промежутков.
- **Почему TV отличался:** физический экран1920×1080, но реальная страница1024CSSpx,
  DPR2/visualScale0.9375. Не использовать старую эмуляцию3491CSSpx/масштаб0.55 как
  доказательство. При49 приложениях прежние48 промежутков занимали480CSSpx из
  примерно485 доступных, оставляя каждому бару лишь0.10CSSpx.
- **Границы:** обычные signed-in просмотр/редактирование/kiosk не меняются;
  общая сетка, другие панели, native цвета/данные/ссылки, масштабы Fully55% и
  шрифт75% не изменены. Классы добавляются только после проверки UID, типа и
  структуры native DOM. Нет данных/неподдерживаемый DOM — отказ от модификации,
  а не нарисованные зелёные блоки. Число приложений динамическое, не фиксированные49.
- **Регрессии:** `tests/test_grafana_tv_public.py` проверяет область действия,
  защитные условия и сохранность native данных. При изменении asset требуется
  проверить scoped Helm diff; допустимы policy ConfigMap и checksum его proxy
  Deployment. Проверить и обновить только соответствующие два reviewed hash в
  `tests/fixtures/public-entry-handoff.json`, не переписывать hashes других owners.
- **Приёмка:** проверить наличие всех приложений, фактическую ширину/высоту заливок
  и полное попадание внутрь панели. Количество DOM-элементов само по себе не
  доказывает видимость. Нужен настоящий ADB screenshot плюс замеры в WebView;
  preview/mixed-state fixture не выдавать за физический TV. Последний результат:
  49 видимых блоков14–15physicalpx шириной в исходной половине строки.
- **Обновление:** Git→Argo Application `grafana`→существующий policy proxy;
  не перезапускать backend Grafana/Prometheus ради CSS. После доставки перечитать
  страницу TV: metric refresh5s не заменяет загрузку новой версии JS/model.
  Временную WebView-отладку возвращать в исходное состояние, ADB/SSH forward закрывать.

### Свежесть и точный смысл Argo-цветов

Это instant latest-state, не история и не среднее. Argo metrics собираются15s,
дашборд обновляет запросы5s: обычно несколько–20s после изменения, уже отражённого
самим Argo; это не мгновенный push и не строгая максимальная задержка. Freshness90s,
up/inventory guards не должны выдавать устаревший/неполный набор за свежий зелёный.
Ready = Healthy+Synced; синий = Progressing; красный = Degraded/Missing;
оранжевый = OutOfSync/Suspended; серый = Unknown. Операция Syncing отдельно не
отслеживается, короткий переход может пройти между сборами. Все зелёные означают
последние свежие состояния Applications, не доказательство доступности всех сервисов.

Код TV-fix: `c6121e19`, интеграция с concurrent main: `f37bdda6`, физическая
приёмка/cleanup: `f459af38`. MoscowIP и ручная раскладка также сохранены в Git;
не возвращать старые принудительные размерыw24/h2 при следующей генерации.

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
