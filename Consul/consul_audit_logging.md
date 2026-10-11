# Consul Audit Logging

**Актуально для:** Consul 2.0.x / 1.22.x / 1.20.x / 1.19.x

## Определения

**Consul Audit Logging** — механизм записи всех аутентифицированных событий, проходящих через HTTP API Consul, в журнал аудита. В отличие от обычных логов агента, audit log фиксирует *кто*, *что*, *когда* и *с каким результатом* выполнил, что является требованием compliance frameworks (PCI-DSS, HIPAA, SOC 2).

> **Важно:** Audit logging доступен только в Consul Enterprise. ACL должны быть включены для использования этой функции.

## Основные концепции

### Архитектура

Audit logging работает на уровне HTTP API каждого агента (server и client). Consul перехватывает каждый входящий HTTP-запрос, фиксирует событие в двух фазах:

1. **OperationStart** — агент начал обработку запроса.
2. **OperationComplete** — агент завершил обработку запроса и записал HTTP-статус ответа.

Каждое событие генерирует отдельную запись в audit log. Это означает, что один пользовательский запрос может создать две записи: одну на старте операции, вторую на её завершении.

### Область покрытия

Audit log фиксирует **только события, инициированные через HTTP API**. Операции, выполняемые по внутреннему RPC-каналу между агентами, не попадают в audit log.

| Категория | Примеры событий |
| :--- | :--- |
| **ACL операции** | Создание/удаление токенов, политик, ролей; изменение прав через HTTP API |
| **Конфигурация** | Запись config entries (service-router, service-splitter, intentions) |
| **KV операции** | Запись/удаление ключей через HTTP API |
| **Аутентификация** | Вход через auth methods |
| **Operator команды** | Команды, обращающиеся к HTTP API (`consul snapshot`, `consul operator raft` и др.) |
| **Каталог сервисов** | Чтение/запись записей через `/v1/catalog/*` |

### Формат вывода

Consul поддерживает один формат:
- **JSON** — единственный доступный формат, структурированный, подходит для SIEM.

### Sinks (цели доставки)

Consul отправляет audit log только в:
- **Файл** (`file`) — локальный файл на каждом сервере. Это единственный поддерживаемый тип sinks.

### Параметры конфигурации

| Параметр | Тип | Назначение |
| :--- | :--- | :--- |
| `enabled` | bool | Включает audit logging. По умолчанию `false`. |
| `sink` | object | Блок с именем sinks. Ключ — имя sinks. |
| `type` | string | Тип sinks. Только `file`. |
| `format` | string | Формат вывода. Только `json`. |
| `path` | string | Путь к файлу audit log. |
| `delivery_guarantee` | string | Гарантия доставки. Только `best-effort`. |
| `mode` | string | Правa на создаваемые файлы audit log (например, `"0600"`). |
| `rotate_duration` | duration | Интервал ротации файла. Хотя бы один из `rotate_duration` или `rotate_bytes` обязателен. |
| `rotate_max_files` | int | Максимальное количество ротированных файлов. |
| `rotate_bytes` | int | Максимальный размер файла в байтах. Хотя бы один из `rotate_duration` или `rotate_bytes` обязателен. |

## Практические сценарии

### 1. Включение audit logging (файл)

```hcl
# В конфигурации агентов (server.hcl / client.hcl)
audit {
  enabled = true

  sink "consul-audit" {
    type   = "file"
    format = "json"
    path   = "/var/log/consul/audit.json"
    delivery_guarantee = "best-effort"
    mode   = "0600"
    rotate_duration = "24h"
    rotate_max_files = 15
    rotate_bytes = 25165824
  }
}
```

> **Важно:** После изменения конфигурации audit logging требуется полный перезапуск агентов Consul. Параметры audit не входят в перезагружаемую конфигурацию (`reloadable configurations`).

### 2. Вывод audit log в stdout

Для контейнеризированных окружений (Docker, Kubernetes) audit log можно направлять в stdout и собирать через стандартный механизм логирования платформы:

```hcl
audit {
  enabled = true

  sink "consul-audit-stdout" {
    type   = "file"
    format = "json"
    path   = "/dev/stdout"
    delivery_guarantee = "best-effort"
  }
}
```

### 3. Несколько sinks

Consul позволяет определить несколько sinks одновременно. Это полезно, когда требуется дублировать audit log в несколько файлов с разной политикой ротации:

```hcl
audit {
  enabled = true

  sink "short-term" {
    type   = "file"
    format = "json"
    path   = "/var/log/consul/audit-recent.json"
    delivery_guarantee = "best-effort"
    rotate_duration = "24h"
    rotate_max_files = 7
  }

  sink "long-term" {
    type   = "file"
    format = "json"
    path   = "/var/log/consul/audit-archive.json"
    delivery_guarantee = "best-effort"
    rotate_bytes = 1073741824
    rotate_max_files = 30
  }
}
```

### 4. Валидация

```bash
# Проверка конфигурации агента
consul validate /etc/consul.d/server.hcl
# → Configuration valid!

# Поиск сообщений о запуске audit logging в логах агента
journalctl -u consul -f | grep -i audit
# → 2026-09-30T10:00:00Z [INFO] audit: enabled sink "consul-audit"

# Проверка файла audit log
tail -f /var/log/consul/audit.json
# → {"created_at":"2026-09-30T10:00:00.559349128Z","event_type":"audit","payload":{...}}

# Проверка, что ACL включены (требование для audit)
consul acl bootstrap
# → Error enabling ACLs: ACLs already bootstrapped
```

## Структура записи audit log

Каждая запись — JSON-объект. Consul пишет две записи на один HTTP-запрос: `OperationStart` и `OperationComplete`.

### OperationStart

```json
{
  "created_at": "2025-07-31T14:32:38.559349128Z",
  "event_type": "audit",
  "payload": {
    "id": "674891c9-a5a0-e0ba-c738-00cab3c42f16",
    "version": "1",
    "type": "HTTPEvent",
    "timestamp": "2025-07-31T14:32:38.558390378Z",
    "auth": {
      "accessor_id": "00000000-0000-0000-0000-000000000002",
      "description": "Anonymous Token",
      "create_time": "2025-07-30T09:14:52.866798047Z"
    },
    "request": {
      "operation": "GET",
      "endpoint": "/v1/catalog/service/ssh",
      "remote_addr": "127.0.0.1:45110",
      "user_agent": "curl/7.88.1",
      "host": "127.0.0.1:8500"
    },
    "stage": "OperationStart"
  }
}
```

### OperationComplete

```json
{
  "created_at": "2025-07-31T14:32:38.562146462Z",
  "event_type": "audit",
  "payload": {
    "id": "c7d9614e-b110-729a-4c0b-6123f5c341a1",
    "version": "1",
    "type": "HTTPEvent",
    "timestamp": "2025-07-31T14:32:38.561802712Z",
    "auth": {
      "accessor_id": "00000000-0000-0000-0000-000000000002",
      "description": "Anonymous Token",
      "create_time": "2025-07-30T09:14:52.866798047Z"
    },
    "request": {
      "operation": "GET",
      "endpoint": "/v1/catalog/service/ssh",
      "remote_addr": "127.0.0.1:45110",
      "user_agent": "curl/7.88.1",
      "host": "127.0.0.1:8500"
    },
    "response": {
      "status": "200"
    },
    "stage": "OperationComplete"
  }
}
```

### Поля записи

| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `created_at` | string | Время создания записи в audit log (наносекунды, RFC 3339). |
| `event_type` | string | Тип события. Для audit logging всегда `"audit"`. |
| `payload.id` | string | Уникальный идентификатор события. |
| `payload.version` | string | Версия схемы payload. |
| `payload.type` | string | Тип payload. Для HTTP API всегда `"HTTPEvent"`. |
| `payload.timestamp` | string | Время события (наносекунды, RFC 3339). |
| `payload.auth.accessor_id` | string | Accessor ID ACL-токена, использованного в запросе. |
| `payload.auth.description` | string | Описание токена. |
| `payload.auth.create_time` | string | Время создания токена (наносекунды). |
| `payload.request.operation` | string | HTTP-метод (`GET`, `PUT`, `DELETE` и т.д.). |
| `payload.request.endpoint` | string | Эндпоинт HTTP API (`/v1/...`). |
| `payload.request.remote_addr` | string | IP:port клиента. |
| `payload.request.user_agent` | string | User-Agent клиента. |
| `payload.request.host` | string | Host, к которому обратился клиент. |
| `payload.response.status` | string | HTTP-статус ответа (только для `OperationComplete`). |
| `payload.stage` | string | `"OperationStart"` или `"OperationComplete"`. |

## Устранение неполадок

### Audit log не создается

- **Причина:** `audit.enabled = false` или ACL не включены.
- **Решение:** Убедитесь, что ACL загружены (`acl = { enabled = true }`), и audit блок присутствует в конфигурации. После изменения конфигурации выполните полный перезапуск агента.
  ```bash
  # Проверка статуса ACL
  consul acl token self
  # → Token accessor ID: ...
  ```

### Audit log пустой, несмотря на активность

- **Причина:** События генерируются только для HTTP API. RPC-операции между агентами не логируются.
- **Решение:** Убедитесь, что операции выполняются через HTTP API (CLI, UI, curl). Проверьте, что агент, к которому обращаетесь, является целевым для audit sink.

### Audit log растет слишком быстро

- **Причина:** Отсутствует ротация или настроены слишком большие интервалы/размеры.
- **Решение:** Настройте хотя бы один из параметров ротации:
  ```hcl
  rotate_duration = "24h"
  rotate_max_files = 7
  rotate_bytes = 52428800
  ```

### Файл audit log не ротируется

- **Причина:** Не задан ни `rotate_duration`, ни `rotate_bytes`. Оба параметра опциональны по отдельности, но хотя бы один должен быть указан.
- **Решение:** Добавьте один из параметров ротации и перезапустите агент.

### SIEM не получает события

- **Диагностика:** Audit log в Consul Enterprise поддерживает только файловый sink. Для передачи в SIEM используйте:
  - Локальный агент сбора логов (Filebeat, Fluentd, rsyslog), который читает файл audit log и отправляет в SIEM.
  - Направление audit log в stdout и последующий сбор sidecar-ом.
- **Решение:** Проверьте права на файл audit log и работу агента сбора логов.

### Чувствительные данные в логах

- **Проблема:** В поле `payload.request` содержится полный путь эндпоинта и удаленный адрес, но не тело запроса. Audit log не записывает тела запросов и ответов.
- **Решение:** Избегайте передачи секретов в URL-параметрах и путях эндпоинтов, так как они попадают в audit log. Используйте тела запросов для конфиденциальных данных.

## Лучшие практики

- **Обязательно включите audit logging** в production для compliance. Это требование большинства frameworks.
- **ACLs должны быть включены** перед включением audit logging. Без ACL audit не имеет смысла, так как некому аутентифицировать запросы.
- **Ротация:** Настраивайте хотя бы один из параметров ротации (`rotate_duration`, `rotate_bytes`) для предотвращения заполнения диска.
- **Права на файлы:** Используйте параметр `mode` для ограничения доступа к audit log (например, `"0600"`).
- **Централизация:** Используйте локальный агент сбора логов (Filebeat, Fluentd, rsyslog) для чтения файла audit log и отправки в SIEM (ELK, Splunk, OpenSearch).
- **Мониторинг:** Настройте алерты на отсутствие записей в audit log в течение более 15 минут — это индикатор проблем с доставкой или отказом агента.
- **Короткоживущие токены:** Используйте короткоживущие токены для ACL операций; audit log фиксирует их создание и удаление, что упрощает расследование инцидентов.
- **Не полагайтесь на RPC-логи:** Audit log не покрывает внутреннее взаимодействие агентов. Для полной картины комбинируйте audit log с обычными логами Consul и метриками.
- **Не пропускайте перезапуск:** Изменения audit-конфигурации требуют полного перезапуска агентов. Планируйте окно обслуживания.

## Граничные случаи

- **Multi-DC:** Audit log создается на каждом агенте независимо. Для корреляции событий между датацентрами используйте centralized SIEM с временными метками и полем `payload.auth.accessor_id`.
- **High availability:** При failover лидера audit log продолжает писаться на новом лидере. События не теряются, если sink использует `best-effort` доставку на локальный файл.
- **Performance overhead:** Audit logging добавляет незначительный overhead на HTTP API-операции. На высоконагруженных кластерах тестируйте производительность при включенном audit.
- **Encryption at rest:** Audit log не шифруется автоматически. Используйте filesystem encryption (LUKS, BitLocker) или отправляйте файлы в защищенный SIEM.
- **Compliance и хранение:** Для юридически значимого хранения используйте внешний SIEM с immutable storage (WORM, S3 Object Lock). Локальные файлы audit log подлежат ротации и не гарантируют неизменность.
- **RPC операции не покрываются:** Внутренние операции Consul (gossip, Raft replication, сервер-серверное взаимодействие) не попадают в audit log. Для их аудита используйте системные логи агента и network-level instrumentation.
- **Config entries:** Запись config entries через HTTP API логируется. Изменения, примененные автоматическими системами (например, Terraform), видны в audit log с соответствующим `user_agent`.

## Дополнительная информация

- **[Audit Logging (Enterprise)](https://developer.hashicorp.com/consul/docs/monitor/log/audit)** — официальная документация по включению и настройке audit logging.
- **[Agent log configuration reference](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/log#audit)** — справочник параметров конфигурации audit sinks.
- **[Consul Telemetry](./consul_telemetry.md)** — метрики и диагностика Consul, дополняющие audit log для observability.
- **[Consul ACLs](./consul_acl.md)** — настройка ACL, которая является обязательным условием для audit logging.
- **[Consul Logs and Telemetry](https://developer.hashicorp.com/consul/docs/agent/telemetry)** — общая конфигурация логирования агента.
- **[Splunk Add-on for Consul](https://splunkbase.splunk.com/app/5021/)** — интеграция Consul с Splunk (для сбора обычных логов Consul, audit log требует отдельного набора ingest через файловый мониторинг).
