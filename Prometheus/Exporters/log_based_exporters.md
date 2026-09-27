# Log-based Exporters: mtail и grok_exporter

## Определения

**Log-based Exporter** — класс экспортеров, которые парсят текстовые логи и генерируют из них метрики Prometheus. Используются, когда целевая система не предоставляет метрики нативно или через отдельный экспортер, но генерирует логи с полезной статистикой.

*   **mtail** — компилятор регулярных выражений для извлечения метрик из логов. Работает как демон, постоянно читающий файлы логов. Поддерживает counter, gauge, histogram, timer.
*   **grok_exporter** — экспортер, использующий паттерны Grok (аналогичные Logstash) для парсинга логов в метрики. Основан на библиотеке `grok` и поддерживает сложные многострочные паттерны.

**См. также:** [Textfile Collector](./extensibility/textfile_collector.md), [ELK Stack](../../../ELK_Stack/elk_overview.md).

## Предварительные требования

*   **Доступ к файлам логов:** mtail/grok_exporter должен иметь доступ на чтение к файлам логов (обычно `/var/log/`).
*   **Формат логов:** Структурированные или semi-структурированные логи (JSON, syslog, Apache/Nginx combined).
*   **Ресурсы:** ~50m CPU, 64Mi RAM на mtail (зависит от количества правил). grok_exporter потребляет больше CPU при сложных паттернах.

## Основные концепции

### Сравнение mtail vs grok_exporter vs Textfile Collector

| Характеристика | mtail | grok_exporter | Textfile Collector |
|:---|:---|:---|:---|
| **Источник данных** | Файлы логов (tail -F) | Файлы логов | Файлы `.prom` (script output) |
| **Парсинг** | Регулярные выражения | Grok-паттерны | Текстовый формат Prometheus |
| **Сложность** | Средняя | Низкая (готовые паттерны) | Низкая |
| **Производительность** | Высокая (нативный Go) | Средняя (Grok сложнее regex) | Высокая (простое чтение) |
| **Multi-line** | Ограниченно | Да (grok-паттерны) | Нет |
| **Когда использовать** | Строковые логи, simple patterns | Сложные многострочные логи | Простые метрики из скриптов |

### mtail

**Принцип работы:** mtail запускается как демон, читает файлы логов через `tail -F` и применяет регулярные выражения. Совпадения увеличивают/уменьшают счетчики или задают значения gauge.

**Язык mtail:**

```
# Счётчик запросов по HTTP-кодам
counter http_requests_total by status

/HTTP\/\d+\.\d+" (\d+)/ {
    http_requests_total[$1]++
}

# Gauge текущей длины очереди
gauge queue_length

/^queue_length=(\d+)$/ {
    queue_length = $1
}

# Гистограмма длительности запросов
histogram request_duration_seconds buckets 0.01, 0.05, 0.1, 0.5, 1, 5

/^request took (\d+\.\d+)s$/ {
    request_duration_seconds = $1
}
```

**Запуск:**

```bash
mtail \
  --progs /etc/mtail/rules/ \
  --logs /var/log/myapp/*.log \
  --logs /var/log/nginx/access.log \
  --address 0.0.0.0:9116 \
  --one_shot  # для тестирования
```

### grok_exporter

**Паттерны Grok** — это именованные комбинации регулярных выражений, аналогичные Logstash:

```
# Grok-паттерн для Apache combined log
%{COMBINEDAPACHELOG}

# Grok-паттерн для Nginx
%{IPORHOST:remote_addr} - %{USER:remote_user} \[%{HTTPDATE:time_local}\] "%{WORD:method} %{URIPATHPARAM:request} HTTP/%{NUMBER:http_version}" %{NUMBER:status} %{NUMBER:body_bytes_sent} "%{DATA:http_referer}" "%{DATA:http_user_agent}"
```

**Конфигурация grok_exporter:**

```yaml
# /etc/grok_exporter/config.yml
global:
  config_version: 2
  retention: 1h

input:
  type: file
  path: /var/log/nginx/access.log
  readall: false

metrics:
  - name: nginx_requests_total
    type: counter
    help: "Total HTTP requests"
    match: '%{COMBINEDAPACHELOG}'
    labels:
      method: "{{ .method }}"
      status: "{{ .status }}"
      host: "{{ .request_host }}"

  - name: nginx_response_size_bytes
    type: counter
    help: "Response body size"
    match: '%{COMBINEDAPACHELOG}'
    labels:
      status: "{{ .status }}"

  - name: nginx_request_duration_seconds
    type: histogram
    help: "Request duration"
    buckets: [0.01, 0.05, 0.1, 0.5, 1, 5]
    match: '%{COMBINEDAPACHELOG}'

server:
  host: 0.0.0.0
  port: 9144
```

**Запуск:**

```bash
grok_exporter \
  --config /etc/grok_exporter/config.yml
```

## Практические сценарии

### mtail: Мониторинг уровня ошибок в логах приложения

```
# /etc/mtail/rules/app_errors.mtail

counter app_errors_total by level

# Подсчёт ERROR и WARN
/^\[(ERROR|WARN)\]/ {
    app_errors_total[$1]++
}

# Подсчёт конкретных ошибок
/Exception: (.+)/ {
    app_errors_total["exception"]++
}

# Подсчёт OOM
/out of memory/i {
    app_errors_total["oom"]++
}

# Gauge: количество активных соединений из логов
gauge active_connections

/^Active connections: (\d+)$/ {
    active_connections = $1
}
```

### grok_exporter: Мониторинг PostgreSQL slow query log

```yaml
global:
  config_version: 2
  retention: 1h

input:
  type: file
  path: /var/log/postgresql/postgresql-16-main.log
  readall: false

metrics:
  - name: pg_slow_query_total
    type: counter
    help: "Slow queries detected in log"
    match: '^%{TIMESTAMP_ISO8601:log_time}.*duration: %{NUMBER:duration_ms:float} ms\s+statement: %{GREEDYDATA:statement}$'
    labels:
      database: "{{ .database }}"

  - name: pg_slow_query_duration_seconds
    type: histogram
    help: "Slow query duration"
    buckets: [0.1, 0.5, 1, 5, 10, 30, 60]
    match: '^%{TIMESTAMP_ISO8601:log_time}.*duration: %{NUMBER:duration_ms:float} ms\s+statement: %{GREEDYDATA:statement}$'

  - name: pg_connection_error_total
    type: counter
    help: "Connection errors"
    match: 'FATAL: too many connections'
```

### grok_exporter: Мониторинг Redis slowlog

```yaml
input:
  type: file
  path: /var/log/redis/redis-server.log

metrics:
  - name: redis_slowlog_entries_total
    type: counter
    match: '^\[%{NUMBER:timestamp}\] %{WORD:level} %{GREEDYDATA:message}$'
    labels:
      level: "{{ .level }}"

  - name: redis_aof_rewrite_total
    type: counter
    match: 'Background AOF rewrite'
```

### Systemd service

```ini
[Unit]
Description=mtail log exporter
After=network.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/mtail \
  --progs /etc/mtail/rules/ \
  --logs /var/log/myapp/*.log \
  --address 0.0.0.0:9116
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

### Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'mtail'
    static_configs:
      - targets: ['app-host:9116']
    scrape_interval: 15s

  - job_name: 'grok_exporter'
    static_configs:
      - targets: ['app-host:9144']
    scrape_interval: 30s
```

## Алертинг

```yaml
groups:
  - name: log_based_alerts
    rules:
      # Высокий уровень ошибок
      - alert: HighErrorRate
        expr: rate(app_errors_total{level="ERROR"}[5m]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень ошибок в логах"
          description: "{{ $value }}/сек ошибок."

      # OOM detected
      - alert: OOMDetected
        expr: increase(app_errors_total{level="oom"}[1h]) > 0
        labels:
          severity: critical
        annotations:
          summary: "Обнаружен OOM в логах"

      # Медленные запросы PostgreSQL
      - alert: PgSlowQueries
        expr: rate(pg_slow_query_total[5m]) > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "PostgreSQL генерирует slow queries"
          description: "{{ $value }}/сек."

      # Много ошибок подключения
      - alert: PgConnectionErrors
        expr: increase(pg_connection_error_total[1h]) > 10
        labels:
          severity: warning
        annotations:
          summary: "Много ошибок подключения PostgreSQL"
```

## Типичные ошибки и устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| mtail не читает логи | Нет прав доступа к файлу | Проверьте права: `chmod +r /var/log/app.log` |
| grok_exporter не парсит | Несоответствие паттерна формату лога | Протестируйте паттерн на sample: `grok_exporter --config config.yml --test "sample log line"` |
| Метрики не обновляются | Файл лога не ротируется или mtail не видит новые строки | Убедитесь, что mtail использует `tail -F` (follow) |
| Высокая нагрузка CPU | Слишком много правил или сложные regex | Упростите паттерны, уменьшите количество правил |
| Потеря данных при рестарте | mtail не помнит позицию в файле | Используйте `--one_shot=false` и храните позицию в файле |

## Лучшие практики

1.  **Приоритет:** Если есть нативный экспортер — используйте его. Log-based экспортеры — крайний вариант.
2.  **Лимиты:** Ограничивайте количество правил mtail (<100) и сложность grok-паттернов.
3.  **Тестирование:** Всегда проверяйте паттерны на реальных строках логов перед деплоем.
4.  **Ротация логов:** Убедитесь, что mtail/grok_exporter корректно работает с `logrotate` (через `copytruncate` или `postrotate` с перезапуском процесса).
5.  **Кардинальность:** Избегайте использования полей логов с уникальными значениями (session ID, trace ID) как лейблов — это создаст взрыв кардинальности.
6.  **Альтернатива — OpenTelemetry Collector:** Для сложных сценариев с multi-line логами и трассировкой рассмотрите OTel Collector с процессорами `transform` и `attributes`.

## См. также

*   [Textfile Collector](./extensibility/textfile_collector.md) — проще для простых метрик
*   [ELK Stack](../../../ELK_Stack/elk_overview.md) — полный стек для логов
*   [OpenTelemetry Overview](../../../OpenTelemetry/opentelemetry_overview.md) — современная альтернатива
*   [Обзор экспортеров](./overview.md) — принципы выбора экспортера
