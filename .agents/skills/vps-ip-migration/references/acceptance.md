# Acceptance ledger — заполнить для каждого переезда

Не отмечать «passed» по наличию config. Значения: **passed / failed / unknown /
not applicable (reason)**. Записывать UTC/time window и vantage. Если обязательный
пункт unknown, общий статус — **не завершено**, либо явно ограниченный server-only.
Evidence приватная, только sanitized summary в Git.

| Проверка | Обязательный результат / evidence |
|---|---|
| Provider assignment/persistence | NEW назначен VPS; source route работает; persistent network owner известен |
| Management | Приватный доступ сохранён; новый direct SSH проверен с прежним pinned host key |
| Repository | reviewed allowlist diff, targeted tests, обычный commit/push, remote revision verified |
| Host phase | audit всех 4 узлов; reviewed apply; private preimages/receipt; нет partial failure |
| Native services | Knot/TCP transport/guard active; новый bind; только ожидаемые restarts |
| Mesh | persistent + runtime endpoint нового VPS; свежие handshakes между нужными peers; no interface/key replacement |
| Control plane/storage | nodes Ready; прежние identities/volumes; etcd и DB не пересозданы |
| Primary 3x-ui | exact hosts.address changes only; private consistent backup; quick_check; credentials/IDs invariant |
| Retained legacy | адрес обновлён, БД проверена; dormant runtime **не запущен** |
| Panel lifecycle | только точный x-ui pod; Ready; повторный subscription/tunnel test после последнего reload |
| Plain subscriptions | все enabled; decoding/base64/vmess; count OLD=0; NEW/other классифицированы; ошибки=0 |
| JSON subscriptions | все enabled; valid JSON; OLD=0; no user identifiers/body in evidence |
| VPN from HOME | authenticated tunnel literal NEW (не hostname или self-hairpin), neutral HTTPS + Telegram + ChatGPT |
| VPN from PHONE | выбранный пользовательский профиль обновлён; Wi-Fi/mobile проверены пользователем или явный pending |
| Other VPN protocols | используемые Reality/VLESS/WG/Amnezia протоколы реально проверены, либо каждый явно unknown |
| Public HTTPS | оба входа, корректный TLS/SNI, актуальные health/login semantics; backend reachability |
| Both child authorities | UDP/TCP 53 NEW bind; NS + SOA + A, действующий serial/TTL; OLD не публикуется |
| Registrar | сохранены прежние NS names и IP ns1; только ns2 → NEW; подтверждение кабинета |
| Parent glue | прямые ответы минимум двух `.xyz` authoritative возвращают NEW (не только child A) |
| Recursive DNS | Google/Cloudflare DoH observed values, TTL/cache lag отдельно от registrar publication |
| Kube live audit | functional specs/ConfigMap/Secret address fields reviewed; no unexplained OLD reference |
| Native Collector target | один owned blackbox target NEW; остальные jobs/collector.yaml preserved |
| Collector activation | fresh UID/ID/image/config/binary receipts; same pod; neighbors IDs/restarts unchanged |
| Telemetry gate | duration, log/metric sent deltas, refused/failed/enqueue deltas, queue samples/drain, freshness |
| Availability alert | NEW instance probe_success=1; old alert naturally resolved, no silencing/series deletion |
| Loki/Tempo | прежние owners/routes/mTLS/data; ingestion/readiness не сломаны изменением сети |
| NetBird | STUN bind + advertised URI NEW; exact secret change; server reload + Ready; external UDP test |
| Relay privacy | source semantics validated without printing raw client IP; no open unauthenticated TURN |
| Bot webhook | Telegram API sees NEW, queue/error timestamps understood; fresh delivery tested или отдельно unknown |
| NetworkPolicies | RustFS auth/gateway and NetBird policy IP updated in правильных namespace; no broader exposure |
| Local clients | generated Mac profile **и imported profile** distinguished; SSH aliases pinned; phone action explained |
| GitOps state | нужные revisions применены; remaining unrelated OutOfSync описан, no blanket prune |
| Cleanup | bounded probe processes stopped; temporary pods/Secrets/bundles absent; permanent backups kept |

## Остановиться, а не продолжать

- Утерян последний доступ; новый IP ещё не назначен; identity отличается.
- Неожиданный source/schema/owner или неизвестный affected inactive unit.
- SQLite invariant/quick_check failed; нет защищённой согласованной preimage.
- Container/image/config/binary pin mismatch; Collector neighbor перезапустился.
- Receiver/exporter failures растут, queues не дренируются, метрики/логи устарели.
- Секрет попал в stdout/Git: прекратить публикацию, сообщить оператору, отдельное
  решение о remediation/rotation; не делать вид, что редактирование лога всё исправило.
- Parent glue OLD после сохранения: pending registrar, не «готово» и не recursive cache.
- После apply ошибка: читать receipt/preimages, устанавливать actual state,
  не повторять importer/deployer и не откатывать живую БД целиком.
