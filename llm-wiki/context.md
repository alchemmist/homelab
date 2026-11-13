# Socrat: текущий контекст

## Unplanned fallback repair investigation —13Nov2026, NEWEST / PENDING SUDO

Concrete Moscow defect: HOME advertised API addresses192.168.0.23/.24 currently
route to eth0 default and actual TCP6443 times out. WG APIs10.250.0.1/.3 succeed
~18–25ms.4hostvars lacked the extra /32 AllowedIPs already used by workers3/5;
our worker-return preflight missed it. This explains agent API timeouts but does
NOT prove every TLS failure/NL transport interruption. Before fallback, HOME0
could not reach NL2380 and NL lost API/leader access;0/1 continued commits/quorum.
Source prepared: exactly2API /32 additions (boot+live helper without restart/key
changes), watcher direct-upstream attribution before stopping still-listening local
worker, sanitized per-stage failure diagnostics, no stale-green health in boot
grace. New scoped moscow-watchdog-repair.yml: defaultpreflight, confirmedapply,
separateconfirmedreturn via existing failback/native rollback; no Node deletion or
NL stop.148tests+2subtests, syntax passed. NOT APPLIED: sudo -n unavailable;
previous password file deleted/value absent in current context. Await private
Ansible vars-file PATH, not chat password. Current4OS/check1/NotReady,2K3S/check1;
other5Ready. Do not report resolved or bypass current fences/credentials.
[Evidence and gate](../docs/moscow-unplanned-fallback-20261113.md).


## Fixed Moscow chain + native readiness —13November2026, CURRENT

Owner ABANDONED HOME/direct-NL/node5 user fallback. Only clients→Moscow4→NL;
K3S primary, systemd fallback. Keep4 a worker; never retire/delete it for CPU.
Audit found stale NL native image6c7… vs live/source1628…; staged cached image,
passed isolated copied-DB/cert namespace smoke, cleanup verified, atomically
exchanged dormant root under watchdog lock, old image retained. No NL Pod/server
restart/live DB migration. Both boot fences/timers/native assets audited positive.
Native component observers installed2/4; existing exporter+sole OTel/mTLS path.
Mode9 now composite: K3S green both checks; OS amber any native; K3S amber partial
check failure; OFF only positive no-data-sockets evidence; NO DATA missing/stale/
conflicting evidence. Explore details; layout/auth/alert thresholds unchanged.
Moscow observer uses watchdog cached health+real timestamp, no extra TLS per tick.
IMPORTANT UNPLANNED EVENT08:37UTC: existing4watchdog reached4failed path checks,
stopped/fenced its agent, activated native. NOT an operator outage test. Cause
unknown; do not blame/exonerate changes or infer Kubernetes failure from TLS loss.
NL briefly NotReady then recovered without restart. Final:4present/NotReady while
fenced,5others Ready;4native/check1 and2K3S/check1; actual Mode9=1/OS. DO NOT blindly
failback to paint green; explicit return and authenticated tests need short window.
Source through8c9ee2ae;77tests+2subtests before final doc. Escalation/private fetched
config removed. [English evidence/limits](../docs/vpn-runtime-readiness-20261113.md).
Older6Ready/K3S claims below precede this automatic transition. HOME investigation
below is historical/abandoned, not authorization to add5 to user traffic.


## VPN HOME fallback investigation —13November2026: NOT YET DEPLOYED

IMPORTANT CORRECTION: earlier direct NL443 claim was wrong: HOME OUTPUT DNAT
silently sent literal NL targets via Moscow. Corrected f1163873/45841353 with
probe-only UID19091 exemption on0, exact CAS+boot receipts; ordinary traffic
unchanged. Exporter uses new direct-home-wan-v2 provenance. Actual direct probes:
NL443=0/timeouts, HOME443=1, Moscow443=1. Do NOT claim NL reachable directly from
HOME or infer all-Russia/global blocking. Existing Moscow authenticated proof valid.
Bounded direct UDP51843 diagnostic also negative; no matching datagram/response.
Files/responder cleaned; existing mesh/ports/control-plane untouched,6Ready/relay1.
HOME0→5→NL strictly pinned SSH works without Moscow, candidate native transport
but NOT user-data reserve; private443 from5 refused (ACL review needed). HOME raw
VPN public ports not yet established; router mappings require verification.
Mode9 missing/stale now NO DATA not OFF (db1263e6), positive native latch OS.
Still NL-only mode signal: composite two-axis mode/automatic HOME switching and
return NOT implemented. Need topology decision before adding5 to user path.
Temporary escalation file removed. [English evidence and gates](../docs/vpn-home-fallback-20261113.md).


## Moscow WORKER RESTORED —13November2026, owner requirement

Owner rejects permanent removal as optimization: socrat-4 MUST remain worker.
All6nodes Ready; agent active/enabled; VPN Pod1/1, native relay inactive/fence
absent, controller kubernetes/healthy. Source30091cb7; TV4 Kubernetes Ready
restored467c7e95; mode9 and4actual queries0green; both Argo apps Synced/Healthy.
Five authenticated HOME protocols passed65536B/checksum/NLexit; owned fixture/
tokens cleaned, original config preserved, escalation file deleted. Retain
bootstrap admission taint/GOMAXPROCS1/native fallback. CPU pressure NOT solved;
no alert weakening. More CPU/RAM acceptable; do NOT retire this worker again.
Separate ingress failover via HOME0 still NOT implemented. Physical TV visual
acceptance not claimed. [English acceptance](../docs/moscow-worker-return-20261113.md).
Older native-primary and native cube4 entries below are historical/superseded.


## Historical: initial IP probe fix13Nov, direct-NL inference WITHDRAWN above

Panel926 now uses native host up/memory/root-space metrics, not removed Kubernetes
Ready4. IP cubes905/906/928 use distinct public-ip-probes, stock hostNetwork
exporter on HOME0, LAN source192.168.0.23, literal public TCP443. Verified direct
physical route via192.168.0.1/eno1; no VPN/service-alert coupling. Existing TV OTel
sidecar owns these3jobs with unchanged mTLS. Argo Synced/Healthy bb5b1e05; all
three fresh direct probes1 and actual four panel expressions0/green. Native
Grafana API model matches, all63panel geometries retained;56tests+promtool/lint.
Public NL TCP443 works directly from HOME0/1; ICMP and public2222 do not answer,
not proof of whole-IP or all-Russia blocking. TV ADB has no connected device;
physical page needs refresh, no visual acceptance claimed. See
[contract/evidence](../docs/traffic-light-direct-ip-20261113.md).


## Historical, superseded13Nov: Moscow native-primary —12November2026

Accepted migration: Kubernetes now has5Ready nodes0/1/2/3/5; Moscow4 remains a
managed network host, not a worker. Same pinned Xray/config, native-primary mode,
worker boot disabled, persistent fence retained, relay desired replicas0 in GitOps.
Five authenticated HOME protocols passed before/after handoff; temporary fixture/
tokens removed, originals preserved. All30directed inter-host ICMP/SSH paths
passed. Native DNS/management/telemetry continue; no WG/control-plane restart,
network flush or uninstall. Rollback data retained. Available RAM~544MiB versus
~350MiB earlier; CPU PSI~42% and SocratNodeResourceContention STILL firing at
WG RX4.56MB/s. No alert weakening. Public NL UDP53 timed out from Mac at closeout.
Source published through db14a58e. [Acceptance, architecture and rollback](../docs/moscow-native-primary-20261112.md).
Earlier6Ready/Pod-primary notes below are historical, not the current target.


## TV / Traffic Light — принято 11 ноября 2026

Owner-approved адресный CSS только для native Argo909 на public TV opt-in:
padding3CSSpx, gap2CSSpx, flex redistribution. Ручныеw12/h1 сохранены,49 блоков
подтверждены реальным screenshot и WebView-замерами. Обычный ноутбук/другие панели/
Fully55%/font75% не менялись; не возвращать прежнее растягиваниеw24/h2. MoscowIP928
добавлен справа и работает по свежему TCP443 probe91.189.82.238. Код, scoped Helm,
приёмка и границы: [TV-CSS и сопровождение](android-tv.md#сопровождение-кастомного-tv-css-для-argo).
Это исключение из старого «без CSS» только для одной панели, не глобальное разрешение.

## SSH management policy — owner override 2026-11-10

Ordinary Mac aliases 0/1/2/4 now use public SSH directly (HOME WAN forwarded
2222/2223, NL .60:2222, Moscow :2222). Private workers3/5 use direct NetBird, ProxyJump none.
All six real SSH logins accepted; strict pins retained, no Mac route/DNS/VPN
changes. Do not restore the older internal-only alias policy.
[Current table](../docs/mac-private-ssh.md).

## socrat-5 workload migration — 2026-11-11

Owner authorized PR Agent, Rancher replica and n8n migration, plus daily compressed
versioned n8n backups to socrat-3. PR Agent and n8n moved to5 without NFS. n8n
copied offline to new static Retain node5-local PV/PVC `automation/n8n-socrat5`;
legacy claim remains on1 for rollback. Storage admission gained only this named
verified-local claim exception; foreign PVC/inline NFS negative probes denied.
Daily CronJob `automation/n8n-backup`,03:15 Europe/Moscow, uses SQLite online backup,
integrity check and pinned restricted SSH to `socrat-3:/home/alchemmist/backups/n8n`.
Two test versions (~19MiB) accepted; offline archive SHA/SQLite/counts/key presence
verified. No automatic archive deletion; private storage, not at-rest encryption.
n8n 7 workflows/10 credentials/1 user/5 active preserved; healthz ok. No production
workflow manually run. **Rancher attempt failed:** native jailer needs device nodes,
`mknod` denied inside unprivileged LXC. Startup budget extension did not fix it;
rolled desired placement/probes back to0/1, no jail/security/privilege bypass.
Socrat4 untouched. [Evidence, limits, restore](../docs/n8n/worker5-migration-20261111.md).

## socrat-5 full headless setup — IN PROGRESS

Owner authorized general worker, not VPN transit. Account/shell/verified bottom,
SSH2222+preserved22 and metadata welcome configured; direct WG to all five peers
accepted, temporary Moscow isolation retired. K3s agent joined,6Ready;5 has dedicated
no-NFS scheduling taint (bootstrap gate retired). LXC uses native usernamespace kubelet mode and node-local
legacy netfilter after actual DNS failure/EMSGSIZE; policies not disabled.
NetBird5 ready with key-free restart; direct ordinary SSH/no jumps and password
sudo accepted. Native OTel up1/uname and Loki329/10min counts accepted. Direct
peers0/1/2/3 remain reachable during scoped Moscow WG failure. Own fixtures cleaned.
**Owner-approved no-NFS profile now accepted:** bootstrap gate replaced with
`homelab.io/no-nfs=true:NoSchedule`, label nfs=false; explicit toleration required.
Native owned admission policy rejects remote/unclassified persistent volumes
for5, except verified local NetBird identity PVC and the explicitly migrated node5-local
n8n PVC (11 November; see above). No existing NFS PV/RBAC changes.
NetworkPolicy cause/fix: missing existing NetBird/VXLAN mark guard on new5;
installed role, now included in worker play and required/reapplied before every
agent start. Real deny/allow and same-/cross-node wrong-label tests passed without
network/K3s restart or policy weakening. Nonroot scheduler-selected Job with
emptyDir/DNS/HTTP passed. Owned fixtures removed,6Ready, NetBird Argo Healthy,
direct SSH accepted. Root UID map remains unprivileged; no VM needed for the
accepted restricted profile.30Mbit Proxmox cap, physical reboot/HA/NAT rebinding
remain unverified. Do not replay earlier failed enrollment or bootstrap admission.
[Current setup and remaining gates](../docs/socrat-5-worker-20261110.md).

## Исторический bootstrap socrat-5 — superseded by worker setup above

Владелец выдал NATed Debian13 LXC, исходное имя testing-class; WG create/delete
успешен, SSH22 root key-only. Новый согласованный идентификатор **socrat-5**,
mesh **10.250.0.41/32**, peer только Moscow.40. На Москве source-scoped pre-DNAT
изоляция+boot dependency и один persistent/runtime WG peer приняты без restart;
старые peers и VPN relay healthy сохранены. **Owner запустил WG: handshake/ping приняты; native SSH root по independently
pinned ED25519 принят, Ansible pipelining работает. Один negative TCP443 probe
из.41 к Moscow.40 получил timeout. Полная mesh/failure/isolation matrix и
K3s/LXC suitability НЕ приняты.**
[Runbook, source, fingerprint и pending gates](../docs/socrat-5-bootstrap-20261110.md).
Исторический bootstrap завершён и superseded:5 уже в Socrat/K3s. Не переигрывать one-time admission; для5 обычный scheduling требует no-NFS toleration и storage admission guard.

## Закрытие сессии: RF/NL split отложен владельцем

**10 ноября: владелец решил оставить рабочую схему, серверный split не внедрять.**
VPN-трафик по-прежнему Москва → NL → Интернет; существующий Happ bypass сохранён.
Read-only настройки панели: routing/onadd `Alchemmist VPN`, GlobalProxy=true,
49 DirectSites, DirectIp/ProxySites/ProxyIp пусты; активность на каждом телефоне не
проверялась. Это не серверный GeoIP split. Исследование — reference, **не pending
implementation и не разрешение переносить VPN termination на Москву**.
[Исследование и альтернативы](../docs/vpn-split-routing-research-20261110.md).

При закрытии сессии fresh read-only на Москве: именно `vpn-transit-655857b776-9mt9v`
SANDBOX_READY; watchdog kubernetes/healthy, data_path_healthy=true, failures=0,
agent_active=true, native_active=false, fallback_marker=false. Конфиг user.json
совпадает по содержимому с Git: tunnel TCP80/443/32053/32083/32084 и
UDP443/32085/32086 →10.250.0.2, freedom sendThrough10.250.0.40.
Это локальный статус/штатная TLS-проверка пути, **не новая полная проверка клиентов,
etcd/WAL/всего кластера или DR**. Никаких activate/failback/перезапусков не выполняли.

[Как устроен Pod, границы Xray/3x-ui и ownership](../docs/vpn-mesh-runtime-20261110.md#what-the-pod-actually-does).
Public wiki: [VPN](../wiki/content/network/vpn.md). Секреты и recovery receipts
остаются вне Git; подготовительные/migration apply не повторять.


## Текущий транспорт — 10 ноября 2026 (supersedes прежний отдельный WG)

Пользовательский relay Москвы теперь **Pod `vpn-transit` на socrat-4** под Argo;
при реальном отказе — независимый fenced systemd fallback. Оба используют тот же
Xray и конфиг. Общий `wg-socrat`:Москва10.250.0.40→NL10.250.0.2; отдельный
`wg-vpn-transit` остановлен/disabled на обеих нодах, ключи/конфиги архивированы.
Management51832UDP/51840TCP остаётся отдельным systemd-relay, независимо от Pod.
DNS:.40:53→.2:5354, старый dnsmasq.2:53 не трогали. Только machine.40 исключён из
старого private-web443 DNAT; human/admin ACL не расширены. Trojan допускает
только mesh.40/32 и точный health-loopback127.0.0.1/32.

Реальный timer автоматически восстановил native relay после остановки только
московского worker-agent и его relay-контейнера; затем штатный failback вернул Pod.
Все пять HOME профилей приняты в Pod/native/fallback и **после удаления отдельного
WG**;17 клиентов/91 bindings/подписки84URI/77JSON/ключи сохранены, fixture cleanup
подтверждён. Кластер:3 healthy voters/hashKV equal revision17514049,5Ready/noMemoryPressure.
134 tests+14 subtests, новые private archives2/4 off-host SHA verified.
Это не zero-downtime rollout: исправлены TIME_WAIT guard, management source IP и
Pod bind-capability; не скрывать ошибки/короткую недоступность, не приписывать
результаты native-fallback probe первому неудачному Pod. [Подробности и операции](../docs/vpn-mesh-runtime-20261110.md).
API loss при работающем relay не вызывает переключения; native sticky до явного
failback. Mobile/AWG/полный DR/reboot/HA не доказаны. Подписка/публичный вход прежние,
Mac/Tunnelblick/default routes не менялись. Подготовительные apply не переигрывать.


Актуализировано **10 ноября 2026**: production VPN Pod/native и общий mesh приняты; остальные
срезы сохраняют свои даты. Это не новая полная live-проверка кластера.
Начинать с [карты справочника](README.md). Старые датированные журналы — evidence
своего этапа, не задания повторить миграцию и не замена текущим manifests/live state.

## Сеть и вход

**NetBird — основной пользовательский доступ во внутреннюю сеть Socrat.**
Не предлагать людям ручной профиль «socrat-wg» как обычный onboarding.

| Слой | Текущий контракт |
| --- | --- |
| NetBird | Личный Authentik/MFA, отдельно согласованные JWT-группы/device policies |
| Маршруты администратора | Только четыре адреса нод `/32`, не весь LAN/pod/service CIDR и не exit node |
| Ноды 0 / 1 / 2 / 3 | `10.250.0.1` / `.3` / `.2` / `.5`; SSH `2222`, pinned host keys |
| Межнодовая сеть | Реальный интерфейс `wg-socrat` сохранён: NetBird human ingress его не заменял |
| Recovery | Независимый standalone WireGuard владельца, обычно выключен; не обычный путь входа |
| Рабочий VPN Mac | Обязательный Tunnelblick; не отключать и не менять DNS/routes ради homelab |
| Public HTTPS | HOME `109.173.40.247`, VPS `109.120.141.60`; обычный DNS/TLS без Mac overrides |

У NetBird на Mac DNS выключен, выбраны только четыре согласованных маршрута.
Setup keys для людей не используются. Автоматический user/device approval выключен,
но принадлежность устройства и реальные разрешения проверяются. Cold start без
management ранее не прошёл: не обещать HA и не удалять recovery WG.

SSH transport, публичный ключ/Linux account, sudo, Kubernetes RBAC и app role —
**независимые разрешения**. Публичные HTTPS-входы не означают публичный SSH.
Не удалять known_hosts, не добавлять public fallback/ProxyJump и не отключать TLS.
Ключи/пароли/QR/подписки/activation URLs не публиковать.

Процедуры: [сеть](network-access.md), [NetBird и onboarding](netbird.md),
[SSH без sudo](ssh-user.md), [Linux/RBAC](identity-host-access.md),
[публичный DNS](public-dns.md).

## Актуально: production VPN через Москву, 9 ноября 2026

**Клиенты/HOME → Москва91.189.82.238 → NL109.120.141.60**. URL подписки
`vpn.alchemmist.xyz` неизменен; обновлять существующую подписку, не аккаунт/ключи.
Все три DNS-writer публикуют статический VPN A Москвы без NL fail-open. Нативные
Hosts7/7 обновлены:17 identities/91 bindings сохранены,32063 disabled. Подписки всех
17 клиентов:84 URI/77 JSON, обычный DNS/валидный TLS, старого NL endpoint нет.
После восстановления проверены из HOME три VLESS/REALITY, Trojan и WG:200/65536B/
контрольный hash, отдельный HTTPS exit-check=NL. UDP32…8192B через реальный
зашифрованный межсерверный канал также проверен; это не authenticated AWG/mobile.

HOME0/3 management WG и HOME1 pinned-TLS/GOST идут через Москву; известные NL
DNS/HTTPS/VPN потоки на HOME0/1/3 перенаправляются scoped persistent nft DNAT.
Не глобальный exit node, Mac/default routes/DNS-настройки не менялись. Private
DNS:Москва10.250.0.40:53→NL10.251.4.2:53. NS1 HOME и NS2/glue NL сохранены.
NL WAN raw VPN закрыт; только Trojan HTTP-путь на shared443 допускает московский
private10.251.4.1/32 и точный loopback127.0.0.1/32 для штатной health-проверки.
Public403/private101, spoofedXFF не помогает; портал200/LMS303/Argo200 сохранены.
Такой же gate установлен/проверен в native Caddy fallback.

**Инцидент не скрывать:** первоначальный ACL пропустил local health и вызвал
watchdog fallback/остановку NL K3s. Исправлено loopback-исключением, проверки и
watchdog не отключены. Штатный failback исходного member без reset/replacement;
160MB Raft catch-up занял3m45s, bounded start timeout180→600s. После восстановления:
3 healthy voters/common leader/hashKV equal (revision17449598),5Ready/noMemoryPressure,
все пять транспортов и17 подписок повторно приняты, watchdog healthy/fallback off.
Московский socrat-4 — agent-only10.250.0.40, bootstrap NoSchedule сохранён,
не control-plane/etcd/обычный heavy worker. Четыре human admin routes не расширялись.

Бэкапы пяти нод плюс post-recovery supplement — private/off-host/SHA verified;
история/старые recovery receipts сохранены.126 tests+14 subtests passed — срез приёмки,
не непрерывный healthcheck. Mobile/Happ interactive, authenticated AWG, полный DR/
chaos/reboot и сохранение end-user IP enforcement не доказаны. Не обещать HA/TSPU immunity.
Подробности и custody: [production runbook](../docs/vpn-production-cutover-20261109.md).
Исторический staging: [Moscow bootstrap](../docs/moscow-vpn-transit-20261109.md).
Не переисполнять migration/prepare/apply: fresh preimage/CAS, uncertain→разбор.

## Исторический VPN-срез 8 ноября (superseded)



С 8 ноября — только конфигурация существующего socrat-2, **без покупки VPS/IP**.
Свежий аудит и приватный WAL-aware backup выполнены. Установлены только ACCEPT
backend-счётчики, не блокировки. REALITY32053 исправлен штатным API: Yahoo→Yahoo;
прошли fallback TLS1.3/H2 и synthetic64KiB до/после. Временные machine credentials
и fixture удалены, прежние токены/users/settings сохранены. Plaintext32063 и raw
backends ещё не закрыты; у всех7 plaintext-связей уже есть encrypted alternative,
но device/subscription acceptance не доказана. `x-ui -getApiToken` ротирует токен,
не извлекает его; не запускать ради чтения. Не выключать старые клиентские профили и не обещать обход IP/ASN-ban.
[Актуальный scope, исследования, инструменты и gates](vpn-hardening.md).

## Личности и авторизация

Начать с [текущего состояния identity](identity-current-state.md), затем
[операций](identity-operations.md) и [карты интеграций](identity-integrations.md).

- Owner — `alchemmist`, единственный человек в `homelab-owner`.
- Tim: **логин `antropophag`**, новая native Authentik identity после согласованного
  пересоздания; UUID закреплён в account mappings. Display name Tim и Linux `tim`
  — не логин IdP. На read-only проверке пароль ещё не задан, MFA/первого входа нет.
  Create user не запускает автоматическую установку пароля. Старый отдельный
  activation flow удалён, ссылка отозвана; SMTP invitation/recovery не настроены.
- Native OIDC: Grafana, Harbor, Rancher, Open WebUI, Wiki, LiteLLM, отдельно Argo CD.
  Admission через IdP не выдаёт native admin. Роли и exact subject links проверять
  по источникам, не по email или похожему имени.
- n8n/3x-ui, Kuma admin/Syncthing — только штатный логин сервиса; внешние Authentik proxy gates удалены.
  не универсальный account SSO. Umami для Tim **приостановлен** до native OIDC (#85).
- **Observer принят 8 ноября:** Rancher, Grafana, Wiki, Argo CD. Danila добавлен в
  `homelab-observer`, ошибочная `authentik Read-only` снята, согласованный NetBird
  сохранён; пароль/MFA и персональные native app/RBAC записи не создавались.
  Обычному следующему человеку достаточно IdP-группы и native SSO/JIT. Имеющиеся
  owner/editor/direct grants аддитивны, observer их не понижает.
- Отзыв проверен на synthetic identity: старые cookie/действующий Rancher bearer,
  Wiki MCP и новый вход без группы; автоматический native cache remove/re-add.
  Worker не создаёт users/roles; его доступность контролируют Prometheus alerts.
  Не обещать мгновенный logout всех OAuth/JWT. **Harbor для observer закрыт**:
  нативный CLI-кеш не прошёл отзыв, follow-up #134. Не возвращать Guest grants
  по старому readiness receipt. [Границы и evidence](native-observer.md).
- Machine APIs, robots, MCP, agents, webhooks сохраняют отдельные credentials;
  их нельзя переводить на browser MFA redirects.
- Grafana anonymous org access выключен. Исключение — только явно shared
  `socrat-traffic-light`. Wiki read public, запись — native OIDC/роль, MCP — bearer.

## SPI: полный сервис в отдельном репозитории — 9 ноября 2026

Канонический код **frontend + backend** теперь в
[`alchemmist/spi-triage`](https://github.com/alchemmist/spi-triage), не только UI.
Старый `spi-queue-ui` — прежнее имя того же репозитория; отдельная frontend-схема
была ошибкой и убрана из Git. Один образ/релиз, существующий Argo `spi-triage`;
chart и cluster values остаются в homelab. CI42585299451:295тестов в native image
без пропусков/сети при1CPU/384Mi, release image собран. **Publish skipped**, не
релиз: `PUBLISH_ENABLED=false`; native cluster access/Harbor остаются блокерами.
`bundleEnabled=false`:20ресурсов рендерятся идентично прежним; старые code/UI
ConfigMap-копии заморожены до безопасной активации, это не второй источник разработки.
**Продакшн на новый bundle ещё не переключён.** Не заявлять live UID/readiness,
queue counts или browser acceptance по CI/рендеру. Owner отменил backup prerequisite
для этого выноса/релизов, но не разрешал удалять архивы, убивать paid work или
сбрасывать budgets/leases. Нужен естественный drain и protected production review,
не новый backup blocker. Полные границы/проверки/следующие шаги:
[SPI](spi-incident-triage.md#current-source-extraction--9-november-2026).

## Деплой и источники

Постоянные изменения оформляются в Ansible/Helm/Git. Workloads — Argo CD,
`root → deploy/argocd/apps`, проект `default`. Fleet GitRepo/bundles retired;
наличие Rancher Fleet controllers не означает возврат к Fleet deployment.

Для подключённых приложений: build/test → immutable Harbor image →
`alchemmist/deploy-to-socrat@v1` → tag/digest в homelab main → Argo reconciliation
→ readiness и функциональная проверка. Push образа или коммит не равен deployment.
Уточнять состояние `automated.enabled`, hooks и конкретной Application; не делать
blanket sync/prune, `helm upgrade` или ручной image patch для обхода GitOps.

Публичный ingress/policy принадлежат **своему приложению**. Aggregate
`public-web-entry` удалён; его не восстанавливать. Grafana сейчас имеет Application
`grafana`, chart `charts/grafana` и `deploy/platform/grafana/public-entry`.
Не искать его текущего владельца в старом `kube-prometheus-stack` app.

Мониторинг разделён на `grafana`, `prometheus`, `alertmanager`, `prometheus-operator`,
`node-exporter`, `kube-state-metrics`, `loki`, `tempo`, `pyroscope`;
дашборды/rules/probes — отдельный `monitoring-k3s`. Handoff закрыт: старые
`kube-prometheus-stack`, `prometheus-stack`, `otel-backends`, `profiling` удалены без
каскадного удаления. Auto-sync включён у действующих владельцев. На закрытии
первого этапа сохранены 103 UID ресурсов; на окончательном разделении
Prometheus-компонентов повторно проверены все 77 ресурсов этого подмножества,
8 runtime Pods без перезапуска, 4 PVC и UID/содержимое 3 целевых Secrets.
Неиспользуемый общий ConfigMap удалён отдельно по UID. Не повторять retirement и не возвращать старые owners.
Итоговый checkpoint — `0bb4e31`; 104 профильных теста и 24 subtest, public regression
134/134. Это результаты закрытия миграции, не замена новой live-проверке.
Остаётся отдельная проблема WAL Prometheus; сбой digest блога исправлен
параллельным релизом `f485c74` (blog снова Synced/Healthy). Это **не** обещание
целостности WAL или здоровья всего кластера. Карта/приёмка и границы:
[деплой](cluster-deploy.md), [наблюдаемость](observability-current.md),
[первый closeout](../docs/monitoring-service-split.md),
[окончательное разделение Prometheus-компонентов](../docs/prometheus-service-split.md).

## Топология и данные

- Последняя принятая native-проверка etcd: исходные voters **0/1/2**, кворум два;
  members `socrat-0-36692c46`, `socrat-1-2398a245`, `socrat-2-eb4ac34e`.
  Прежнюю запись «0/2/3, нода1 без голоса» не использовать как текущую топологию.
- socrat-0: дом/RTX3090, vLLM/LLM, Authentik/PG, Wiki PVC, Kuma MariaDB и NFS.
  На проверке Prometheus pod также на socrat-0, не выводить placement из имени app.
- socrat-1: Grafana, Loki/Tempo/Pyroscope и часть приложений на проверке.
- socrat-2: VPS/3x-ui/edge; img-proxy закреплён именно здесь (`b3ad6e2`).
- socrat-3: внешняя control-plane/etcd нода и пользовательский desktop.
- Два публичных IP не реплицируют backend, GPU, SQLite/PVC или PostgreSQL.
  Singletons и retained PVC не являются HA/проверенным off-node DR.

Scheduler/placement сверять перед работой; старые offload-таблицы не текущая правда.
Resource budgets: `ansible/vars/container-resources.yml`, native admission policy;
requests не резервируют физическую память, сумма limits не доказывает N−1.

## Мониторинг, бот и телевизор

Collector — sole scraper; Prometheus принимает OTLP, Loki/Tempo работают в K8s.
Dashboard/rules/probes в `charts/monitoring-k3s`, datasource/provisioning Grafana —
в его текущем chart. English titles/descriptions; не скрывать telemetry gaps,
не превращать отсутствие данных в здоровый ноль. Чтение метрик — через read-only
Grafana MCP/API, браузер — для визуальной проверки.

SPI triage использует durable queue, read-only evidence и scoped GitHub App;
не получает права автоматически чинить инфраструктуру или закрывать инциденты.
[Бот](socrat-bot.md), [SPI](spi-incident-triage.md), [n8n](n8n-workflows.md).
Ручная эскалация20→10 не равна смене severity и не обещает SLA.

TV использует public traffic-light URL канонического Grafana, без внутреннего VPN.
Профиль `xiaomi-tv`/peer отозван; `alchemmist-tv` для YouTube сохранён отдельно.
Не стирать app data WireGuard. Fully55%/font75%, injectJsCode пуст; актуальный
TV layout в Git, старые panel coordinates не повторять. Физический пульт/cold boot
не считать повторно проверенными по одному screenshot: [TV](android-tv.md).

## Безопасный порядок работы

1. Fresh status/fetch и сверка владельца ресурса, версии, UID и реального placement.
2. Read-only аудит; явный scope, private backup, fresh preconditions/lock/CAS.
3. Декларативное изменение и профильные tests/render/syntax checks.
4. Только согласованное точечное применение; uncertain write → остановка/разбор,
   не слепой retry. Никаких глобальных firewall/DNS/VPN/K3s/DB рестартов попутно.
5. Отдельно доказать readiness, native права, negative cases и реальные user steps.

Не трогать посторонние worktree/Playwright profile. Не stash/reset/force-push.
Для Ansible единый `inventory/hosts.yml`, четыре ноды `Socrat`; для подмножества
явный `--limit`. App/browser MFA не даёт право взять owner kubeconfig.
Локальные `/tmp`-артефакты не постоянный deployment dependency.

Эта актуализация — документация с read-only аудитом, не повторная миграция,
не browser acceptance, не завершённый первый вход человека и не общий зелёный suite.


## MCP в репозитории

Agent entrypoint — `AGENTS.md`, settings — `.pi/mcp.json` (без секретов в Git).
Официальные подключения и полный audit/ограничения: [official-mcp.md](official-mcp.md).
n8n MCP после локального обновления токена проверен (`initialize`/`tools/list`)
и включён на Mac: поиск/чтение workflows, без execution. Токен только в private
файле0600, не в Git. В committed config n8n пока disabled; другие машины не
настроены автоматически. Umami остаётся опциональным и ждёт authorized analytics
key; не обходить это через reset/DB. Новых обязательных MCP на кластере не требуется.


VPN83 latest owner clarification: users will refresh subscriptions themselves.
Native32063 excludeFromSub=true applied, enabled=true retained for cached clients.
All16 URI+JSON subscriptions verified public/backend before/after: exactly7 plaintext
links removed (78 URI entries remain), unrelated profiles/keys/URLs preserved.
Server publication migration done, not device refresh/legacy retirement. No device
remote-control prerequisite for this phase; wait for owner refresh confirmation
before closing32063. Temporary tokens removed; see llm-wiki/vpn-hardening.md.


VPN83 latest: raw public eth0 TCP12096/32087 rejected by a dedicated persistent
exact-owned guard; external resets+TLS443 and all16 URI/JSON subscriptions verified.
Own Trojan64KiB before/after; no rule replay after nft1.0.6 readback correction.
Real socrat-0 HOME FIXED WAN now passes own REALITY32053+TrojanTLS44364KiB each;
expected home source, not overlay; routes/resolver unchanged, all probe credentials
cleaned, four nodes Ready.71 tests+6 subtests. Mobile/reboot not tested. Legacy32063
still excluded+enabled pending actual refresh confirmation; WATCHDOG CONFIG STILL
REQUIRES IT, so no blind API disable (would false-fail/fence). Coordinated watchdog
source/live config+monitoring update is required before retirement. See VPN wiki.


VPN83 latest supersedes previous retirement gate: OWNER APPROVED old-client
DISCONNECT.32063 now disabled+excluded, no listener/external TCP refused. Source/live
watchdog dependencies+collector updated under existing lock, timer resumed, recovery
healthy/not inhibited. All16 URI/JSON subscriptions preserved; users refresh SAME
URL/select encrypted profile, keys unchanged. Actual HOME WAN REALITY+Trojan64KiB
repeated after cutover, passed; no global network change, all temp keys/clients clean.
133 tests+8 subtests scoped. Server move complete, do not re-enable32063. Mobile,
reboot/DR and future-IP-ban immunity not claimed. See authoritative VPN wiki latest.


VPN active incident19:07–19:45UTC supersedes availability assumptions: owner says all
phone profiles now fail on mobile too. New literal-VPS TCP timed out home+workstation,
internal health/4nodes/auth fields intact. Independent GermanyTCP443 succeeded10ms:
regional/source filtering or routing suspected, not proven TSPU. vpn hostname DNS
currently HOME IP (TLSworks), not VPS; earlier Trojan hostname probe exact path was
not recorded, do not claim literalVPS443 from it. Paired header diagnosis unavailable
home tcpdump missing; no matched packet attribution. No repair/IP change performed.
Don't use HOME as VPN fallback without explicit risk consent or remove old IP before
safe parallel replacement. See VPN wiki/runbook incident section; future ban immunity
never established.


Observer alert active20:02–20:24: exact cause identified read-only. CoreDNS onVPS
returns Authentik hostname→VPS109.120.141.97; home CoreDNS→HOME109.173.40.247,
cluster VIP alternates. Actual worker socket SYN_SENT/retrans toVPS443, notKubeAPI.
VPS authoritative refresh loopback probes see home=False/vps=True and publishVPS
while home authority publishesHOME; provider upstreams inherit that split, not
proven stale/poisoned DNS. Membership token valid; groups/users HTTP200 through
working path; verified internalTraefik443 Host/SNI endpoint works. No repair yet.
Proposed scoped internal auth-name DNS mapping with fresh approval/preimages,
no globalDNS/node restarts/RBAC broadening/token rotation. Historical observer
acceptance != current revocation bound. See observer acceptance incident appendix.


Observer reconciliation DNS FIX ACCEPTED20:46UTC: auth hostname internal-only now
maps private HA VIP192.168.0.250 via scoped coredns-custom key. InitialServiceIP
attempt failed worker network-policy acceptance; own key corrected under fresh
CAS, NO NetworkPolicy widening. Both CoreDNS replicas+VIP agree; natural successes
20:44/45/46, Prometheus no pending/firing, freshness18s. Private receipt at
/var/lib/homelab-observer-rollout/observer-internal-dns-vip-20261108 on socrat-0.
Source scripts/observer-internal-dns.py, runbook deploy/identity/authentik-internal-dns.md.
No tokens/RBAC/publicDNS/VPN changes/restarts. PublicVPN incident NOT repaired by this.


Cheap resilience phase1 accepted21:23UTC, source219eddf: observer CronJob now runs
safe diagnostics wrapper; original controller/Wiki bytes and all policy/credentials
unchanged, no Wiki Recreate rollout. Argo rancher Synced/Healthy, three new natural
jobs21:21/22/23 succeeded; no freshness alert,32s freshness. Private preimages/proofs
socrat-0:/var/lib/homelab-observer-rollout/resilience-phase1-20261108/. New scripts
public-entry-health.py (on-demand credential-free TLS+OIDC backend probe; self/
hairpin not external proof) and public-entry-failover-plan.py (OFFLINE ONLY, always
ready_to_publish=false, no renderer/zone changes).93tests+195subtests. See docs/
network/entry-resilience-phase1-20261108.md for gates/partial results.
NEW21:15 degradation: VPS private10.250.0.2:2222/443 times out also FROM HOME,
socrat-2 ReadyUnknown, other three Ready. VPS observation launch failed before
execution; no fallback/relaunch/route repair or writes onVPS. Owner asked whether
IP/power changed. Do NOT reuse earlier4Ready/internalVPS green as current evidence.
Public VPN/network incident unresolved; new shared DNS publisher NOT deployed.


## VPS migration recovery — 2026-11-09, fresh acceptance

This supersedes the prior unreachable/ReadyUnknown observation, not its history.
Owner rebooted socrat-2; persistent NEW=109.120.141.60/24, gateway109.120.141.1.
All four nodes Ready; watchdog Kubernetes healthy=true; native fallback inactive.
Management uses owner-authorized direct NEW:2222 with pinned key and /usr/bin/ssh;
old controller wrapper is not private-only evidence and must not be reused blindly.
Do not further alter Mac WireGuard; corporate Tunnelblick/routes/DNS preserved.

Seven stale panel host addresses migrated via native API only, with uncertain-call
readback/reconciliation and no replay.16 identities/85 bindings, credentials,
quotas and disabled legacy32063 preserved; temporary admin tokens removed.
All16 URI subscriptions(78 entries) and JSON(72) match backend/public TLS pinned
NEW, zero OLD. Own temporary HOME-WAN identity authenticated REALITY and
TrojanTLS to literal NEW with HTTP200/65536 bytes each; no overlay/global proxy,
fixture removed. This is NOT mobile/operator acceptance or filtering attribution.

Source d8a5e54 merged normally with upstream SPI extraction and pushed as0642a36;
bot/netbird/traefik-edge/spi-triage naturally Synced/Healthy at that revision.
No blanket sync/prune. Bot runtime webhook env and Telegram destination NEW;
queue2 ->0, existing machine secret/URL/allowed updates retained, no duplicate
mailing command sent. Recipient-level mailing completion remains unproven.
REG.RU accepted ns2-only glue change; **both x.nic.xyz/y.nic.xyz now publish NEW**,
ns1=109.173.40.247 and both NS names unchanged; cached old glue can outlive this.
Public NEW UDP53 authoritative answer and STUN Binding verified.

Still separate: owner phone refresh/connectivity; mailing recipient confirmation;
RustFS manual-sync auth-egress /32 runtime (source changed, app still old revision);
Collector delivery, off-host DR and workstation NetBird LoginFailed. Public
backend eth0 TCP12096/32087 denials preserved (external refused;443 open), priority-6.
NetBird added one nb-host-only accept to that accept-policy chain: read-only proof
shows no public-rule change/no-op semantics; installed exact-table validator stops
on the extra rule, so do not blindly run ensure/rewrite the table. No firewall edits.
Runbook/evidence index: docs/vps-ip-migration-20261108.md. Focused166tests+21subtests.


2026-11-09 10:50UTC correction: owner's Traffic Light report exposed frozen native
Collector scrape target OLD despite chart/ServiceMonitor NEW and Argo Synced.
One-target CAS + validated projected config, then existing exact-container graceful
activation on socrat-0. Same pod/volumes and Prometheus/Thanos/reloader IDs; all Ready.
Fresh NEW:443 probe_success1; actual live socrat-traffic-light panel906 expression0
(verified live mapping OK/green); old alert naturally gone, no silencing/deletion.
Native VPS-probe Collector delivery gate now passed. Other telemetry/DR gates
remain separate. Evidence: docs/vps-ip-migration-20261108.md, private socrat-0
/var/lib/homelab-observer-rollout/traffic-light-vps-ip-20261109/.

### Recovery continuation 2026-11-09 13:54UTC

- `docs/cluster-recovery-20261109.md` now has power timeline, queue preservation and
  exact WAL bit-repair receipts.00001786 repaired13:34 **without restart/truncate**:
  native6409 records valid, all11716 affected samples exact-match independent raw
  Thanos; original/candidate also off-host. **Next native checkpoint pending**;
  retain no-restart/no-silence gate until subsequent-segment/native acceptance.
- Effective vLLM kubelet/allocated request10Gi same process; observer13:48 natural
  success, critical cleared. Four safety rules live; rule-engine evaluation remains
  to verify. Node3 queue draining25→9MB but HDD I/O warning not yet fixed; keep fsync.
- fwupd metadata-only service recovered naturally. Three terminal failed Job
  objects retained with evidence; current native replacements successful. Do not
  erase/relable failures just to clear warning. Detailed historical cause pending.

14:40 update: native safety engine all4 health=ok/inactive, fresh voters3. Node3
queues0 and Loki delivery fresh;1s filelog poll + infinite receiver retries applied
only there (consistent backup, fsync retained),5m I/O6.9% and contention naturally
cleared. Fresh etcd common-revision hash agreement and post-recovery snapshot/current
panel online backup off-host SHA verified. Guard validator compatibility repaired
without any nft write. Original16/85 unchanged; current17/91 has1 external addition,
not attributed/deleted. Only3 old failed Jobs + historical compaction alert firing;
**next normal WAL checkpoint still pending**, no restart/silence shortcut.

### Latest acceptance 2026-11-09 15:15UTC (supersedes pending WAL notes)

Normal native WAL checkpoint **1786→2388** succeeded15:10 after9m54s; same Pod/all
container IDs, no new failure in read-only watch, no forced restart/truncate/replay.
All4 nodes Ready/no active nonready Pods; actual TLS LMS303/Umami heartbeat200;
observer/SPI/Wiki/Thanos natural jobs successful. I/O5m5.4%, warning cleared.
Only3 old terminal failed Jobs (no TTL) and historical3h compaction warning remain;
no masking/reset/delete. Full receipts and explicit remaining physical-power,
unknown old hashKV/bit-flip, DR/NetBird/mobile/site-HA limits in recovery runbook.

### Moscow staging 2026-11-09 — five nodes, production VPN cutover still pending

`socrat-4` is a constrained **agent-only** worker at mesh `10.250.0.40`, public
`91.189.82.238`, standard owner SSH2222/zsh/welcome. Explicit TOFU pin accepted;
no console blocker. All5 Ready/MemoryPressure=False; bootstrap NoSchedule remains,
no new ordinary workloads/storage. Mac's four approved management routes unchanged.
New scoped native telemetry is functional: fresh Grafana/Thanos node_uname_info and
count-only Loki104 records/5m. Existing CA/leaves and historical data untouched.

Independent host Xray relays fixed ports through separate encrypted Moscow↔NL
`10.251.4.1/.2` link. Actual HOME→**91.189.82.238**→NL authenticated **REALITY,
Trojan and WireGuard/UDP** each passed HTTP200/65536B/hash, separately proving exit
**109.120.141.60**. Own expiring fixture/tokens removed; original config preserved.
**No subscription/DNS or production HOME→NL route switch yet**; old VPN remains.
No mobile/Happ, AmneziaWG, comprehensive MTU/failure or complete transit claim.
Next authorized steps and private evidence/replay rules:
[dated staging runbook](../docs/moscow-vpn-transit-20261109.md). No new approval needed.


### Production VPN cutover 2026-11-09 (supersedes staging-only boundary)

Native Hosts7/7 and all three DNS writers now publish **Moscow91.189.82.238** for
VPN; URL/domain unchanged,17 identities/91 bindings preserved,32063 disabled.
Normal-DNS strict-TLS subscriptions84 URI/77 JSON match backend with no old NL IP.
Post-fence HOME authenticated Yahoo/Sony REALITY, AMDgRPC, Trojan and WG each pass
HTTP200/65536B/hash and exitNL109.120.141.60. Actual protected cross-host UDP
32/1200/1420/1472/8192B round trips passed default settings; temporary fixtures gone.
HOME0/3 WG and HOME1 pinned-TLS/GOST management now transit Moscow. Known public
NL HTTPS/DNS/VPN flows also use scoped persistent HOME DNAT (not default routes).
DNS uses private Moscow→private NL Knot listener; one scoped NL Knot restart,
public listener preserved. Raw NL WAN VPN ports fenced;12096/32087 still closed.
Final shared443 Trojan-path allowlist **accepted**: public403/private101 with
spoofedXFF rejected; exact loopback127.0.0.1/32 retains real watchdog WS health.
Initial private-only ACL accidentally denied that probe and triggered native
fallback/K3s fencing on NL. Resolved transparently: unchanged health/hash checks,
native failback of original member, start bound180→600s after measured160MB Raft
catch-up>180s. No reset/member replacement. After recovery:3 healthy voters/hashKV
equal at common revision17449598,5Ready/noMemoryPressure, all five HOME transports
and17 normal-DNS subscriptions retested; enabled watchdoghealthy/no fallback.
Same source gate also installed/validated in native Caddy; see incident details.
Fresh native3-voter/common-leader/hashKV agreement and5Ready/noMemoryPressure;
all5 canonical metrics fresh. Five private native archives off-host SHA verified.
Details, replay/custody and honest mobile/AWG/source-IP/HA limits:
[production cutover](../docs/vpn-production-cutover-20261109.md).

TV11November owner correction: latest service-diverse dashboard supersedes AI-heavy
free-space fill. Only own930–935 revised: purpleRustFS RX/TX, tealHarborregistry RX/TX,
compactpinkAIqueue+TTFTp95/15m, LMS/n8nbackupages (HTTPworst3removed by owner).
62panels, original57/Argo909CSS/VPN/share
unchanged. ActualfinalTVfit checked afterdebugfalse cleanup/Fully-onlyrestart;
49Argo fills physicallycounted. No nativeRustFS/Harbor business scrape: networkbytes
are NOT object/pullpush counts; no exporter/backend/CSS changes. Fullsemantics,
currentpositions and60focusedtest acceptance: llm-wiki/android-tv.md latestsection.

LatestTV cascadefooter11November supersedes the two-wide-backup arrangement:
934/935 noww2,h2 atx12/14,y18;936x16,w8,h2 addsfour goldfigures (cascadeJobage,
rawdownsampletodo, haltedcount only3freshstages, append samples/s5m).63panels;AI,
RustFS/Harborh4+curves/VPN/Argo/share andother60existingpanels exact unchanged.
Trialh3 hidnativecurves, so packed WIDTHinstead, no newCSS. No data gray, not0.
ActualfinalTVfit checked afterdebugfalse cleanup/Fully-onlyrestart;49Argofills,
61focusedtests, onlydashboardCM render. No pipeline/Job/retention change orDRclaim.
Details/evidence: android-tv.md latestMetricscascadefooter section.
