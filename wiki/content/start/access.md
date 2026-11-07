---
title: "Как получить доступ"
weight: 20
---

Для человека штатный вход в веб-сервисы Socrat — **личная учётная запись Authentik + MFA по обычному HTTPS**. Специальная сеть, DNS overrides и VPN для веб-панелей не нужны. Владелец выдаёт доступ по задаче, а не общий административный пароль.

## Первое подключение

1. Обратитесь через канал, по которому получили приглашение. Укажите имя, нужные сервисы, проект/namespace и задачу: чтение мониторинга, релизы, редактирование wiki или администрирование узлов.
2. Получите личную учётную запись Authentik и безопасный способ установить свой пароль. Настройте собственный MFA. Не используйте QR/сеанс/пароль владельца.
3. Откройте сервис по HTTPS, выберите Authentik/SSO либо дождитесь автоматического перенаправления. Если показан список приложений Authentik, выбирайте только выданные сервисы.
4. Убедитесь, что внутри приложения правильные **личность и роль**. Успешное MFA не означает права на все проекты и не делает пользователя администратором.

Не добавляйте человека в `homelab-owner` ради обычного входа. Роли выдаются минимально необходимыми; root, Harbor robot, deploy key и kubeconfig владельца не являются onboarding kit.

## Где единый вход, а где нужны отдельные права

| Сервис | Вход | Что запросить дополнительно |
| --- | --- | --- |
| Grafana | Native Authentik OIDC | Viewer для чтения; Editor только при необходимости; native admin отдельно |
| Wiki | Публичное чтение; Authentik OIDC для аккаунта | Роль editor для записи, administrator только для управления wiki |
| Harbor | Native Authentik OIDC | Membership/роль конкретного проекта; CI и pull используют scoped robots |
| Argo CD | Native Authentik OIDC | Права на нужные Application; право просмотра не означает sync/delete |
| Rancher | Native Authentik OIDC | Отдельные native bindings и Kubernetes RBAC для согласованных ресурсов |
| Open WebUI | Native Authentik OIDC | Доступ к чату, моделям и рабочим ресурсам в рамках роли |
| LiteLLM browser administration | Native Authentik/OIDC на согласованном входе | Административный допуск ограничен; обычному API-клиенту нужен личный virtual key, не admin login |
| LMS | Authentik OIDC | Учебная роль/группа: student или teacher |
| Search | Authentik MFA-gate | Допуск в согласованную группу, не роль администратора кластера |

## Исключения: Authentik не заменяет native login

**MFA-gate перед сервисом — не native OIDC внутри него.** Он проверяет допуск к входу; затем приложение может требовать собственную учётную запись.

| Сервис | Текущий контур | Что отдельно получить |
| --- | --- | --- |
| n8n Community | Authentik MFA-gate, затем native n8n login; штатный gate сейчас owner-only | Явно согласованный допуск и native учётную запись/права workflow; наличие общего SSO недостаточно |
| Uptime Kuma admin | `kuma.socrat.alchemmist.xyz`: Authentik MFA-gate, затем native Kuma auth | Допуск в admin gate и собственно административный доступ Kuma. Публичный статус входа не требует |
| 3x-ui | Authentik MFA-gate, затем native login панели; gate ограничен владельцем | Отдельное согласование панели, не обычную роль нового администратора |
| Syncthing GUI, если нужен | Authentik MFA-gate, затем сохранённый BasicAuth | Согласованный доступ к конкретному GUI; device/folder approval отдельно |
| Umami 3.4.1 | Пока native учётная запись Umami; Authentik OIDC не внедрён | Учётную запись и права на конкретный сайт/команду; нельзя считать это уже подключённым SSO |

Для Umami upstream route с названием SSO не является generic OIDC-клиентом Authentik. Внешний gate оставит отдельный пароль; настоящая интеграция потребует отдельно спроектированной поддержки. Статус описан на [странице Umami]({{< relref "observability/umami.md" >}}).

## Отдельные доступы, которые не выдаёт SSO

- **API и агенты:** личный LiteLLM virtual key, персональный wiki MCP token, согласованный read-only Grafana MCP bearer. Browser cookies, MFA aliases и пароль Authentik их не заменяют.
- **CI/registry:** scoped Harbor robots и защищённые release credentials; [гайд деплоя]({{< relref "platform/deploy.md" >}}).
- **Ноды:** отдельный NetBird admission, собственный SSH key, Linux/sudo и при необходимости Kubernetes RBAC; [SSH onboarding]({{< relref "network/ssh.md" >}}).
- **Telegram:** [подписка Socrat Bot]({{< relref "platform/socrat-bot.md" >}}) с первым одобрением владельца; Telegram identity не связывается автоматически с Authentik.
- **Пользовательский VPN:** отдельная персональная подписка/профиль, не средство открыть панели; [VPN и NetBird]({{< relref "network/vpn.md" >}}).
- **Внешние интеграции n8n:** отдельные Credentials и scopes подключаемых систем.

Пароли, токены, recovery material и ключи храните в менеджере секретов. Не отправляйте их в общие чаты/issue и не коммитьте. При потере доступа или увольнении сообщите администратору: нужно отозвать не только группу Authentik, но и app sessions, API keys, устройства, SSH/RBAC и Telegram subscription. Старые сеансы не обязаны закрыться сразу после удаления группы.
