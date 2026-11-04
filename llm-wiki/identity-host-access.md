# Linux, SSH, kubeconfig и Kubernetes RBAC

Часть [общего справочника](identity.md). Authentik SSO не заменяет эти контуры и
не выдаёт SSH/root/kubectl автоматически. WireGuard/NetBird topology здесь не менять.
Сетевой вход и полный сценарий нового админа: [NetBird](netbird.md).

## 1. Источники

- `ansible/roles/users/tasks/main.yml`, `files/verify.py` — restricted personal users.
- `ansible/playbooks/ssh-user.yml`, роль `ssh_user` — ручной username + один public key,
  добавление без удаления остальных ключей: [короткая инструкция](ssh-user.md).
- `ansible/playbooks/users.yml` — точный декларативный key set из inventory.
- `ansible/playbooks/identity-hosts.yml` — защита owner kubeconfig + users playbook.
- Inventory/group/host vars `homelab_users` — реальные публичные ключи и assignments.
- `deploy/identity/access-policy.yaml` — intent ролей, не самостоятельный enforcement.
- [Опциональный Authentik public-key import](identity-ssh-keys.md) — отдельный
  read-only plan/export и guarded Ansible play; сейчас пустой/выключенный, без
  миграции Tim. Immutable UUID binding, explicit active/revoked hosts; не SSO/CA.
- `deploy/identity/observer-role.yaml`, `identity-rbac.yml` — unbound observer definition.
- K3s install/HA config templates также сохраняют kubeconfig mode/group.

Owner/root/automation identity не управляются restricted-user path. Роль запрещает
`root`, `alchemmist`, `ghactions`; их изменение — отдельная привилегированная процедура.

## 2. Что делает users role

Перед изменениями валидирует username, state, отсутствие sudo intent/опасных
supplementary groups и формат всех public keys. Допускаются reviewed OpenSSH
ключи (ed25519/RSA/поддержанные ECDSA/security-key варианты), не private key.
Usernames уникальны. `authorized_keys` должен быть списком, не одной строкой.

Для assigned пользователя:

- создаёт/сохраняет home, account и shell;
- блокирует password authentication (`password_lock`);
- задаёт **точный** supplementary group set (`append: false`);
- `.ssh` 0700, `authorized_keys` 0600, владельцем остаётся пользователь;
- **заменяет**, а не дописывает key set: удалённый из списка ключ действительно исчезает;
- удаляет legacy прямой `/etc/sudoers.d/<name>` grant;
- запускает privileged verifier SSH/PAM/sudo/kubeconfig isolation.

Роль не выдаёт sudo и отвергает root-equivalent groups: sudo/wheel/admin/docker/
disk/lxd/incus/kvm/libvirt. Но чужие sudoers rules не угадывает: effective verifier
нужен именно потому, что привилегия может прийти не из одного файла/группы.

## 3. Как добавить Linux-доступ

**Обычный ручной сценарий:** [username + `.pub` → `ssh-user.yml`](ssh-user.md).
Authentik и workflow не нужны. Этот отдельный play добавляет один ключ, проверяет
каждую выбранную ноду и не удаляет другие ключи. Дальше описан другой,
декларативный путь через `homelab_users` с **полной заменой** key set.
Не путать семантику двух playbooks. Если account уже в inventory, новый public
key сначала должен быть одобрен и добавлен туда — ручной play это проверяет.

Сначала отдельно согласовать **какие hosts**, зачем shell, срок и конкретные
public keys. Личность/ключ fingerprint подтвердить через независимый канал.
Наличие пользователя в Authentik не является таким согласованием.

В существующем inventory source добавить `homelab_users` запись по действующей
схеме. Обязательные решения: `name`, explicit `hosts`, список `authorized_keys`,
`state: present`, без sudo/privileged groups. Public key брать от самого человека;
не генерировать за него private key и не просить прислать private material.

**Если `hosts` не указан, роль применяет пользователя ко всем hosts соответствующего
play.** Не оставлять поле случайно пустым при желаемом доступе только к одной ноде.
Проверить merged group_vars/host_vars и inventory aliases до apply.

Проверить syntax, diff, затем применить по согласованным хостам с безопасным sudo
вводом. Пример существующего полного hardening play, не универсальная выдача всем:

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml \
  playbooks/identity-hosts.yml --ask-become-pass
```

Для одной ноды использовать reviewed `--limit` / правильный users playbook и
inventory, понимая, что `identity-hosts` первый play целится только в socrat-0.
Не сохранять become password в source. На socrat-3 используется проверенный sudo
method; не подменять его прежним неработавшим privileged path.

После apply: владелец проверяет фактические key fingerprints/effective policy,
а сам человек делает реальный SSH login с собственного устройства. Проверка
authorized_keys владельцем не доказывает, что у человека есть правильный private key.
У Tim intended keys/PAM/public-key/sudo isolation проверены на четырёх нодах,
но его собственный сетевой private-key acceptance остаётся отдельным шагом.

## 4. Отзыв SSH

`state: disabled` сохраняет account/home, ставит nologin и очищает authorized_keys.
Это предпочтительнее несанкционированного удаления пользовательских данных.
Существующие процессы/SSH sessions этим не гарантированно завершаются: отдельно
разобрать active connections/jobs и approved termination/credential rotation.

**Удаление пользователя из vars или удаление host из `hosts` само по себе не
чистит аккаунт на прежней машине.** Роль управляет только текущими assignments,
специально не удаляя другие accounts. Для revoke сначала явно применить disabled
состояние на прежней ноде (reviewed per-host override/отдельный проход), проверить
очистку ключей/privileges, потом убрать assignment. Не делать глобальный destructive cleanup.

`password_lock` — не эквивалент безопасного SSH policy на любой OS. Учитывать
sshd `PubkeyAuthentication`, PAM, Account checks и shell; verifier различает это.
Arch tooling может выдавать OSC/JSON noise, поэтому использовать reviewed parser,
а не произвольный grep/первую строку terminal output.

## 5. Инцидент с admin kubeconfig

На socrat-0 `/etc/rancher/k3s/k3s.yaml` был **0644**. Исправлено немедленно на
**0640 root:alchemmist**; K3s config сохраняет `write-kubeconfig-mode: "0640"` и
`write-kubeconfig-group: alchemmist`. Install/HA templates исправлены тоже, чтобы
новая установка не вернула world-readable credential.

Перед сменой group play проверяет primary + supplementary membership: только
owner, без unexpected users. Затем проверяет, что Tim не может читать файл, а
owner всё ещё получает `yes` на `kubectl auth can-i '*' '*' --all-namespaces`.
Admin kubeconfig не превращается в read-only от выдачи его observer: это полномочие
cluster-admin, а не обычная настройка подключения.

**Chmod не отзывает скопированный certificate/key.** Историческая экспозиция и
поддерживаемая credential/CA rotation — отдельная задача. Не заявлять, что утечки
точно не было, если такой forensic/audit не выполнялся; не перезапускать весь K3s
и не менять CA как побочное действие CSS/SSO rollout.

## 6. Почему sudo exit code недостаточен

`sudo -l -U tim` может завершиться rc0 и одновременно написать, что Tim не
разрешено запускать sudo. Verifier использует C locale и разбирает реальный
policy result, не считает один exit code доказательством grant или denial.
При error/неразобранном результате требуется review, не предположение о безопасности.

## 7. Kubernetes/Rancher права

`homelab-project-observer` разрешает get/list/watch pods/services/endpoints/PVC/
events, deployments/replicasets/statefulsets/daemonsets, jobs/cronjobs,
ingresses/networkpolicies. **Нет Secrets, pods/exec, pods/log и nodes**.
Сама definition установлена, human bindings не создавались.

Чтобы дать доступ к одному namespace, отдельно определить реальный authentication
subject/principal и namespace `RoleBinding` на reviewed role. Не создавать
`ClusterRoleBinding` там, где достаточно namespace. Проверить `kubectl auth can-i`
на разрешённые и запрещённые resources под соответствующей identity; не выдавать
чужому человеку owner kubeconfig ради такого теста.

Для Rancher дополнительно смотреть exact OIDC principal и реальные project/
cluster grants: его existing users/principal IDs не те же строки, что IdP groups.
Auth configs/subject mappings не исправляют широкие старые RBAC bindings сами.

Root ноды способен читать/менять node workloads и secrets. Pod creator/exec в
namespace потенциально также получает namespace secrets. Ограниченный app role
не снимает эти host/workload trust boundaries. Нельзя обещать владельцу внешнего
root-хоста «нет доступа к данным», пока там исполняются доверенные workloads.
