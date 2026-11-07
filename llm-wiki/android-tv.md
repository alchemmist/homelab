# Гостиная: телевизор как монитор и светофор Grafana

Срез на **6 ноября 2026** (пульт/холодное включение проверялись пользователем 22 октября). Памятка, как устроен Xiaomi в гостиной и что переживает выключение питания. Операционная инструкция на английском — `docs/android-tv.md`. Плейбук — `ansible/playbooks/tv-admin.yml`. Это не замена live-проверке: адрес по DHCP может смениться.

Общий итог VPS/DNS/NetBird/Mac/public access: [network-access.md](network-access.md). Этот TV setup — окончательный вариант после удаления временного TV домена и внутреннего WG, не промежуточная публикация.

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

Исходники YouTube и Grafana — Smali-код с манифестами в `android/tv-mode/` и `android/tv-grafana/`. Их можно пересобрать на машине с Java командой `./android/build.sh`: Apktool и uber-apk-signer закреплены по версии и SHA-256; скрипт проверяет, что подпись совместима с установленными на ТВ APK. APK попадают в `android/releases/`. `tv-hdmi.apk` — сохранённый оригинальный подписанный APK: исходный ключ подписи HDMI-помощника в репозитории отсутствует.

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
`docs/traffic-light-tv-design.md`. Прямой patch ConfigMap откатывает Argo CD;
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
файлами, не коммитятся. Детали и ограничения — `docs/traffic-light-tv-design.md`.

## Владение dashboard и свежая раскладка — 7 ноября 2026

После monitoring split public policy/TV assets принадлежат Application **grafana**,
`deploy/platform/grafana/public-entry`, не прежнему kube-prometheus-stack app.
Headerless/full-height disk layout изменён в `832e341`; canonical share URL,
Fully55%/font75%, empty injectJsCode и отдельный YouTube VPN не менять по старым
координатам панелей. [Monitoring ownership](observability-current.md). Source update
и проверка Argo не заменяют физический remote/cold-boot тест.
