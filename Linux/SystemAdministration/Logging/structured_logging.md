# Структурированное логирование (Structured Logging)

## Определения

**Структурированное логирование** — метод записи логов в машиночитаемом формате (обычно JSON), где каждое поле имеет определённый тип и имя. В отличие от plain text логов (`Jan 15 10:23:45 web-01 nginx[1234]: GET /api 200 1234`), структурированные логи позволяют извлекать поля без регулярных выражений, обеспечивая эффективный поиск и агрегацию.

**Почему это важно:**
- Агенты (Vector, Fluent Bit) парсят JSON без regex — экономия CPU и исключение ошибок парсинга
- SIEM и поисковые системы (Elasticsearch, Loki) индексируют конкретные поля
- Корреляция между сервисами через `trace_id`, `request_id`
- Автоматизация: алерты на конкретные значения полей, а не на текстовые совпадения

## Базовые концепции

### Форматы логов

| Формат | Пример | Парсинг | Применение |
|:---|:---|:---|:---|
| **Plain text** | `2026-01-15 ERROR Failed to connect` | Regex (ненадёжно) | Legacy, скрипты |
| **JSON** | `{"timestamp":"...","level":"error","msg":"Failed"}` | Нативный | Production (рекомендуется) |
| **logfmt** | `timestamp=... level=error msg="Failed"` | key=value | Go-приложения |
| **CSV** | `2026-01-15,error,Failed` | Позиционный | Редко |

### Обязательные поля (Recommended Schema)

```json
{
  "timestamp": "2026-01-15T10:23:45.123Z",
  "level": "error",
  "service": "payment-api",
  "message": "Failed to connect to database",
  "error": "connection_timeout",
  "duration_ms": 5000,
  "trace_id": "abc123def456",
  "request_id": "req-789",
  "host": "web-01",
  "env": "production"
}
```

| Поле | Тип | Описание | Обязательно |
|:---|:---|:---|:---|
| `timestamp` | ISO 8601 | Время события (UTC) | Да |
| `level` | string | Уровень: debug/info/warning/error/critical | Да |
| `service` | string | Имя сервиса/микросервиса | Да |
| `message` | string | Текст сообщения | Да |
| `error` | string | Тип ошибки (если применимо) | Нет |
| `trace_id` | string | ID трассировки (OpenTelemetry/Jaeger) | Рекомендуется |
| `request_id` | string | ID запроса (для корреляции) | Рекомендуется |
| `host` | string | Имя хоста | Автоматически |
| `env` | string | Окружение (dev/staging/prod) | Рекомендуется |

### Методы вывода JSON-логов

| Метод | Язык/Фреймворк | Пример |
|:---|:---|:---|
| **Стандартный вывод** | Python (python-json-logger) | `stdout` → journald → агент |
| **Библиотека** | Go (zerolog, zap) | `logger.Info().Str("key","val").Msg("text")` |
| **Конфигурация** | Java (logback-json) | `<encoder class="net.logstash.logback.encoder.LogstashEncoder"/>` |
| **Встроенный** | Nginx (ngx_http_log_module) | `log_format json escape=json '{...}'` |
| **Встроенный** | PostgreSQL | `log_line_prefix = '%m [%p] %q%u@%d '` → JSON через扩展у |

## Практические сценарии

### Сценарий 1: Python (structlog)

```python
# Установка: pip install structlog python-json-logger

import structlog
import logging
import sys

# Настройка structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
)

logger = structlog.get_logger()

# Использование
logger.info("payment_processed", amount=100.50, currency="USD", user_id="u-123")
# → {"event":"payment_processed","amount":100.50,"currency":"USD","user_id":"u-123","level":"info","timestamp":"2026-01-15T10:23:45Z"}

logger.error("payment_failed", error="insufficient_funds", amount=500, user_id="u-456")
# → {"event":"payment_failed","error":"insufficient_funds","amount":500,"user_id":"u-456","level":"error","timestamp":"2026-01-15T10:23:45Z"}
```

### Сценарий 2: Go (zerolog)

```go
package main

import (
    "os"
    "github.com/rs/zerolog"
    "github.com/rs/zerolog/log"
)

func main() {
    // Настройка JSON-вывода
    log.Logger = zerolog.New(zerolog.ConsoleWriter{Out: os.Stderr}).
        With().Timestamp().Logger()

    // Или чистый JSON
    log.Logger = zerolog.New(os.Stdout).With().Timestamp().Logger()

    // Использование
    log.Info().
        Str("service", "api-gateway").
        Str("method", "GET").
        Str("path", "/api/users").
        Int("status", 200).
        Dur("latency", 45*time.Millisecond).
        Msg("request completed")

    log.Error().
        Str("service", "payment").
        Str("error", "connection_timeout").
        Str("trace_id", "abc123").
        Msg("failed to process payment")
}
```

### Сценарий 3: Java (Logback JSON)

```xml
<!-- logback.xml -->
<configuration>
    <appender name="JSON" class="ch.qos.logback.core.ConsoleAppender">
        <encoder class="net.logstash.logback.encoder.LogstashEncoder">
            <fieldNames>
                <timestamp>[ignore]</timestamp>
                <version>[ignore]</version>
            </fieldNames>
            <includeMdcKeyName>trace_id</includeMdcKeyName>
            <includeMdcKeyName>request_id</includeMdcKeyName>
        </encoder>
    </appender>

    <root level="INFO">
        <appender-ref ref="JSON" />
    </root>
</configuration>
```

```xml
<!-- pom.xml -->
<dependency>
    <groupId>net.logstash.logback</groupId>
    <artifactId>logstash-logback-encoder</artifactId>
    <version>7.4</version>
</dependency>
```

### Сценарий 4: Nginx JSON-логи

```nginx
# /etc/nginx/nginx.conf

http {
    log_format json_combined escape=json
        '{'
            '"time_local":"$time_iso8601",'
            '"remote_addr":"$remote_addr",'
            '"request_method":"$request_method",'
            '"request_uri":"$request_uri",'
            '"status":$status,'
            '"body_bytes_sent":$body_bytes_sent,'
            '"request_time":$request_time,'
            '"upstream_response_time":"$upstream_response_time",'
            '"http_user_agent":"$http_user_agent",'
            '"http_referer":"$http_referer",'
            '"server_name":"$server_name",'
            '"request_id":"$request_id"'
        '}';

    access_log /var/log/nginx/access.log json_combined;
}
```

### Сценарий 5: Structured logging в shell-скриптах

```bash
# Утилита для JSON-логов из bash
log_json() {
    local level="$1"
    local msg="$2"
    shift 2
    echo "{\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)\",\"level\":\"${level}\",\"service\":\"$(hostname)\",\"message\":\"${msg}\",\"$@\"}" | logger -t "$(basename $0)"
}

# Использование
log_json "info" "backup started" "backup_type=full"
log_json "error" "backup failed" "error_code=127" "path=/backup"
```

## Интеграция с агентами

### Vector

```yaml
# Vector автоматически парсит JSON-логи
sources:
  app:
    type: file
    include: ["/var/log/app/*.log"]

transforms:
  parse_json:
    type: remap
    inputs: [app]
    source: |
      . = parse_json!(.message)

sinks:
  loki:
    type: loki
    inputs: [parse_json]
    labels:
      service: .service
      level: .level
```

### Fluent Bit

```ini
[INPUT]
    Name    tail
    Tag     app.*
    Path    /var/log/app/*.log
    Parser  json

[OUTPUT]
    Name    loki
    Match   app.*
    Labels  service=$service, level=$level
```

### rsyslog

```conf
# Парсинг JSON из imfile
module(load="mmjsonparse")
if $programname == 'myapp' then {
    action(type="mmjsonparse")
    action(type="omfile" file="/var/log/rsyslog/myapp-parsed.log")
}
```

## Диагностика

### Проверка валидности JSON-логов

```bash
# Проверка всех строк в файле
cat /var/log/app/app.log | jq . > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Невалидный JSON в логах"
    # Найти невалидные строки
    cat -n /var/log/app/app.log | while read line; do
        echo "$line" | cut -f2- | jq . > /dev/null 2>&1 || echo "INVALID: $line"
    done
fi

# Поиск строк без JSON
grep -v '^{.*}$' /var/log/app/app.log | head -5
```

## Дополнительная информация

### Лучшие практики

1. **JSON по умолчанию** — используйте JSON для всех production-сервисов.
2. **Единый набор полей** — `timestamp`, `level`, `service`, `message` обязательны.
3. **trace_id / request_id** — добавляйте для сквозной трассировки.
4. **Не дублируйте поля** — `host`, `env` добавляйте на уровне агента, а не приложения.
5. **Избегайте вложенных JSON-строк** — `{"data": "{\"key\":\"val\"}"}` — антипаттерн.
6. **Экранируйте спецсимволы** — `escape=json` в Nginx, `json.dumps()` в Python.
7. **Размер строки** — следите за `LineMax` в journald (по умолчанию 48K).
8. **Тестируйте парсинг** — убедитесь, что агент корректно извлекает поля.

### См. также

- [Обзор системы логирования](./logging_overview.md)
- [Logs Deep Dive](../../../Concepts/Observability_and_Monitoring/logs_deep_dive.md)
- [Vector VRL Language](../../../Vector/vrl_language.md)
