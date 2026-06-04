# Blackbox Exporter — Метрики и алертинг

## Определения

**Метрики Blackbox Exporter** — временные ряды, генерируемые экспортером при выполнении проверок (probes) целевых эндпоинтов. Результаты проверок доступны по пути `/probe`, метрики работы самого экспортера — по `/metrics`.

**HTTP (HyperText Transfer Protocol)** — протокол передачи гипертекста.
**SSL (Secure Sockets Layer)** — протокол защищенных сокетов.
**TLS (Transport Layer Security)** — протокол защиты транспортного уровня.

**См. также:** [Обзор и концепции](./blackbox_exporter_overview.md), [Конфигурация модулей](./blackbox_exporter_modules_configuration.md).

## Основные концепции

### Основные метрики

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `probe_success` | gauge | `1` если проверка успешна, `0` если нет |
| `probe_duration_seconds` | gauge | Общее время выполнения проверки |
| `probe_dns_lookup_time_seconds` | gauge | Время DNS (Domain Name System) запроса |
| `probe_connect_duration_seconds` | gauge | Время установления соединения (TCP/TLS) |
| `probe_tls_version_info{version="TLSv1.3"}` | info | Информация о версии TLS |
| `probe_ssl_earliest_cert_expiry` | gauge | Время истечения SSL-сертификата (epoch seconds) |
| `probe_ssl_last_chain_expiry_timestamp_seconds` | gauge | Время истечения последнего сертификата в цепочке |
| `probe_http_status_code` | gauge | HTTP статус-код ответа |
| `probe_http_duration_seconds` | gauge | Время HTTP-запроса (по фазам: connect, tls, processing, transfer) |
| `probe_http_content_length` | gauge | Размер тела ответа (Content-Length) |
| `probe_http_redirects` | gauge | Количество редиректов |
| `probe_ip_protocol` | gauge | Протокол IP (Internet Protocol) (`4`/`6`) |
| `probe_icmp_round_trip_seconds` | gauge | Время ICMP (Internet Control Message Protocol) ping (RTT — Round Trip Time) |
| `probe_tcp_connect_duration_seconds` | gauge | Время TCP (Transmission Control Protocol) соединения |
| `probe_icmp_duration_seconds` | gauge | Время ICMP-проверки (фазы: resolve, rtt и др.) |
| `up` | gauge | `1` если Prometheus успешно скрейпил экспортер, `0` если нет |

### Лейблы метрик

| Лейбл | Описание | Пример |
| :--- | :--- | :--- |
| `instance` | Адрес Blackbox Exporter | `blackbox:9115` |
| `job` | Имя задания (job) в Prometheus | `blackbox-http` |
| `target` | Целевой эндпоинт (после relabeling → `instance`) | `https://example.com` |
| `module` | Использованный модуль | `http_2xx`, `tcp_connect`, `icmp` |

## Практические сценарии

### Алерт: эндпоинт недоступен

```yaml
- alert: BlackboxProbeFailed
  expr: probe_success == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Проверка {{ $labels.instance }} не удалась"
    description: "Blackbox-проверка (модуль {{ $labels.module }}) не удалась более 5 минут"
```

### Алерт: высокое время ответа

```yaml
- alert: BlackboxSlowResponse
  expr: probe_duration_seconds > 2
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Медленный ответ от {{ $labels.instance }}"
    description: "Время ответа превышает 2 секунды (текущее: {{ $value }}s)"
```

### Алерт: SSL-сертификат истекает

```yaml
- alert: BlackboxSSLCertExpiring
  expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 30
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "SSL-сертификат истекает на {{ $labels.instance }}"
    description: "До истечения SSL-сертификата осталось менее 30 дней ({{ $value | humanizeDuration }})"
```

### Алерт: SSL-сертификат истёк

```yaml
- alert: BlackboxSSLCertExpired
  expr: probe_ssl_earliest_cert_expiry < time()
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "SSL-сертификат истёк на {{ $labels.instance }}"
    description: "SSL-сертификат более недействителен"
```

### Алерт: некорректный HTTP статус-код

```yaml
- alert: BlackboxUnexpectedHTTPStatus
  expr: probe_http_status_code < 200 or probe_http_status_code >= 400
  for: 3m
  labels:
    severity: warning
  annotations:
    summary: "Неожиданный HTTP статус от {{ $labels.instance }}"
    description: "Получен HTTP статус-код {{ $value }}"
```

### Алерт: недоступность самого экспортера

```yaml
- alert: BlackboxExporterDown
  expr: up{job=~"blackbox.*"} == 0
  for: 3m
  labels:
    severity: critical
  annotations:
    summary: "Blackbox Exporter недоступен ({{ $labels.instance }})"
    description: "Prometheus не может получить метрики от Blackbox Exporter"
```

### Recording rules для агрегации доступности

```yaml
groups:
  - name: blackbox-recording-rules
    interval: 30s
    rules:
      # Доступность эндпоинта в процентах за 5 минут
      - record: job:probe_availability:ratio
        expr: avg_over_time(probe_success[5m]) * 100

      # 95-й перцентиль времени ответа по job
      - record: job:probe_duration:p95
        expr: histogram_quantile(0.95, sum(rate(probe_duration_seconds_bucket[5m])) by (le, job))
```

## Дополнительная информация

**См. также:**

- [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
- [Alertmanager](../../alertmanager.md)
- [Правила оповещений](../../rules.md)
