# Structured Logging и анализ для веб-производительности

## Определения

**Structured Logging** — подход к логированию, при котором каждое событие записывается в виде структурированного объекта (обычно JSON) с явными полями, а не как свободный текст. Позволяет автоматизировать парсинг, поиск и корреляцию.

**Access Log** — журнал всех запросов, обработанных веб-сервером. В контексте производительности содержит TTFB, размер ответа, HTTP-код, upstream response time.

**Error Log** — журнал ошибок и предупреждений веб-сервера. Критичен для диагностики проблем производительности: таймауты, unhealthy upstream, кэш-промахи.

**Log Format** — шаблон, определяющий, какие поля записываются в лог. В Nginx/Angie задаётся директивой `log_format`.

**Correlation ID** — уникальный идентификатор запроса, propagating через все компоненты системы (прокси → бэкенд → БД). Позволяет сопоставить логи разных сервисов при расследовании инцидента.

**Log Rotation** — процесс архивации и очистки старых лог-файлов. В production без ротации логи заполнят диск за часы.

## Основные концепции

### Почему structured logging критичен для SRE

При расследовании инцидента производительности (например, рост TTFB на 500 мс) SRE использует логи для:

1. **Поиска аномалий:** Фильтрация по `status >= 500` или `upstream_response_time > 1s`.
2. **Корреляции:** Сопоставление spike в access log с error log (например, `upstream timed out`).
3. **Trend analysis:** Построение графиков TTFB, 5xx rate, Cache Hit Ratio за время.
4. **Root cause:** Отслеживание Correlation ID через все сервисы.

### Поля для мониторинга производительности

Обязательные поля в access log для performance-oriented SRE:

| Поле | Переменная Nginx/Angie | Назначение |
| :--- | :--- | :--- |
| **Timestamp** | `$time_iso8601` | Временная метка для корреляции |
| **Remote Addr** | `$remote_addr` | Геолокация, аномалии |
| **Request** | `$request` | Endpoint, метод |
| **Status** | `$status` | HTTP-код (5xx = проблема) |
| **Body Bytes Sent** | `$body_bytes_sent` | Размер ответа |
| **Request Time** | `$request_time` | Общее время обработки запроса |
| **Upstream Response Time** | `$upstream_response_time` | Время ответа бэкенда (TTFB) |
| **Upstream Status** | `$upstream_status` | HTTP-код от бэкенда |
| **Cache Status** | `$upstream_cache_status` | HIT/MISS/STALE |
| **Connection** | `$connection` | ID соединения для Correlation |
| **Request ID** | `$request_id` | Correlation ID |

### JSON log format

```nginx
log_format performance escape=json '{
  "timestamp": "$time_iso8601",
  "remote_addr": "$remote_addr",
  "request": "$request",
  "status": "$status",
  "body_bytes_sent": "$body_bytes_sent",
  "request_time": "$request_time",
  "upstream_response_time": "$upstream_response_time",
  "upstream_status": "$upstream_status",
  "cache_status": "$upstream_cache_status",
  "connection": "$connection",
  "request_id": "$request_id",
  "ssl_protocol": "$ssl_protocol",
  "ssl_cipher": "$ssl_cipher"
}';
```

## Практические сценарии

### Сценарий 1: Настройка performance-oriented access log

```nginx
http {
    # Генерация Request ID для Correlation
    log_format performance escape=json '{
      "timestamp": "$time_iso8601",
      "remote_addr": "$remote_addr",
      "request": "$request",
      "status": "$status",
      "body_bytes_sent": "$body_bytes_sent",
      "request_time": "$request_time",
      "upstream_response_time": "$upstream_response_time",
      "upstream_status": "$upstream_status",
      "cache_status": "$upstream_cache_status",
      "connection": "$connection",
      "request_id": "$request_id",
      "ssl_protocol": "$ssl_protocol",
      "ssl_cipher": "$ssl_cipher"
    }';

    # Отправка логов в stdout (для Docker/Kubernetes)
    access_log /dev/stdout performance;

    # ИЛИ: отправка в syslog (для centralized logging)
    # access_log syslog:server=127.0.0.1:514 performance;

    server {
        location / {
            proxy_pass http://backend;
            proxy_set_header X-Request-ID $request_id;
        }
    }
}
```

### Сценарий 2: Анализ логов для диагностики TTFB

```bash
# Поиск запросов с TTFB > 500 мс
jq -r 'select(.upstream_response_time > 0.5) | "\(.timestamp) \(.request) \(.upstream_response_time)s"' /var/log/nginx/access.json | tail -20

# Анализ распределения TTFB
jq -r '.upstream_response_time' /var/log/nginx/access.json | sort -n | uniq -c | awk 'NR==1{min=$1} NR==N{max=$1} END{print "Min:", min, "Max:", max}'

# Поиск correlation: slow requests + error log
grep "upstream timed out" /var/log/nginx/error.log | tail -20
```

### Сценарий 3: Корреляция с бэкендом

```nginx
# Прокси передаёт Correlation ID бэкенду
location / {
    proxy_pass http://backend;
    proxy_set_header X-Request-ID $request_id;
    proxy_set_header X-Real-IP $remote_addr;
}

# Бэкенд возвращает Correlation ID в заголовке
# (при поддержке на стороне приложения)
```

```bash
# Поиск всех логов по Correlation ID
REQUEST_ID="abc123"
grep "$REQUEST_ID" /var/log/nginx/access.json
grep "$REQUEST_ID" /var/log/backend/app.log
```

### Сценарий 4: Мониторинг через Loki/Promtail

```yaml
# promtail-config.yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 9096

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: nginx
    static_configs:
      - targets:
          - localhost
        labels:
          job: nginx
          __path__: /var/log/nginx/access.json
```

```logql
# Запрос: 95-й перцентиль TTFB за 5 минут
quantile_over_time(upstream_response_time, 0.95, /var/log/nginx/access.json[5m])
```

## Операции и команды

### Валидация логов

```bash
# Проверка синтаксиса JSON
jq . /var/log/nginx/access.json > /dev/null && echo "OK" || echo "INVALID JSON"

# Статистика по HTTP-кодам
jq -r '.status' /var/log/nginx/access.json | sort | uniq -c | sort -rn

# Средний TTFB по endpoint
jq -r '[.request, .upstream_response_time] | @tsv' /var/log/nginx/access.json | awk '{a[$1]+=$2; n[$1]++} END {for (i in a) print i, a[i]/n[i]}'
```

### Ротация логов

```bash
# logrotate (автоматически в Debian/Ubuntu)
cat /etc/logrotate.d/nginx

# Или вручную
mv /var/log/nginx/access.json /var/log/nginx/access.json.1
kill -USR1 $(cat /run/nginx.pid)
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Логи в текстовом формате** | Невозможно парсить jq | `cat /var/log/nginx/access.log | head` | Переключиться на `escape=json` |
| **Отсутствует Correlation ID** | Нельзя сопоставить логи прокси и бэкенда | `grep -c request_id` | Добавить `log_format` с `$request_id` |
| **Логи теряются** | Пропуски в последовательности | Сравнить с access_log счётчиком | Увеличить буфер, проверить disk I/O |
| **Большой размер логов** | Диск заполнен | `du -sh /var/log/nginx/` | Настроить logrotate, компрессию |
| **Нет upstream_response_time** | Нельзя диагностировать TTFB | `grep upstream_response_time` | Добавить в `log_format` |

## Рекомендации

### Базовые правила

1. **Используйте JSON формат:** `escape=json` в `log_format`. Избегайте текстовых форматов для production.
2. **Добавьте обязательные поля:** `$request_time`, `$upstream_response_time`, `$upstream_cache_status`, `$request_id`.
3. **Настройте ротацию:** `maxsize 1G`, `rotate 7`, `compress`.
4. **Централизуйте логи:** Отправляйте в Loki/ELK через stdout, syslog или Filebeat.
5. **Мониторьте качество логов:** Алерт при падении объёма access log на 50% (возможно, проблема с записью).

### Для DevOps/SRE/SysAdmin

- **Dashboard:** Графики 5xx rate, P95 TTFB, Cache Hit Ratio из access log.
- **Alerting:** Алерт при росте 5xx >1% или TTFB P95 >500 мс в течение 5 минут.
- **Runbook:** Для каждого алерта — шаги поиска по логам, корреляции с error log, escalation.

## Дополнительная информация

### См. также

- [Мониторинг кэширования в Nginx/Angie](../../WebServers/Nginx/Performance/Caching/monitoring.md) — JSON-логирование для аудита кэша.
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — корреляция keepalive-пула с TTFB в логах.
- [Circuit Breaker и Degradation](./circuit_breaker_and_degradation.md) — анализ 5xx в логах.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — мониторинг reload через логи.

### RFC и спецификации

- **RFC 5424** — Syslog Protocol.
- **RFC 9590** — JSON Logging.
