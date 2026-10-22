# Гостиная: телевизор как монитор и светофор Grafana

Срез на **22 октября 2026**. Памятка, как устроен Xiaomi в гостиной и что переживает выключение питания. Операционная инструкция на английском — `docs/android-tv.md`. Плейбук — `ansible/playbooks/tv-admin.yml`. Это не замена live-проверке: адрес по DHCP может смениться.

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

Цветные кнопки обрабатывает **tvQuickActions** (`dev.vodik7.tvquickactions.free`), служба доступности `KeyAccessibilityService`. Системное приложение Xiaomi `com.xiaomi.android.tvsetup.partnercustomizer` выключено: иначе оно забирает те же кнопки, и tvQuickActions перестаёт открываться.

| Кнопка | Действие |
| --- | --- |
| BUTTON_11 | Fully Kiosk, светофор Grafana |
| BUTTON_10 | HDMI 1 через `xyz.alchemmist.hdmi` |
| Home | штатный лаунчер `com.google.android.tvlauncher` |

Сами назначения кнопок лежат в приватных данных tvQuickActions. Плейбук их не перезаписывает. Он только держит службу включённой и не даёт приложению Xiaomi её вытеснить. Переназначение кнопок — правка внутри tvQuickActions, не в git.

HDMI 1 для прошивки — `com.mediatek.tvinput/.hdmi.HDMIInputService/HW4`. Настройка **Не менять источник сигнала** — это `settings get global set_auto_play`, значение `1`. Это память последнего входа, а не жёсткая привязка к HDMI: если перед выключением выбран другой источник, после включения вернётся он.

## Grafana на экране

Браузер — Fully Kiosk `de.ozerov.fully`. Стартовый адрес:

`https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light?kiosk=1&hideLogo=1`

- `kiosk=1` — полный киоск Grafana, без верхней полосы диапазона и Refresh.
- `hideLogo=1` — без нижней плашки Powered by Grafana. Голый `?kiosk` верхнюю полосу оставлял.
- `injectJsCode` пустой. JavaScript через Fully считается Plus-функцией и рисует водяной знак PLUS Features Activated. Туда скрипт не возвращать.
- `launchOnBoot`, `kioskMode`, `disableHome` и `disableHomeButton` — false. Киоск здесь только параметр страницы Grafana. Fully не становится лаунчером и не стартует вместе с питанием, иначе закрыл бы картинку HDMI.

Плейбук записывает это в `/sdcard/fully-once-settings.json`. Fully читает файл на следующем старте и удаляет его. Чтобы файл был виден, у Fully разрешены `NO_ISOLATED_STORAGE` и `LEGACY_STORAGE`. Перезапуск Fully — только если файл изменился или передан `-e homelab_tv_fully_reapply=true`.

Вход в Grafana — пользователь `tv`, Viewer. Пароль в секрете `socrat-grafana-tv` пространства `cattle-monitoring-system`. В репозиторий и в эту памятку пароль не кладётся.

Дашборд — UID `socrat-traffic-light`, JSON `charts/monitoring-k3s/dashboards/traffic-light.json`, ConfigMap `socrat-traffic-light-dashboard`. Обновление 5 секунд. `now-15m` — окно графиков, не интервал обновления. Слева плитки сервисов, справа CPU, память, диск и температура, ноды `socrat-0` … `socrat-3` по возрастанию имени. У socrat-2 нет датчика температуры CPU.

Верхняя полоса управления скрыта полем дашборда `timepicker.hidden`, не стилями. Отступ 5px со всех сторон — не настройка Fully и не CSS всего сайта. Приватный шлюз Grafana подмешивает `charts/syncthing/files/traffic-light-inset.js` только на `/d/socrat-traffic-light`, и только если у virtual host `grafana` стоит `trafficLightInset: true`. Флаг есть и в inventory socrat-0, и в `monitoring_wg_access`, чтобы повторный выкат его не стёр. Шлюз — nginx в DaemonSet Syncthing, Grafana на socrat-1, `10.250.0.3:18443`.

Масштаб шрифта Fully 65% и desktop mode выставлены в приложении руками. Плейбук их не хранит.

## Сеть до Grafana

`grafana.socrat.alchemmist.xyz` открывается только из WireGuard. На телевизоре приложение `com.wireguard.android`, туннель `xiaomi-tv`, адрес `10.250.0.8`. Приватный ключ только в `~/.config/homelab/wireguard/xiaomi-tv.key` на машине администратора. Публичный ключ пира — в `ansible/inventory/group_vars/Socrat.yml`. Старый профиль `alchemmist-tv` выключен.

Маршруты раздельные: сеть homelab идёт в туннель, обычный интернет остаётся на Wi-Fi. Поэтому YouTube и Кинопоиск не зависят от VPN.

Пользовательский WireGuard сам туннель после загрузки не поднимает. Плейбук ставит его always-on VPN и оставляет lockdown выключенным (`always_on_vpn_lockdown=0`). Туннель возвращается вместе с телевизором и не запирает остальной трафик.

Fully, tvQuickActions, WireGuard и `xyz.alchemmist.hdmi` стоят в whitelist deviceidle и могут работать в фоне. Иначе Android останавливает их после простоя, и кнопки или туннель не переживают сон.

## Что не автоматизировано

Плейбук не устанавливает Fully, tvQuickActions, WireGuard и помощник HDMI, не задаёт масштаб 65% и desktop mode, не логинит пользователя `tv` и не записывает назначения BUTTON_10 и BUTTON_11. Это уже сделано на этом телевизоре и хранится в его данных. Новый телевизор этими шагами сам не поднимется.
