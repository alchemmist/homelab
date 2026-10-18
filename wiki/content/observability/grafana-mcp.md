---
title: "Grafana MCP: подключение агента"
weight: 25
---

Grafana MCP даёт агенту доступ к дашбордам, запросам Prometheus и правилам алертов нашего кластера. Сервер работает только на чтение: изменения дашбордов по-прежнему вносятся через конфигурацию homelab.

## Параметры подключения

| Параметр | Значение |
| --- | --- |
| URL | `https://grafana-mcp.socrat.alchemmist.xyz/mcp` |
| Transport | `Streamable HTTP` |
| Authentication | Заголовок `Authorization: Bearer <token>` |
| Сеть | Административный WireGuard `socrat-wg` с приватным DNS |

Подключение выполняется с компьютера, где запущен MCP-клиент. Облачный агент без доступа к `socrat-wg` до этого адреса не доберётся. Адрес `/mcp` — протокольный endpoint, а не веб-страница.

## Получить токен

Токен выдаёт администратор кластера. Это отдельный токен MCP, а не пароль пользователя Grafana. Не вставляйте его в сообщения агенту, wiki или Git.

Администратор с SSH-доступом к `socrat-0` может загрузить токен непосредственно в окружение терминала, не выводя его на экран:

```sh
SOCRAT_GRAFANA_MCP_TOKEN="$(ssh socrat-0 'env K3S_CONFIG_FILE=/dev/null k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n cattle-monitoring-system get secret grafana-mcp-credentials -o jsonpath="{.data.client-token}"' | base64 --decode)"
test -n "$SOCRAT_GRAFANA_MCP_TOKEN" && export SOCRAT_GRAFANA_MCP_TOKEN
```

Клиент должен унаследовать эту переменную: запустите его из того же терминала. Уже открытое приложение новое окружение не получит. Для постоянного хранения используйте своё защищённое хранилище секретов.

## Cursor

Добавьте запись в `~/.cursor/mcp.json`, сохранив остальные серверы:

```json
{
  "mcpServers": {
    "socrat-grafana": {
      "url": "https://grafana-mcp.socrat.alchemmist.xyz/mcp",
      "headers": {
        "Authorization": "Bearer ${env:SOCRAT_GRAFANA_MCP_TOKEN}"
      }
    }
  }
}
```

После запуска с нужным окружением проверьте подключение в настройках MCP. Удалённые серверы Cursor поддерживают подстановку переменных в `headers`; поле `envFile` предназначено только для локальных STDIO-серверов. [Документация Cursor](https://cursor.com/docs/mcp).

## Claude Code

В `.mcp.json` проекта добавьте сервер с явным типом `http`:

```json
{
  "mcpServers": {
    "socrat-grafana": {
      "type": "http",
      "url": "https://grafana-mcp.socrat.alchemmist.xyz/mcp",
      "headers": {
        "Authorization": "Bearer ${SOCRAT_GRAFANA_MCP_TOKEN}"
      }
    }
  }
}
```

Запустите `claude` из терминала с экспортированной переменной, разрешите подключение проектного сервера и проверьте его через `/mcp`. В конфигурации остаётся имя переменной, а не её секретное значение. [Документация Claude Code](https://code.claude.com/docs/en/mcp).

## Что попросить у агента

- «Найди дашборд Overview и покажи запрос панели с неготовыми pod».
- «Проверь, какие Prometheus targets сейчас недоступны».
- «Сравни очередь vLLM и использование GPU за последний час».
- «Покажи активные правила алертов и объясни их условия».

MCP читает реальные данные Grafana. Для оценки внешнего вида графиков по-прежнему нужен [интерфейс Grafana]({{< relref "observability/grafana.md" >}}). Логи Loki будут доступны только после подключения соответствующего источника данных и инструментов на сервере.

## Если подключение не работает

| Симптом | Что проверить |
| --- | --- |
| DNS error или timeout | Подключён ли `socrat-wg`, используется ли его DNS |
| HTTP 401 | Токен задан, не устарел и передан с префиксом `Bearer ` |
| HTTP 403 | Запрос идёт через разрешённую приватную сеть |
| HTTP 502 или 503 | Доступны ли MCP-сервер и Grafana внутри кластера |
| Соединение есть, инструмент вернул ошибку | Источник данных, запрос и выбранный временной диапазон |

Не отключайте проверку HTTPS-сертификата для обхода ошибки подключения.

Если имя открывали до настройки приватного DNS, macOS может сохранить старый публичный адрес. В `socrat-wg` имя должно возвращать `10.250.0.3`. Проверка приватного DNS:

```sh
dig @10.250.0.2 grafana-mcp.socrat.alchemmist.xyz A +short
```

Для очистки системного DNS-кеша macOS:

```sh
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

Эти команды меняют только DNS-кеш клиентского Mac, а не настройки или сеть нод.

Сервер основан на официальном [grafana/mcp-grafana](https://github.com/grafana/mcp-grafana).
