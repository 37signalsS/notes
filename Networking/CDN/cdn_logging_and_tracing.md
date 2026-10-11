# CDN — Логирование, Tracing и Observability

## Определения

- **Structured Logging (Структурированное логирование)**: Формат логов в виде JSON с фиксированными полями, обеспечивающий удобство парсинга и анализа в ELK, Loki, Grafana.
- **CF-Ray**: Уникальный идентификатор запроса в Cloudflare. Формат: `{hex_timestamp}-{datacenter_id}`. Используется для трассировки запроса через все PoP CDN.
- **Server-Timing (RFC 7231)**: HTTP-заголовок, предоставляющий тайминги этапов обработки запроса. Каждый CDN добавляет свои метрики: `edge;dur=3, origin;dur=45`.
- **traceparent (W3C Trace Context)**: Стандартный заголовок распределённого трейсинга (RFC 8338). Содержит `trace-id`, `parent-id` и `trace-flags`. Поддерживается Cloudflare, Fastly, Akamai.
- **CDN Access Logs**: Логи HTTP-запросов, обработанных CDN. Содержат URL, статус, размер, время, IP клиента, User-Agent, Referer, Cache-Status.
- **Logpush (Cloudflare)**: Автоматическая доставка логов CDN в хранилище (S3, GCS, R2) или аналитические системы (Datadog, Splunk, ELK).
- **Edge Logs (Fastly)**: Реалтайм-логи с edge-узлов. Доступны через API или Stream Logs (webhook).
- **Real User Monitoring (RUM)**: Метод сбора метрик производительности от реальных пользователей (TTFB, LCP, INP, CLS) через браузерный JavaScript.
- **Synthetic Monitoring (Синтетический мониторинг)**: Периодические HTTP-запросы из разных PoP для измерения TTFB, доступности и SSL-статуса.
- **Distributed Tracing (Распределённый трейсинг)**: Метод отслеживания запроса через все компоненты системы (CDN → Origin → Database) с использованием trace-id.

---

## Теория

### Архитектура логирования CDN

```
[Клиент] → [CDN Edge] → [Origin] → [Database]
                ↓              ↓
         [CDN Logs]     [Application Logs]
                ↓              ↓
         [Log Storage]   [APM/Jaeger]
         (S3/R2/GCS)         ↓
                ↓         [Dashboard]
         [ELK/Loki]
                ↓
         [Grafana/Datadog]
```

**Уровни логирования:**

| Уровень | Описание | Пример |
| :--- | :--- | :--- |
| **Access Logs** | Каждый HTTP-запрос | URL, статус, размер, IP, User-Agent |
| **Error Logs** | Ошибки обработки | 5xx, timeout, origin connection refused |
| **Security Logs** | События безопасности | Blocked requests, rate limiting, WAF triggers |
| **Analytics** | Агрегированная статистика |_requests, bandwidth, cache hit ratio |

### Трассировка через CDN

**Цепочка трассировки:**
```
Клиент → CDN Edge (span 1) → Origin Shield (span 2) → Origin (span 3) → DB (span 4)
```

**W3C Trace Context (traceparent):**
```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             ^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^  ^^
           version        trace-id                  parent-id     flags
```

- **trace-id**: 16 байт (128 бит), уникальный для всего запроса.
- **parent-id**: 8 байт (64 бит), идентификатор текущего span.
- **flags**: `01` = sampled (запрос трейсится), `00` = not sampled.

**Cloudflare:**
- `cf-ray`: `{hex_timestamp}-{dc_id}` (например, `8a1b2c3d4e5f-LAX`).
- `cf-connecting-ip`: Реальный IP клиента.
- `cf-ipcountry`: Код страны клиента (ISO 3166-1).
- `cf-ray`: Автоматически добавляется к каждому ответу.

**Fastly:**
- `x-request-id`: Уникальный ID запроса.
- `x-served-by`: ID PoP, обслужившего запрос.
- `x-cache`: HIT/MISS/REFRESHSTALE.

### Метрики для мониторинга CDN

| Метрика | Источник | Описание | Целевое значение |
| :--- | :--- | :--- | :--- |
| **TTFB (Time To First Byte)** | `Server-Timing` | Время до первого байта | <50 мс (edge), <200 мс (origin) |
| **Cache Hit Ratio** | CDN Analytics | Процент HIT из общего числа | >98% (статика) |
| **Error Rate (5xx)** | CDN Logs | Доля ошибок | <0.01% |
| **Origin Latency** | `Server-Timing` | Задержка ответа Origin | <200 мс |
| **Edge Latency** | `Server-Timing` | Задержка обработки на Edge | <5 мс |
| **Bandwidth** | CDN Analytics | Потребление Egress | Мониторинг роста |
| **RPS (Requests per Second)** | CDN Analytics | Количество запросов в секунду | Мониторинг пиков |

---

## Практика

### Cloudflare: Настройка логирования

```bash
# Включение Logpush в S3
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/logpush/jobs" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "cdn-logs",
    "destination_conf": "s3://cdn-logs-bucket?region=us-east-1",
    "logpull_options": "fields=ClientIP,ClientRequestHost,ClientRequestMethod,ClientRequestURI,EdgeEndTimestamp,EdgeResponseBytes,EdgeResponseCode,EdgeResponseContentType,RayID,CacheCacheStatus,CacheResponseBytes&timestamps=rfc3339",
    "enabled": true
  }'
# → {"result":{"id":1,...}}

# Включение Logpush в Datadog
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/logpush/jobs" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "cdn-logs-datadog",
    "destination_conf": "datadog://http-intake.logs.datadoghq.com/v1/input?ddsource=cloudflare&ddtags=env:production",
    "logpull_options": "fields=ClientIP,ClientRequestHost,EdgeResponseCode,RayID,CacheCacheStatus",
    "enabled": true
  }'
```

**Поля логов Cloudflare (доступные через Logpush):**

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `ClientIP` | IP клиента | `203.0.113.10` |
| `ClientRequestHost` | Hostname запроса | `example.com` |
| `ClientRequestMethod` | HTTP-метод | `GET` |
| `ClientRequestURI` | URI запроса | `/api/products?limit=10` |
| `EdgeResponseCode` | HTTP-статус ответа CDN | `200` |
| `EdgeResponseBytes` | Размер ответа (байты) | `15432` |
| `CacheCacheStatus` | Статус кэша | `hit`, `miss`, `bypass` |
| `RayID` | Уникальный ID запроса | `8a1b2c3d4e5f` |
| `EdgeEndTimestamp` | Время завершения | `2026-08-25T10:00:00Z` |
| `ClientRequestProtocol` | Версия HTTP | `HTTP/2` |
| `ClientASNNumber` | ASN клиента | `13335` |
| `ClientCountryName` | Страна клиента | `US` |

### Fastly: Stream Logs

```bash
# Настройка Stream Logs в Elasticsearch
curl -X POST "https://api.fastly.com/service/{service_id}/version/{version}/logging/elasticsearch" \
  -H "Fastly-Key: {api_token}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "cdn-logs-es",
    "url": "https://elasticsearch.example.com:9243",
    "index": "cdn-logs-%Y-%m-%d",
    "format_version": "1",
    "tls_hostname": "elasticsearch.example.com",
    "request_max_bytes": 0,
    "response_condition": "",
    "name_condition": "",
    "content_type": "application/json",
    "placement": "none"
  }'

# Stream Logs в webhook (реалтайм)
curl -X POST "https://api.fastly.com/service/{service_id}/version/{version}/logging/http" \
  -H "Fastly-Key: {api_token}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "stream-logs",
    "url": "https://logs.example.com/ingest",
    "method": "POST",
    "content_type": "application/json",
    "header_name": "Authorization",
    "header_value": "Bearer {log_token}",
    "format": "{\"timestamp\":\"%t\",\"client\":\"%h\",\"method\":\"%m\",\"uri\":\"%U\",\"status\":\"%s\",\"bytes\":\"%b\",\"cache\":\"%{cache.status}V\",\"request_id\":\"%{req.id}V\"}"
  }'
```

### AWS CloudFront: Access Logs

```bash
# Включение Access Logs
aws cloudfront update-distribution \
  --id E1234567890ABC \
  --distribution-config '{
    "Logging": {
      "Enabled": true,
      "Bucket": "s3://cdn-logs-bucket.s3.amazonaws.com",
      "Prefix": "cloudfront/",
      "IncludeCookies": false
    }
  }'

# Формат логов CloudFront:
# date time x-edge-location sc-bytes c-ip cs-method cs(Host) cs-uri-stem sc-status cs(Referer) cs(User-Agent) cs(Cookie) x-edge-result-type x-edge-request-id x-host-header cs-protocol cs-bytes time-taken x-forwarded-for ssl-protocol ssl-cipher x-edge-response-result-type cs-protocol-version fle-status fle-encrypted-fields c-port time-to-first-byte x-edge-detailed-result-type sc-content-type sc-content-range sc-range-start sc-range-end
```

### Tracing через traceparent

**Пример: генерация trace-id в приложении:**
```python
import uuid
import time

def generate_traceparent():
    """Генерация W3C Trace Context traceparent."""
    version = "00"
    trace_id = uuid.uuid4().hex  # 32 hex = 16 bytes
    parent_id = uuid.uuid4().hex[:16]  # 16 hex = 8 bytes
    flags = "01"  # sampled
    return f"{version}-{trace_id}-{parent_id}-{flags}"

# Пример: передача trace-id через CDN
traceparent = generate_traceparent()
# → 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01

# Отправка запроса с trace-id
headers = {
    "traceparent": traceparent,
    "Authorization": "Bearer {token}"
}
# CDN добавит к ответу Server-Timing с таймингами edge и origin
```

**Анализ Server-Timing:**
```bash
# Получение таймингов
curl -sD- https://example.com/api/data | grep -i server-timing
# → server-timing: edge;dur=3, origin;dur=45, total;dur=48
# → server-timing: cache;desc="hit", ttl;desc=345

# Парсинг и расчёт
python3 -c "
import re
header = 'edge;dur=3, origin;dur=45, total;dur=48'
metrics = dict(re.findall(r'(\w+);dur=(\d+)', header))
print(f'Edge: {metrics.get(\"edge\", 0)}ms')
print(f'Origin: {metrics.get(\"origin\", 0)}ms')
print(f'Edge overhead: {int(metrics.get(\"total\", 0)) - int(metrics.get(\"origin\", 0))}ms')
"
```

### Synthetic Monitoring

```bash
#!/bin/bash
# synthetic_monitor.sh — синтетический мониторинг CDN из разных PoP

URLS=(
  "https://example.com/"
  "https://example.com/api/products"
  "https://example.com/static/app.js"
)

REGIONS=("LAX" "FRA" "NRT" "SIN" "SYD")

for url in "${URLS[@]}"; do
  for region in "${REGIONS[@]}"; do
    # Запрос из конкретного PoP (через区域性 DNS)
    RESULT=$(curl -sD- -o /dev/null \
      -w "time_namelookup=%{time_namelookup}\ntime_connect=%{time_connect}\ntime_starttransfer=%{time_starttransfer}\ntime_total=%{time_total}" \
      "$url" 2>/dev/null)

    TTFB=$(echo "$RESULT" | grep time_starttransfer | cut -d= -f2)
    TOTAL=$(echo "$RESULT" | grep time_total | cut -d= -f2)

    echo "[$region] $url → TTFB: ${TTFB}s, Total: ${TOTAL}s"
  done
  echo "---"
done
```

**Ожидаемый вывод:**
```
[LAX] https://example.com/ → TTFB: 0.023s, Total: 0.045s
[FRA] https://example.com/ → TTFB: 0.089s, Total: 0.156s
[NRT] https://example.com/ → TTFB: 0.134s, Total: 0.267s
---
```

### Интеграция с Grafana и Prometheus

```yaml
# prometheus.yml — scrape CDN метрик
scrape_configs:
  - job_name: 'cdn_metrics'
    scrape_interval: 30s
    static_configs:
      - targets: ['localhost:9090']
    # Импорт метрик из CDN Analytics API
    # Cloudflare → Prometheus exporter: https://github.com/labbs/cloudflare-exporter

# cloudflare.json — конфигурация экспортера
{
  "api_token": "{api_token}",
  "zone_ids": ["{zone_id}"],
  "scrape_interval": "30s"
}

# Grafana Dashboard: Cloudflare CDN Overview
# Панели: TTFB, Cache Hit Ratio, Error Rate, Bandwidth, RPS
# Дашборд ID: 13904 (Cloudflare CDN)
```

---

## Дополнительная информация

### Типичные ошибки и их решение

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **Нет логов** | CDN не отправляет логи в хранилище | Проверить credentials, bucket, permissions |
| **Нет trace-id** | Невозможно трассировать запрос | Убедиться, что `traceparent` передаётся клиентом |
| **Высокий TTFB** | `Server-Timing: origin;dur > 200ms` | Оптимизировать Origin, проверить маршрутизацию |
| **Memory Overflow** | Логи переполняют хранилище | Настроить ротацию, агрегацию, фильтрацию |

### Связанные темы

- **[Обзор CDN](cdn_overview.md)** — заголовки CDN и диагностика.
- **[Health Checks и Failover](cdn_origin_health_checks.md)** — мониторинг состояния Origin.
- **[Tracing и Observability](../../Concepts/Observability_and_Monitoring/)** — обзор observability.
