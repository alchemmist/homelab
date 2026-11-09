# Публичный DNS alchemmist.xyz

Актуализировано **9 ноября 2026** (VPN cutover; старые приёмки датированы ниже). Текущий сетевой итог: [network-access.md](network-access.md). Это схема и результаты выполненных приёмок, не непрерывный healthcheck и не инструкция повторить migration apply.

## Адреса и делегирование

| Назначение | Текущий адрес |
|---|---|
| HOME / ns1.alchemmist.xyz | `109.173.40.247` |
| VPS / ns2.alchemmist.xyz | **`109.120.141.60`** |

`109.120.141.97` — промежуточный старый адрес, миграция на`.60` завершена отдельно.
`176.98.185.59` — старый VPS адрес, использовавшийся до 5 ноября. Старые результаты 1–2 ноября относятся к нему, а не к новому IP. Миграция обновила source/runtime и REG.RU glue; новый адрес проверен у родителя. Шлюз провайдера `176.98.185.1` сохранён намеренно, не заменять его вместе со старым IP.

1. Резолвер спрашивает `.xyz` о NS `alchemmist.xyz`.
2. Родитель возвращает `ns1`/`ns2` и registrar glue на HOME/NEW VPS; в наблюдавшейся делегации TTL glue 3600s.
3. По glue запрашивается authoritative Knot. Внутризонные NS/A используют TTL 60s. Это не замена родительского glue: bootstrap не должен зависеть от запроса к самому ещё не найденному NS.

## VPN — отдельный статический московский вход

`vpn.alchemmist.xyz IN A 91.189.82.238`, TTL60, на всех0/1/2 writers. Удалён из
FAILOVER, находится в STATIC_A: при отказе Москвы не публиковать NL/HOME как
скрытый fallback. Прочие records проверены на всех четырёх health-комбинациях;
NS1 HOME и принятый NS2/glue NL не менялись, registrar не пересылался.
NL authoritative Knot дополнительно слушает private10.251.4.2:53; московский
private relay10.250.0.40:53 передаёт TCP/UDP по отдельному WG. Один scoped NL Knot
restart был нужен для listener, public listener сохранён; startup dependency на WG.
Никакого Mac resolver override. Это не HA/partition-consistency гарантия трёх writers.
[Production evidence/incident](../docs/vpn-production-cutover-20261109.md).

## Что стоит на узлах

Knot работает на ОС socrat-0/1/2, не в pod. Source: `ansible/playbooks/public-authoritative-dns.yml`, renderer `scripts/public_dns_zone.py`.

- Домашний DNS слушает VIP `192.168.0.250:53`; роутер пересылает на него TCP/UDP 53. HOME HTTPS 80/443 также обслуживается через существующую схему VIP.
- VPS authoritative DNS слушает новый публичный адрес.
- Каждые 30s проверяется TCP 443; для failover-имён публикуются ответившие входы. Если не ответил ни один, сохраняются оба адреса, чтобы зона не опустела.
- Record TTL 60s; серверы обновляют зону независимо, SOA serial может немного различаться.
- `mail`, `sync`, `rooms`, `devsyringe` остаются HOME-only согласно renderer, а не автоматически получают два IP.

Новые public human entrances используют обычную authoritative зону. `kuma.socrat.alchemmist.xyz` добавлен в failover names после обнаруженного NXDOMAIN, блокировавшего ACME. Он не обозначает native Kuma admin grant: HTTPS gate и app auth описаны отдельно.

Временный `tv.alchemmist.xyz` **полностью retired**: больше не входит в renderer/zone, owned Ingress/Certificate/TLS Secret удалены. Телевизор использует `grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>` без внутреннего WG. Не добавлять отдельный TV домен обратно.

## Как менять и проверять

Не править разные authoritative серверы независимо вслепую. Сначала проверить все четыре health-комбинации renderer: все несогласованные records должны оставаться byte-equivalent. Затем whole-fleet preflight, fresh exact hash, serial owned-zone refresh с private backups/receipts, без daemon/node restart. При uncertain marker остановиться, не повторять write.

- `scripts/public-web-dns.py` / `public-web-dns.yml` — узкая первоначальная Kuma addition, не универсальный DNS editor.
- `scripts/grafana-tv-dns.py` / `grafana-tv-dns.yml` — теперь только retirement временного TV alias, не его создание.
- `scripts/vps-ip-migration.py` — отдельная completed migration; не запускать ради текущей DNS-проверки.
- `scripts/retire-tv-public-alias.py` — только exact owned Kubernetes alias resources; не blanket Argo prune.

Финальные DNS retirement audits трёх узлов показали operations=0; alias-resource audit — operations=0. Остальные records сохранены. Ключи NS/SSH, credentials и частные receipts в wiki не помещать.

Примеры read-only проверки с подходящего внешнего vantage:

```sh
dig @x.nic.xyz alchemmist.xyz NS +norecurse
dig @109.173.40.247 alchemmist.xyz SOA +norecurse
dig @109.120.141.60 alchemmist.xyz SOA +norecurse
curl -sS -H 'accept: application/dns-json' \
  'https://dns.google/resolve?name=grafana.socrat.alchemmist.xyz&type=A'
```

Домашний UDP `dig @8.8.8.8` ранее перехватывался и мог показывать старый TTL/AA. Для независимого рекурсивного cache view использовать DoH и другой provider/device; один локальный UDP результат не доказывает глобальную делегацию. Forced routing `curl --resolve` с правильным Host/SNI/TLS проверяет конкретный entrance, **не** обычное DNS-разрешение и не независимый внешний доступ.

## Mac и границы отказоустойчивости

Owned Mac `/etc/resolver` overrides и wiki restorer lifecycle сняты, глобальные DNS/corporate VPN настройки не менялись. Обычный public HTTPS больше не зависит от workstation overrides; NetBird DNS выключен. Внутренний SSH закреплён за private адресами отдельно от публичного DNS. Server-side private DNS для иных consumers может оставаться. См. [итог Mac cleanup](network-access.md#7-mac-старый-owned-dns-lifecycle-снят-полностью).

Кэш не узнаёт об отказе до expiry и может держать запись дольше TTL. Уже открытые соединения не переезжают, клиент не обязан повторять DNS после TCP timeout. Public IP failover не копирует PVC/SQLite/MariaDB/GPU и не делает Authentik/management HA. Traefik Edge может использовать последние маршруты без кворума только пока живы процесс, сеть и backend pods. Потерянный backend/storage DNS не восстанавливает.

Источники: [public ingress](../docs/public-ingress.md), [VPS migration](../docs/vps-ip-migration-20261105.md), [public-web closeout](../docs/public-web-migration.md), `docs/router-static-mappings.md`.


##2026-11-08: partial-network failure / phase1 observation

Current public renderer remains independently local-probed; it is NOT consensus
failover. With VPSIP inaccessible from HOME/mobile but locally healthy onVPS, the
VPS authority can publishVPS while HOME publishesHOME. Two CoreDNS upstream views
then disagree. Internal Authentik dependency was scoped to privateHA-VIP192.168.0.250
(no public DNS change) to restore observer revocation; this does not repair outside
browser fallback or make Authentik/storage HA. Full chronology in observer acceptance.

New on-demand scripts/public-entry-health.py checks forced-IP correct Host/SNI/
verifiedTLS/OIDC backend (no credentials). Local/hairpin probes are NOT external
reachability. scripts/public-entry-failover-plan.py only prepares deterministic
shared decisions with hysteresis and missing/stale/partition warnings; ALWAYS
ready_to_publish=false. No production DNS publisher/timer/TTL/zone change. Trusted
independent collector identities, distribution/leadership/fencing/stale leases,
partition policy and fleet acceptance required before rollout. See network phase1
runbook. By21:15 internalVPS path also timed out/ReadyUnknown; older healthy-VPS
facts are historical, not present availability proof.
