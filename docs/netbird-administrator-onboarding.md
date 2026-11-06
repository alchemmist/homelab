# Администраторы: Authentik → NetBird → внутренняя сеть

## Коротко: что делает владелец и что делает человек

**Владелец:** создаёт личную обычную учётную запись в Authentik, выдаёт человеку
безопасный способ установить свой пароль, добавляет одну группу
**`netbird-internal-admins`**. Не выдаёт `homelab-owner`, Authentik superuser,
NetBird owner/admin, setup key, свой SSH private key или kubeconfig.

**Пользователь:** устанавливает официальный NetBird, указывает self-hosted server
**`https://netbird.socrat.alchemmist.xyz`**, нажимает Connect, проходит личный вход
Authentik и настройку MFA. После синхронизации получает маршруты к узлам.

Не нужны WireGuard-конфиг, setup key, персональные resolver-файлы, static routes,
SSH jump-host, индивидуальная NetBird policy или ручное редактирование Kubernetes.
Адрес self-hosted сервера — обязательный выбор в стандартном клиенте, а не
дополнительный конфигурационный файл; по умолчанию приложение обращается к Cloud.
Приложение само генерирует уникальную device identity. Не копировать профиль
владельца или identity другого устройства.

## Реальные границы прав

- Доступ к четырём host resources `10.250.0.1/32`, `.3/32`, `.2/32`, `.5/32`
  выдаётся существующими **групповыми** правилами; user/device policy не нужна.
- Это доверенная роль внутренних сетевых администраторов, не ограниченная роль
  наблюдателя. Существующие admin policies разрешают доступ ко всему выбранному
  хосту, не только SSH. Не добавляйте случайного пользователя в эту группу.
- Нет default route/exit node, LAN `/24`, Pod/Service CIDR и All-to-All policy.
- NetBird использует четыре routing peers и существующий серверный `wg-socrat`.
  Он не заменяет межсерверный транспорт. Не удалять mesh-ключи/AllowedIPs нод.
- NetBird network admission **не создаёт Linux-пользователя**, не добавляет SSH
  `authorized_keys`, Kubernetes RBAC или роль приложения. Обычный OpenSSH остаётся
  с собственной авторизацией; NetBird SSH выключен. Если человеку нужен именно
  shell/kubectl, оформите отдельную личную авторизацию, не раздавайте ключи владельца.

## Постоянные владельцы настроек

| Настройка | Владелец |
|---|---|
| Личность, пароль, MFA, группа `netbird-internal-admins` | Authentik |
| OIDC application/provider, group claim | Authentik; `netbird-access.yml` проверяет и аддитивно согласует |
| JWT allow groups, DNS management exclusions | Native NetBird API; тот же audit-first playbook |
| JWT-группа админов, route/INPUT policies, devices | Native NetBird API, не YAML-копии identity DB |
| Workloads/volumes/node agents/relays | Root → NetBird Argo CD, `deploy/netbird/values.yaml` |
| Новые cluster nodes | Отдельная процедура `netbird-node-onboarding.md` |
| Mac + Tunnelblick | `netbird-tunnelblick-coexistence.md`; Tunnelblick не менять |

Регулярное заведение **человека не требует запуска node onboarding**,
перевыпуска enrollment keys, deploy или рестарта server/router.

## Почему группы теперь передаются корректно

Для нового админа одновременно должны выполняться **три** условия:

1. Authentik application допускает группу `netbird-internal-admins`.
2. NetBird `jwt_allow_groups` допускает её, `groups` claim и propagation включены.
3. OIDC действительно передаёт группы именно того пользователя, который вошёл.

В штатном embedded IdP 0.82 фактический redirect к Authentik запрашивает
`openid profile email`, **не `groups`**. Поэтому присоединение стандартного
scope-mapping `groups` само по себе не работает. Выделенный mapping
`homelab-netbird-profile-groups`, attached **только к провайдеру NetBird**, добавляет
в обязательный scope `profile`:

```python
return {"groups": [group.name for group in request.user.ak_groups.all()]}
```

Обычные profile/email mappings сохранены. Нет фиксированных username/email,
списка избранных устройств или синтетического `issued: api` вместо JWT-группы.
Отдельное одобрение каждого SSO-пользователя отключено
(`extra.user_approval_required=false`); peer approval остаётся выключенным.
Проверенные группы Authentik и MFA являются входным approval gate;
публичная регистрация без группы не разрешена.

Subject остаётся `user_uuid`; issuer/application slug `netbird-pilot` сохранён как
стабильный identity identifier. Косметическое переименование issuer ломает вход
и не является полезной «чисткой».

В server-side DNS settings встроенная группа **All** включена в
`disabled_management_groups`: исключение действует и на новые устройства.
Пользователю не нужно включать CLI `--disable-dns` самому. Проверенный Mac
дополнительно сохраняет эту защиту локально. Отсутствие NetBird DNS не запрещает
системный DNS пользователя и не меняет Tunnelblick.

## Первичная проверка/восстановление инфраструктуры

Обязательный безопасный entrypoint, audit по умолчанию:

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml playbooks/netbird-access.yml \
  -e @/private/path/become.yml
```

Выводит только purposes/counts/`plan_sha256`. Для согласованного изменения:

```sh
# Тот же запуск с approval свежего audit:
-e netbird_access_apply=true \
-e netbird_access_approve_plan_hash=<FRESH_64_HEX_HASH>
```

`--check` не меняет API. Helper использует уже существующие private credentials
контроллера; их значения не копируются человеку/в Git/argv. При uncertain receipt
остановиться, прочитать protected before/receipt, сверить actual state. Не повторять
POST/DELETE автоматически и не восстанавливать всю identity DB поверх live данных.

## Добавление нового администратора

1. В Authentik создать отдельного **обычного** пользователя с уникальным username
   и проверенным адресом. Не использовать общего пользователя команды.
2. Передать начальную регистрацию/восстановление через защищённый канал и
   ограниченную по времени ссылку, если recovery flow настроен. Не обещать email,
   пока SMTP/recovery не проверены. Альтернатива — безопасно переданный временный
   пароль с личной сменой. Не публиковать пароль, MFA seed/QR или recovery URL.
3. Добавить группу `netbird-internal-admins`. Не добавлять пользователя в старые
   pilot-группы: они сохраняют отдельный, ранее выданный ограниченный доступ.
4. Для автоматизации вместо ручной группы — private extra-vars:

   ```yaml
   netbird_access_action: grant
   netbird_access_username: <EXACT_USERNAME>
   netbird_access_expected_user_uuid: <REVIEWED_AUTHENTIK_UUID>
   ```

   Запустить audit playbook с `-e @/private/path/person.yml`, проверить план,
   затем apply с его hash. Применяется **add_user**, не замена всех memberships.
   Другие группы и приложения не изменяются. Повторный grant — no-op.
5. Человек устанавливает клиент, выбирает указанный self-hosted server и лично
   проходит Authentik/MFA. Обновление группы существующему пользователю требует
   **свежей личной авторизации**, не только повторного использования cached token.
6. В NetBird убедиться: обычная human role `user`, UUID/connector соответствуют
   Authentik; JWT-группа админов получила устройство; нет owner/admin escalation,
   pending approval, blocked или expired session. Не подменять JWT API-группой.
7. Проверить на **его** устройстве: четыре маршрута появились, новый TCP/SSH к
   внутреннему адресу проходит (native SSH credential — отдельно). Для web —
   правильный TLS/SNI и собственная роль пользователя, не только login page.
8. Отрицательная проверка: не-админ не получает admin resources; пилотная роль не
   превращается в администратора. Добавление следующего админа не меняет router,
   resource или policy IDs и не требует перезапуска остальных клиентов.

## Отзыв и увольнение

Не обещать мгновенный отзыв по одному удалению Authentik-группы: текущие JWT и
устройства могут жить до refresh/expiry (сейчас 8 часов).

- `action: revoke` снимает **только admin membership**. Это изменение роли,
  не экстренное отключение существующей NetBird-сессии.
- Для полного немедленного offboarding — **`action: offboard`**, тот же точный
  username/UUID и approved hash. Helper связывает UUID с настоящим Dex
  subject/точным Authentik connector, блокирует обычного NetBird user, удаляет
  **только его** устройства и снимает admin membership. Не меняет service peers,
  реальные owner/admin accounts, email-linking или другие приложения.
- Затем отключить личность в Authentik по общей процедуре и отдельно отозвать
  SSH keys, kubeconfig/certificates/RBAC и app sessions, если они выдавались.
- Если нужны лишь меньшие сетевые права, проектировать отдельную роль, не делать
  полный offboarding. Заблокированного человека нельзя автоматически разблокировать
  простым повторным добавлением Authentik-группы — требуется отдельное review.
- Проверить новые соединения с его устройства и отсутствие возвращающегося peer.
  Удаление device без блокировки личности не мешает новому enrollment.

## Что проверено, а что ещё нельзя утверждать

Live 2026-11-06: OIDC-only, JWT propagation, genuine admin JWT source, MFA enrollment
`configure`; application and account admission согласованы; server DNS исключает
All. Реальный public OAuth redirect подтвердил отсутствие `groups` scope, поэтому
создан и прочитан обратно dedicated `profile` mapping. Повторный reconcile — no-op.

Отдельный временный обычный Authentik user без пароля: grant, readback, no-op,
revoke, no-op и удаление прошли без superuser/app grants, MFA bypass или изменений
реальных пользователей. Это **не** притворяется личным OIDC/MFA входом нового человека
и полноценным enrollment нового устройства. Первому реальному админу нужно пройти
пункты 5–8; credentials/сессия владельца не являются такой приёмкой.

Текущий Mac: реальные SSH с выключенным standalone WireGuard проходят через
NetBird ко всем четырём узлам. Резервный WG `.4` проверен отдельно при выключенном
NetBird, после чего снова выключен и восстановлен основной NetBird. Tunnelblick
оставался на том же OpenVPN процессе и интернет-маршрутах.

## Cleanup и сохранённые зависимости

- Локальный SSH: один однозначный блок на узел, no ProxyJump/public fallback,
  существующие pinned host keys. Отдельный явный `socrat-2-recovery`/`-direct` —
  break-glass, не часть обычного маршрута.
- Default Ansible inventory теперь внутренний, port 2222, pinned legacy host-key
  aliases; `direct.yml`/`lan.yml` остаются явными recovery overlays.
- Временный assistant WG `.6` удалён из registry и persistent/runtime peers
  всех четырёх узлов; owned firewall перечитан без рестарта mesh-интерфейсов.
- Резерв владельца — **одна** identity/profile `.4` `wg-socrat-admin`, отключён.
  Его key/config — одна credential, не несколько разных ключей.
- Phone/TV identities не считались ненужными по отсутствию свежего трафика.
  Историческая отметка об exposed phone key требует отдельного подтверждения
  владельца/ротации; не выдавать её за выполненную или безопасно забытую.
- Старый local bootstrap NetBird admin заблокирован и понижен до user; настоящий
  owner и bound automation service сохранены. Чужие PAT API не разрешил читать:
  обхода/удаления токенов не было, не заявлять обратное.
- Исторические activation/owner-transfer scripts и migration evidence — не
  reconcile API. Не replay. Они оставлены для provenance и зависимых тестов;
  текущая процедура использует `netbird-access.yml`.
- Старые SSH rollback-файлы и дубликаты WG-конфига перемещены из рабочих папок
  в private `~/Backups/homelab-access-cleanup-20261106/`, не уничтожены.
  Полные emergency backups сервера и node/DB identities не затронуты.
- Старые macOS resolver overrides — отдельный root-owned owner. Не удалять их
  и не flush DNS во время обязательного Tunnelblick-сеанса. Они не требуются
  новому чистому клиенту; ревизия/снятие на этом Mac — отдельное безопасное окно.

Control-plane/Auth singleton и провал cold start без management описаны в
`netbird-independent-access.md`; новые пользователи не устраняют эти пределы HA.

### Verification record

Focused offline regression run: **179 passed, 4 skipped, 135 subtests passed**;
Ansible syntax check and live `--check` audit passed with **changed=0 / operations=0**.
Checks cover additive admission, real-scope mapping, bound mandatory MFA, rejection
of All-device policies, user/peer approval semantics, exact UUID/connector pinning,
owner/service protection, scoped offboarding and partial-write stop behavior.
This is not a full repository-suite or new-human-MFA acceptance claim.

One inactive `socrat-assistant` service entry can still be visible in the Mac
WireGuard GUI. Automated UI access was unavailable; its `.6` credentials are
revoked on all nodes and cannot be used. Do not delete the tested `.4` recovery
profile to make the list look shorter. Removal of that obsolete GUI entry is a
cosmetic remaining action, not a second working recovery identity.
