# Первичный аудит технического долга Homelab — 16 ноября 2026

Статус: исследование, **не план разрешённых production-изменений**.
База: Git `6a94a88d`. Исследованы исходники, конфигурации, документация и CI.
В рамках этого аудита кластер и опубликованная Wiki не опрашивались и не менялись.
Сведения о принятой миграции — из её handoff, не новая runtime-приёмка.
Наличие технического долга не доказывает наличие эксплуатируемой уязвимости.

## Ключевые результаты

### R1. Два источника установки Argo CD — высокий приоритет

**Подтверждено:** `deploy/argocd/apps/argo-cd.yaml` использует
`deploy/platform/argo-cd/values.yaml`, где application-controller закреплён за
`socrat-5`. Но `ansible/playbooks/argocd.yml:12` читает другой файл:
`deploy/argocd/values.yaml`, и выполняет `helm upgrade --install` в том же release.
В старых values только глобальный selector `socrat-0`, без override контроллера.
`docs/cluster-deploy.md:114` также направляет оператора на этот старый путь.

**Риск:** повтор bootstrap может вернуть controller на `socrat-0` и применить
другой набор настроек. Это риск кода, не утверждение о случившемся запуске.

**Направление:** разделить install-on-empty и сопровождение существующего
Git-owned release; для второго убрать конкурирующий Helm upgrade. Одни values
для bootstrap и Argo либо проверяемый минимальный bootstrap-слой. Проверка:
рендеры совпадают по security/config/resources, существующий release нельзя
незаметно переустановить старым playbook. Обязательно сохранить native SSO/TLS.

### R2. Общий issuer transport скопирован по приложениям — высокий приоритет

**Подтверждено:** IP `10.43.218.222` повторён в активных hostAliases:
`charts/open-webui/values.yaml`, `deploy/{lms,wishlist,wiki-runtime,spi-triage}/values.yaml`,
`deploy/platform/{litellm,rancher}/values.yaml`; отдельно в defaults роли Rancher.
Это scoped-путь к Authentik через существующий Service, а не случайный IP.

**Риск:** пересоздание Service требует согласованно обновлять несколько файлов;
часть приложений может остаться Ready, но потерять native login.

**Направление:** сначала зарегистрировать owner, назначение, источник адреса и
потребителей; добавить offline-проверку согласованности и bounded runtime-check
на соответствие Service. Затем выбрать генерацию небольших values-overlay или
другую общую конфигурацию. Не вводить runtime-генератор как новый SPOF. Простая
замена IP на DNS без проверки прежнего сетевого сбоя проблему не решает.
Нельзя отключать проверку TLS, менять issuer/callback или расширять NetworkPolicy.

### R3. Топология повторена в нескольких слоях — средний/высокий приоритет

Примеры: `ansible/inventory/hosts.yml`,
`ansible/inventory/group_vars/Socrat.yml` (`wg_socrat_nodes`), Helm values,
network policies, operational scripts. `10.250.0.3` встречается в 56 файлах
категорий ansible/charts/deploy/scripts; `10.250.0.1` — в 47. Это количество файлов,
не количество независимых ошибок; среди них есть fixtures/исторические инструменты.
Loopback, bind-address, CIDR и образцы нужно исключать из тревог отдельно.

Особенно явный пример: `ansible/scripts/wg-peer15-relay.py:12–15` содержит FRONT/CLIENT/
BACK/TARGET, `scripts/wg-peer15-endpoint.py:17` отдельно хранит endpoint; playbook
повторяет prerequisite адреса. Связь рабочего relay с `socrat-0`, `socrat-1` и
`socrat-5` должна быть проверяемой, не угадываемой из нескольких файлов.

**Направление:** небольшой типизированный реестр узлов/сетевых endpoint с
ролями адресов (mesh/LAN/SSH/egress), затем проверки потребителей. Не переписывать
всё одним шаблонизатором и не менять рабочую сеть ради чистоты кода. Особенно не
трогать VPN-нагрузки `socrat-2` и AllowedIPs в рамках обычного рефакторинга.

### R4. Current-state и журнал миграций смешаны — высокий приоритет

**Подтверждённые противоречия:**

- `docs/context/context.md` — 1255 строк; раздел о stateless-переносе описывает Monori
  backend на `socrat-0`, SPI worker на `socrat-1`, хотя более новый раздел того же
  файла фиксирует их работу на `socrat-5`.
- `docs/README.md:42` по-прежнему называет SPI runtime migration pending.
- `ansible/inventory/host_vars/socrat-5.yml:3` утверждает, что приложения остаются
  на `socrat-1`; это устаревший комментарий, не значение настройки.
- `wiki/README.md:15` и `docs/wiki.md:15` называют действующим claim
  `wiki-runtime-data`, тогда как `deploy/wiki-runtime/values.yaml` указывает
  `wiki-runtime-socrat5`.
- `docs/cluster-deploy.md:114` не отражает разделённое размещение Argo CD и
  ссылается на старые bootstrap-values.

**Направление:** короткая актуальная карта компонентов/owners/storage/ограничений,
отдельно датированные handoff. Исторические факты не переписывать под настоящее:
добавлять статус superseded и ссылку. Автоматически проверять ссылки на файлы,
активные claims и canonical values. Не требовать, чтобы старые incident receipts
всегда совпадали с текущим размещением.

### R5. Источник обычной Wiki не равен опубликованному состоянию

`wiki/README.md` правильно предупреждает: runtime-volume авторитетен, Git sync
может отставать. Есть и устаревший технический текст в `wiki/content/platform/rustfs.md`
рядом с более новым пользовательским `s3-storage.md`. Это кандидаты на сверку,
а не основание автоматически удалить старую страницу или перезаписать runtime.

**Направление:** отдельно инвентаризировать страницы и публикационную очередь,
сверить чтением опубликованную версию, затем обновлять через поддерживаемый
editor/import/Git workflow. Не редактировать управляемое дерево активного writer,
не публиковать private operational details; сохранить URLs/aliases.

### R6. Матрица authoritative data → backup/restore пока не доказана

**Подтверждено:** активные пути/PVC изменились; например Wiki теперь
`wiki-runtime-socrat5` / `/mnt/files/homelab/wiki-runtime/data`, n8n —
`n8n-socrat5` с bind mount в host_vars `socrat-5`. Старые recoveryStorage n8n на
`socrat-1` сохранены явно и намеренно — это не ошибка, которую надо «почистить».

**Не доказано этим исследованием:** какие действующие расписания покрывают все
новые authoritative datasets, где последняя независимая копия, проводился ли
restore. Наличие Syncthing или Retain само по себе ничего из этого не доказывает.

**Направление:** реестр dataset / writer / PVC / path / backup owner / consistency
method / independent destination / retention / last restore. Это первая следующая
read-only runtime-проверка из-за риска тихой потери актуального покрытия. Старые
volumes не удалять и не объявлять пригодными для rollback после новых записей.

### R7. Миграционные утилиты и тесты не оформлены как lifecycle

В `scripts/` остаются `vm105-stateless-handoff.py`, `vm105-spi-idle-handoff.py` и
другие инструменты узкого перехода. У SPI helper уже есть правильный отказ для
перенесённого worker. Копируется transport SSH→kubectl, timeout/error handling.
Стандартный `unittest discover` нельзя считать безопасным без предварительной
классификации fixtures, внешних зависимостей и возможных side effects.

**Направление:** каталог active / maintenance / one-shot / retired с prerequisites,
безопасным default и явным разрешением записи. Только потом выделять общий
transport. Не ломать специально fail-closed one-shot tools ради универсальности.

### R8. Новые защитные тесты не подключены к основному Quality Graph

`qg.yaml` сейчас задаёт freshness, workflow policy, alert graph delivery и SPI
execution links. Нет узла для `test_vm105_management.py` и
`test_socrat5_app_placement.py`. Их локальный успех не равен обязательной CI-проверке.
`pyproject.toml` dev dependencies содержат Quality Graph, но не PyYAML; новые
тесты импортируют yaml и часть проверок требует Helm.

**Направление:** отдельный воспроизводимый offline infrastructure-contract suite,
явные Python/Helm dependencies, schema/render/owner/endpoint/storage assertions.
Не редактировать generated workflow вручную: менять qg.yaml и генерацию. Сначала
baseline выбранного suite; не прятать прежние ошибки расширенными skip/allowlist.

## Предлагаемая очередность небольших изменений

1. Зафиксировать current-state/owners и сделать bounded аудит backup coverage.
2. Устранить вторую управляющую конфигурацию Argo CD с render-equivalence тестом.
3. Подключить небольшой offline CI-контракт, включая запрет нового дрейфа.
4. Ввести проверяемый каталог endpoint, начать с issuer transport; затем topology.
5. Сократить docs/context, разнести историю; согласовать Wiki публикацию отдельно.
6. Разобрать lifecycle утилит и vendored-исключений, не массово удалять recovery.

Не предлагается массовая замена IP, PVC rename, рестарт сети, перенос новых
сервисов, обновление версий или «починка» native auth упрощением защиты.
Исследование не является полным security audit или доказательством DR.
