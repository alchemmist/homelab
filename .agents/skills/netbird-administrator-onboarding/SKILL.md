---
name: netbird-administrator-onboarding
description: "Заведение/отзыв администраторов внутренней сети homelab через Authentik и NetBird; очистка legacy доступа, аудит groups/OIDC/DNS, сохранение Tunnelblick и одного WireGuard recovery. Использовать для новых людей и устройств, не путать с onboarding cluster nodes."
---

# Human administrator admission

1. Прочитать `docs/netbird-administrator-onboarding.md` целиком. Это канонический
   workflow, а не набор старых pilot activation scripts.
2. Не менять Tunnelblick, default route, corporate DNS, межсерверный WireGuard,
   Kubernetes RBAC, SSH users/keys или реальные identity UUID ради сетевого доступа.
3. Использовать `ansible/playbooks/netbird-access.yml`: audit по умолчанию;
   `reconcile`, `grant`, `revoke`, `offboard` — разные операции. Apply только с
   свежим approved plan hash. Никаких mutation retries после uncertain receipt.
4. Человек создаётся/подтверждается отдельно в Authentik, normal non-superuser.
   Grant добавляет **одну** группу `netbird-internal-admins` по точному username
   и независимо проверенному UUID. Не сопоставлять по email и не копировать owner.
5. NetBird embedded IdP 0.82 фактически не просит scope `groups`. Не «исправлять»
   только standard groups mapping: штатный dedicated profile mapping передаёт
   настоящие группы в обязательном scope `profile`, только для NetBird provider.
6. Server-side DNS management отключён через builtin All group для новых устройств.
   Доступ — только опубликованные внутренние `/32`, без exit/default/LAN-wide routes.
   Обычная установка клиента требует выбора self-hosted URL, личного SSO/MFA,
   **не** setup key, WireGuard profile, resolver file или персональной policy.
   `user_approval_required=false` при строго ограниченных JWT/application groups;
   peer approval выключен. Не включать публичную регистрацию вместо IdP admission.
7. Проверять actual device, route interface, group provenance, source policies и
   новые соединения с native authorization. Standalone WireGuard должен быть
   выключен при NetBird acceptance. Проверка existing owner не доказывает нового
   human enrollment. Не обходить MFA для демонстрации зелёного результата.
8. Для полного offboarding не ограничиваться group removal: cached JWT может жить.
   Offboard блокирует точный ordinary NetBird user, удаляет его peers, снимает
   группу; owners/services защищены. SSH/app/Kubernetes revocation отдельно.
9. Cleanup: удалить только доказанные temporary identities, оставить проверенный
   WG recovery `.4`; не удалять node keys, phone/TV или неизвестные ключи по age.
   Учитывать отдельно известный exposed phone key. Токены/пароли/recovery links,
   UUID/email, WG private material и сырые API bodies — только private artifacts.
10. Отчёт: что реально applied, no-op/readback, scoped positive/negative tests,
    ограничения новой MFA/device acceptance и оставшиеся dependency/recovery items.
    Не обещать полную HA: cold-client start зависит от management/IdP.

## Kubernetes policy prerequisite

Native host NetBird transport marks can be inherited across the VXLAN boundary
and collide with kube-router allow bits. Before claiming Kubernetes isolation,
audit `ansible/playbooks/k3s-overlay-marks.yml` on all nodes and require zero
operations. Follow `docs/k3s-networkpolicy-overlay-marks.md` after host NetBird,
overlay or node changes. A 403 from S3 is not a network-denial test; test fresh
unprivileged cross-node connections to Pod IP and ClusterIP, plus the allowed
reader. This is infrastructure maintenance, not a per-human client configuration.
