# Authentik → публичные SSH-ключи: только reviewed Ansible assignments

## Статус и границы

**Основной выбранный сценарий теперь проще:**
[ручной Ansible: username + публичный ключ](ssh-user.md), без Authentik/n8n.
Этот документ описывает оставленную выключенной опциональную интеграцию,
не обязательный этап добавления SSH-пользователя.

Интеграция **опциональна и сейчас выключена**: `deploy/identity/ssh-bindings.json`
и `ssh-assignments.json` содержат пустые списки. Существующий `users.yml`, роль
`users`, owner/root/automation accounts и оба текущих публичных ключа Tim в
`ansible/inventory/group_vars/Socrat.yml` не изменены. Никакого live rollout нет.

Authentik хранит **только источник публичных ключей**, не Linux authorization.
`username`, email, группы, `attributes.hosts`, `attributes.sudo` и похожие поля
не дают доступ и не выбирают Linux account. Добавление ключа в IdP само по себе
ничего не меняет на hosts: каждый новый exact key set требует plan → review →
export → отдельный guarded Ansible apply. Это не SSH SSO и не SSH CA.
Приватные ключи остаются на устройствах людей; пароль Linux не создаётся.
App IAM `configure.py`, VPN/NetBird и topology этой интеграцией не управляются.

Источники:

- `scripts/identity-ssh-plan.py`: stdlib Python + системный `ssh-keygen`, только
  HTTPS GET; по умолчанию выводит read-only план без raw public keys/attributes.
- `deploy/identity/ssh-bindings.json`: append-only UUID → Linux username ledger.
- `deploy/identity/ssh-assignments.json`: reviewed state, active и revoked hosts.
- `ansible/playbooks/authentik-ssh-users.yml`: по умолчанию **только intent check**;
  реальный apply использует существующую restricted `users` role и её verifier.
- `ansible/files/verify_authentik_ssh_binding.py`: read-only root preflight,
  запрещающий автоматическое присоединение существующего локального аккаунта.

## Неизменяемая личность и явный scope

Нужен **raw immutable `uuid` из Authentik User API**, не integer `pk`, не `uid`,
не email и не кастомный UUID attribute. API без поля `uuid` или без работающего
UUID filter намеренно отклоняется; не добавлять fallback по имени. Проверить
поддержку установленной версии до enrollment. Ответ должен содержать ровно одну
точную UUID-запись и `pagination.next: null`; неполная/неоднозначная выборка — ошибка.
Активный источник должен иметь `is_active: true`, `type: internal` (human user).
Сервисные пользователи исключены; `root`, `alchemmist`, `ghactions` запрещены
как управляемые Linux usernames. Привилегированные accounts — отдельная процедура.

После независимой проверки личности добавить **новую**, а не заменить старую
binding-запись. Пример схемы (UUID ниже вымышленный, не enrollment Tim):

```json
{
  "version": 1,
  "bindings": [
    {"uuid": "11111111-2222-4333-8444-555555555555", "name": "guest"}
  ]
}
```

Assignments для этой binding:

```json
{
  "version": 1,
  "public_key_attribute": "ssh_public_keys",
  "assignments": [
    {
      "uuid": "11111111-2222-4333-8444-555555555555",
      "state": "present",
      "hosts": ["socrat-1"],
      "revoked_hosts": []
    }
  ]
}
```

`hosts` и `revoked_hosts` обязательны, не пересекаются; active assignment требует
непустой `hosts`. Нет семантики «отсутствует hosts → все машины». Bindings не
выдаются автоматически: UUID без assignment не имеет SSH scope.
Дополнительные поля вроде `sudo`, `groups` или shell в policy отклоняются:
эта интеграция выдаёт только bash/no-sudo, без supplementary groups.

Проверяется **вся доступная Git history HEAD** обоих фиксированных файлов.
UUID/name нельзя удалить или переиспользовать; старые host scopes должны остаться
в active/revoked tombstones, даже после применения revoke. Shallow checkout
отклоняется. Использовать полный доверенный checkout и обычный review; Git history
не является защитой от администратора, переписывающего историю/сам код. Не менять
ledger при восстановлении IdP из backup: новый UUID означает другую личность,
а не автоматическое слияние с прежней. Смена Linux username — отдельная миграция,
не правка binding. Исторический username не освобождается для другой identity.

Для `ssh_public_keys` поддерживается **JSON list отдельных OpenSSH public-key
строк**, не строка с переносами. Отсутствующий/пустой/некорректный список у
active assignment блокирует весь export. Каждый ключ проверяет настоящий
`ssh-keygen -l -E sha256`; regex недостаточно. Поддержан тот же набор типов,
что у users role: ed25519, RSA, nistp256, OpenSSH security-key варианты.
Private material, certificates, authorized_keys options, control characters,
multiline и дубликаты запрещены. Comments отбрасываются. План показывает SHA256
fingerprints; export содержит только canonical public keys и reviewed metadata.
Ни shell interpolation ключей, ни remote shell из IdP attributes нет.

## Plan, export и проверка — без live writes

Необходимы доверенный HTTPS origin Authentik, CA trust, отдельный read-only token
с минимальным разрешением чтения нужных users/attributes, подтверждённые UUID,
точные inventory aliases и проверенные fingerprints. Bootstrap/admin token не
нужен. Не получать token через распечатку Kubernetes Secret и не коммитить его.
Пример **bash**, token вводится без echo и не попадает в аргументы процесса:

```sh
read -r -s -p 'Authentik read-only token: ' AUTHENTIK_SSH_TOKEN; printf '\n'
export AUTHENTIK_SSH_TOKEN
python3 scripts/identity-ssh-plan.py --authentik-url https://sso.example.invalid
# Для собственного CA дополнительно: --ca-file /secure/trusted-ca.pem
```

Нет `--insecure`: hostname/chain verification включены; redirects запрещены,
включая redirect на другой HTTPS host. Script не пишет в Authentik, не запускает
Ansible/SSH и не сохраняет исходные API responses. При error не печатает ответ
сервера, token, raw attributes или некорректный ввод. Не включать shell tracing,
HTTP debug logging или запись environment в сторонний CI artifact.

Проверить каждого человека, все active/revoked hosts, fingerprint и `review_sha256`.
Потом новый GET и **явно подтверждённый export** в новый файл вне repository:

```sh
python3 scripts/identity-ssh-plan.py --authentik-url https://sso.example.invalid \
  --export /tmp/reviewed-ssh-users.json --approve-plan REVIEWED_SHA256
unset AUTHENTIK_SSH_TOKEN
```

Если ключ/policy/binding изменились, digest будет другим, export откажет.
Файл создаётся `O_EXCL`, mode 0600, без overwrite. Пустая интеграция не экспортируется.
Сохранять public export в Git не нужно. Для полностью offline tests разрешён
`--snapshot /secure/public-users.json` (список API user records), но **только plan**,
никогда export. Не сохранять в snapshot passwords/tokens/прочие IdP attributes.

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml \
  playbooks/authentik-ssh-users.yml -e @/tmp/reviewed-ssh-users.json --check
# Без --check поведение тоже read-only, пока нет explicit apply flags.
```

Это **локальная проверка intent, digest, aliases, полного scope и конфликтов с
manual inventory**, не симуляция создания user и не проверка текущего host state.
Она не устанавливает remote connections. Не подменять её утверждением, что
удалённый SSH login уже работает. `--limit`, исключающий хотя бы один required
active/revoked host, запрещён. Unknown inventory host тоже блокирует play.
Export нельзя редактировать после review: Ansible пересчитывает digest payload.

## Отдельный, явно разрешённый apply

Только после review и свежего export (ниже инструкция будущего deployment,
не выполненное действие):

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml \
  playbooks/authentik-ssh-users.yml -e @/tmp/reviewed-ssh-users.json \
  -e homelab_authentik_ssh_apply=true \
  -e homelab_authentik_ssh_approval=REVIEWED_SHA256 --ask-become-pass
```

Нужны **оба** apply/approval flags; `--check` всё равно остаётся read-only.
Перед account/key изменениями root preflight на всех целевых hosts проверяет binding:

- existing Linux account без root enrollment marker → остановка, не auto merge;
- marker с другим UUID/name, symlink или небезопасными permissions → остановка;
- для нового account сначала резервируется `/var/lib/homelab-authentik-ssh-bindings/<name>.json`
  (`root:root`, directory 0700/file 0600), затем вызывается users role;
- marker не перезаписывается, остаётся после disable; частичный apply можно
  повторить с той же binding. Ничего не удалять ради обхода mismatch;
- даже с правильным marker passwd home обязан быть `/home/<name>`. Symlink в
  `/home`, home, `.ssh` или `authorized_keys` запрещён. Нестандартный home не
  мигрируется и старые effective keys не оставляются за пределами managed path;
- проверяется настоящий `sshd -T`: **единственный** AuthorizedKeysFile должен быть
  `.ssh/authorized_keys`, `%h/.ssh/authorized_keys` или точный `/home/<name>/.ssh/authorized_keys`;
  второй файл (включая default `authorized_keys2`), AuthorizedKeysCommand и
  TrustedUserCAKeys запрещены. Требуется pubkey=yes, password/kbd-interactive/
  hostbased/GSSAPI/Kerberos=no. Отсутствие требуемых effective полей — отказ;
- все `Match` directives, в том числе через recursive `Include`, сейчас **unsupported**:
  один `sshd -T -C` не доказывает отсутствие alternate key source для других клиентов.
  Preflight ничего не переписывает в sshd и не меняет auth policy owner/Tim. Если
  действующий sshd запущен с другим `-f`/CLI overrides, STOP: этот режим не поддержан,
  перед пилотом подтвердить стандартный `/etc/ssh/sshd_config` и отсутствие overrides.

Весь host apply (preflight → marker reservation → users role → exact-key postflight)
сериализован exclusive `mkdir /run/homelab-authentik-ssh-apply.lock` от root.
Второй writer **отказывает**, не ждёт и не переиспользует чужой lock; marker/name/UUID
проверяется уже под lock. `always` удаляет только lock успешно начатого apply.
Crash/unreachable host или ошибка другого host может оставить stale lock: сначала
проверить отсутствие работающего apply, marker/account/effective keys и только потом
отдельно согласовать удаление lock. Не автоматизировать lock stealing/TTL.
Manual user-management/adoption вне этого playbook тоже требует операционной
сериализации; lock не защищает от произвольного другого root writer.

`any_errors_fatal` останавливает остальные hosts при preflight error; Ansible не
транзакционен: поздняя ошибка может оставить частичный результат. Исправить
причину, повторить свежий plan/apply и проверить **каждый** host. Не заявлять
об успешном revoke по одному успешно обработанному узлу.

Автоматическая миграция существующих accounts **не реализована**. Для неё нужны
отдельно согласованные доказательства владения, exact keys и local account
review; лишь затем администратор может отдельно зарезервировать проверенный
root marker и перенести account из manual inventory. Не создавать marker из
совпадения email/username. Пока Tim остаётся в manual `homelab_users`, импорт
того же Linux name запрещён. Не удалять его manual запись и не менять оба ключа
ради тестирования интеграции.

Apply управляет **только импортированными accounts**, не пересобирает manual users.
Используется существующая `users` role: exact authorized_keys replacement,
password_lock, отсутствие sudo/root-equivalent groups, private .ssh permissions,
удаление legacy direct sudoers grant и effective SSH/PAM/sudo/kubeconfig verifier.
Единственное scoped расширение role — explicit `/home/<name>` при создании
импортированного account; default/manual users сохраняют прежний OS home behavior.
После role отдельный scoped verifier повторяет binding/home/sshd checks, разбирает
**каждую** effective key строку настоящим `ssh-keygen`, требует exact fingerprints
из reviewed export (без лишних/duplicate/invalid keys). Для disabled требуется
**ноль effective keys** и nologin; одного nologin недостаточно для отзыва forwarding.
Эти проверки не добавлены к manual Tim/owner path. Отдельно проверить permissions,
effective forwarding policy и войти с собственного устройства. Verifier не доказывает наличие
private key у человека. Без реального apply/login acceptance этого не обещать.

## Отзыв и removed-host workflow

1. Для удаления ключа удалить **только этот public key** из IdP attribute,
   получить новый план, independently проверить оставшиеся fingerprints,
   экспортировать и применить exact set. Удаление attribute/последнего ключа
   **не означает успешный revoke**: active plan откажет. Для полного отзыва
   требуется explicit `state: disabled`.
2. Для отзыва **одного host** переместить alias из `hosts` в `revoked_hosts`.
   На остальных hosts оставить `state: present`. Removed host получает explicit
   disabled record, не исчезает из scope. Если убирается последний active host,
   поставить `state: disabled`, можно оставить `hosts: []` и все aliases в revoked.
3. Для полного отзыва оставить прежние hosts/tombstones, поставить `state: disabled`.
   Disabled records не требуют доступного IdP или ключей: можно отозвать доступ
   даже после удаления IdP user/при отказе IdP. UUID binding всё равно обязательна.
4. Применить **ко всем** required hosts. Disabled означает сохранённые account/home,
   nologin shell, пустой authorized_keys и отсутствие managed privileges.
   Проверить каждый host/effective verifier. Оставить ledger и host tombstones
   в Git и host markers на месте. Простое удаление assignment/host блокируется
   проверкой history, а не считается revoke.
5. При недоступной/выведенной из эксплуатации машине нельзя объявлять доступ
   отозванным. Нужна отдельная проверяемая decommission/isolation процедура;
   не удалять tombstone для получения зелёного результата.

**Уже установленные SSH sessions, port forwards и процессы этим не гарантированно
завершаются.** Отдельно согласовать inspection/termination active sessions/jobs,
проверить другие SSH key providers/sshd overrides и доступные пользователю
credentials. Не удалять home и не запускать глобальный destructive account cleanup.
Возврат доступа — новое reviewed решение, не rollback старого export с отозванными
ключами. Изменение IdP groups или отключение IdP account само по себе hosts не
меняет; inactive active-assignment блокирует план с требованием explicit disable.

## Offline acceptance

```sh
/tmp/homelab-iam-tests/bin/python -m unittest discover -s tests -p 'test_identity_ssh.py' -v
/tmp/homelab-iam-tests/bin/python -m unittest discover -s tests -p 'test_identity.py' -v
cd ansible
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml \
  playbooks/authentik-ssh-users.yml --syntax-check
```

Тесты используют fake HTTPS, настоящий parser публичных ключей, временный local
inventory и **только default/--check Ansible**, без remote writes, реальных tokens
или private key fixtures. SSH CA не реализуется.

**До production всё ещё нужны disposable Linux real-apply acceptance**, не на Tim/owner:
creation → login; rotation (old key denied/new key allowed); disabled и removed-host
(old keys denied, включая `ssh -N`/new forwards); корректный marker и отказ при
другом UUID/unbound account; nonstandard home/alternate key file/Match отказ **до**
account/key writes; competing writers и crash/stale-lock recovery. Также проверить
реально запущенный sshd command line, fresh login с разных client addresses,
уже установленные sessions/forwards, недоступный host и повтор partial apply.
Эти действия здесь не выполнялись. Без них нельзя объявлять revocation работающим.

### Ограниченный синтаксис OpenSSH Include

Импорт намеренно принимает только простые `Include` paths/globs из букв, цифр,
`_ . / - * ? [ ]`, без кавычек, escape-последовательностей, `#`, `~` и `%`.
Комментарии поддерживаются отдельными строками. Остальные формы могут быть
валидными для OpenSSH, но importer останавливается до изменения accounts/keys:
он не должен интерпретировать конфигурацию иначе, чем sshd. Любой `Match`
в основном или включённом файле остаётся блокирующим условием. Не упрощать
рабочую SSH-политику ради прохождения importer; использовать существующий
reviewed manual Ansible path либо отдельно расширять verifier с реальными
OpenSSH regression tests.

Регрессия использует настоящий `sshd -T` и `-T -C` с временным host key:
Include filename с буквальным `#` может скрыть `Match` от shell-парсера, но
теперь отвергается preflight. Это offline test, не приёмка SSH на нодах.
