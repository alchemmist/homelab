# LLM wiki: карта актуального контекста Socrat

Актуализация **9 ноября 2026** (полный SPI service extraction; observer — 8 ноября, остальные срезы датированы в своих разделах). Это рабочая память для сопровождения homelab,
не public wiki content и не набор команд для автоматического повторения миграций.
Git/manifests задают intent; runtime определяется отдельной проверкой.

## Начать здесь

1. [Текущий контекст](context.md) — краткая схема, ограничения и порядок работы.
2. [Сеть и доступ](network-access.md) — **NetBird основной human ingress**, межнодовый
   WG сохранён, standalone WG только recovery, корпоративный Tunnelblick не трогать.
3. [Identity сейчас](identity-current-state.md) — `antropophag`, пароль/первый вход,
   native app links, ограничения Umami и отсутствие автоматического invitation.
4. [Деплой](cluster-deploy.md) — Git → Argo, per-app ingress, image release contract.
5. [Наблюдаемость сейчас](observability-current.md) — новые monitoring owners,
   paused legacy apps, source/status и проверенное размещение.

## Справочники по задаче

| Тема | Документы |
| --- | --- |
| Сетевой onboarding, devices, JWT policies и node agents | [NetBird](netbird.md), [DNS](public-dns.md) |
| VPN/TSPU: конфигурационное усиление текущего VPS, без новых покупок | [Hardening и текущие gates](vpn-hardening.md) |
| Публичный SSH key, обычный Linux account и отзыв | [SSH user](ssh-user.md), [host/RBAC](identity-host-access.md) |
| Observer: обычное групповое подключение, Danila, отзыв доступа | [Native observer](native-observer.md), [приёмка](../docs/identity/observer-acceptance-20261108.md) |
| Главный identity справочник и ежедневные операции | [Identity](identity.md), [операции](identity-operations.md) |
| OIDC, native app roles, gateway exceptions | [Архитектура](identity-architecture.md), [интеграции](identity-integrations.md), [диагностика](identity-gateway-troubleshooting.md) |
| Optional disabled SSH-key integration | [UUID/key assignments](identity-ssh-keys.md) |
| Theme, native UI и recovery | [Frontend](identity-frontend.md), [backup/recovery](identity-recovery.md) |
| Registry, robots, scoped push/pull | [Harbor](harbor.md) |
| Wiki runtime/content | [Процесс](../docs/wiki-process-lifecycle.md), [upgrade](../docs/wiki-upgrade-20261107.md), [public onboarding source](../wiki/README.md) |
| Logs/metrics/traces/profiles | [Мониторинг](observability-current.md), [monitoring](../docs/monitoring.md) |
| Инциденты, уведомления, workflow integration | [Socrat bot](socrat-bot.md), [SPI: полный frontend/backend repo, CI принят, runtime migration pending](spi-incident-triage.md), [n8n](n8n-workflows.md) |
| TV/public dashboard и отдельный YouTube VPN | [Android TV](android-tv.md) |
| LMS и локальные генераторы | [LMS](lms.md), [локальная генерация](lms-generation.md) |
| Остальные scoped подсистемы | [RustFS](rustfs-foundation.md), [Smart home](smart-home-automation.md), [inference reliability](inference-client-reliability.md) |

## Как читать старые результаты

- «Synced/Healthy», passed tests, screenshots и counters действуют для указанного
  среза/ресурса. Не суммировать разные suites и не переносить успех owner/fixture
  на первого настоящего человека, другое устройство, ISP или полный DR.
- `tim` в старом журнале IdP — прежний login, не текущий. Linux `tim`, Rancher
  resource names и `wg-socrat` — отдельные реальные identifiers; массово не менять.
- Сеть NetBird не выдаёт SSH/sudo/cluster-admin. Authentik MFA не заменяет app RBAC.
- «Запушен образ/коммит» не означает rollout; disabled auto-sync и hooks проверять.
- Исторические migration/apply scripts часто меняют production. Перед запуском
  fresh audit, scope/UID/hash, private backup, lock/CAS; uncertain write → разбор.
- Не публиковать credentials, QR, private keys, subscriptions, tokenized share/
  recovery/activation URLs. Публичный hostname не делает machine API anonymous.

Эта редакция изменила только `llm-wiki` и свела уже завершённую приёмку observer
в общую навигацию. Новые runtime-проверки/rollout, пароль/MFA за человека и смена
VPN/DNS при обновлении справочника не выполнялись.

- [Официальные MCP для агентов](official-mcp.md) — project settings, полная сервисная инвентаризация, read-only scope и реальные blockers.
