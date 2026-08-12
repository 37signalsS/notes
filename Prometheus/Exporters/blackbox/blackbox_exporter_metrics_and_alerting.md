# Blackbox Exporter — Метрики и алертинг

## Определения

**Метрики Blackbox Exporter** — временные ряды, генерируемые экспортером в процессе выполнения сетевых проверок (probes). В отличие от внутренних метрик приложения, они отражают состояние сервиса с точки зрения внешнего клиента.

*   **Эндпоинт `/probe`** — возвращает результаты проверки конкретной цели.
*   **Эндпоинт `/metrics`** — возвращает метрики состояния самого процесса экспортера.
*   **CEL (Common Expression Language)** — язык выражений, используемый в новых версиях экспортера для сложной валидации HTTP-ответов (например, проверки полей JSON или специфических заголовков).

**Связанные документы:**
*   [Обзор и концепции](./blackbox_exporter_overview.md)
*   [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
*   [Установка и настройка](./blackbox_exporter_installation_and_setup.md)

## Основные концепции

### Ключевые метрики (v0.28.0+)

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `probe_success` | gauge | Основной индикатор: `1` — успех, `0` — сбой. |
| `probe_duration_seconds` | gauge | Полное время выполнения проверки. |
| `probe_http_version` | gauge | Версия протокола, использованная при ответе (`1.1`, `2`, `3`). |
| `probe_http_status_code` | gauge | HTTP-код состояния ответа. |
| `probe_http_duration_seconds` | gauge | Время HTTP-запроса, разбитое по фазам (лейбл `phase`). |
| `probe_http_redirects` | gauge | Количество выполненных редиректов. |
| `probe_grpc_status_code` | gauge | Код статуса gRPC (0 — OK, 14 — Unavailable и т.д.). |
| `probe_grpc_health_status` | gauge | Статус gRPC Health Check (1 — SERVING). |
| `probe_ssl_earliest_cert_expiry` | gauge | Unix-время (epoch) истечения ближайшего сертификата в цепочке. |
| `probe_tls_version_info` | info | Информация о версии TLS (лейбл `version`). |
| `probe_failed_due_to_cel` | gauge | `1`, если валидация через CEL-выражение не прошла. |
| `probe_dns_lookup_time_seconds` | gauge | Время, затраченное на DNS-резолвинг. |
| `probe_icmp_duration_seconds` | gauge | Время отклика ICMP (Ping). |
| `up` | gauge | Статус доступности самого Blackbox Exporter для Prometheus. |

### Детализация фаз HTTP (Лейбл phase)

Метрика `probe_http_duration_seconds` позволяет диагностировать, на каком этапе возникают задержки:
*   `resolve`: Время на DNS-резолвинг.
*   `connect`: Время установки TCP-соединения.
*   `tls`: Время выполнения TLS-handshake.
*   `processing`: Время от отправки запроса до получения первого байта ответа (**TTFB**).
*   `transfer`: Время передачи тела ответа.

### Лейблы метрик

| Лейбл | Описание | Пример |
| :--- | :--- | :--- |
| `instance` | Адрес Blackbox Exporter. | `127.0.0.1:9115` |
| `target` | Проверяемый URL или хост (после relabeling). | `https://api.myapp.com` |
| `module` | Имя модуля из `blackbox.yml`. | `http_v3_tls13` |

## Практические сценарии

### Настройка алертов (Prometheus Rules)

#### Общий сбой проверки (Availability)
```yaml
- alert: BlackboxProbeFailed
  expr: probe_success == 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Сбой проверки эндпоинта {{ $labels.target }}"
    description: "Сервис {{ $labels.target }} недоступен более 2 минут (модуль {{ $labels.module }})."
```

#### Истечение SSL-сертификата (Многоуровневый)
```yaml
# Предупреждение за 30 дней
- alert: SSLCertExpiringSoon
  expr: (probe_ssl_earliest_cert_expiry - time()) < 86400 * 30
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "Срок действия SSL истекает через 30 дней"
    description: "Сертификат для {{ $labels.target }} истечет {{ $value | humanizeTimestamp }}."

# Критическая ошибка за 7 дней
- alert: SSLCertExpiringCritical
  expr: (probe_ssl_earliest_cert_expiry - time()) < 86400 * 7
  for: 15m
  labels:
    severity: critical
  annotations:
    summary: "Критическое истечение SSL для {{ $labels.target }}"
    description: "Сертификат истекает менее чем через неделю!"
```

#### Деградация производительности (Latency)
```yaml
- alert: BlackboxSlowResponse
  expr: probe_duration_seconds > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Медленный ответ от {{ $labels.target }}"
    description: "Время ответа превышает 5 секунд (текущее: {{ $value | printf \"%.2f\" }}s)."
```

#### Ошибка DNS-резолвинга
```yaml
- alert: BlackboxDNSFailure
  expr: probe_dns_lookup_time_seconds == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Ошибка DNS для {{ $labels.target }}"
    description: "Не удалось разрешить имя хоста для цели {{ $labels.target }}."
```

### Анализ SLO и SLI (Recording Rules)

Для расчета доступности и производительности на длительных интервалах рекомендуется использовать Recording Rules.

```yaml
groups:
  - name: blackbox_slo_rules
    rules:
      # SLI: Доступность (Availability) за 5 минут
      - record: job:probe_success:ratio_rate5m
        expr: avg_over_time(probe_success[5m])

      # SLI: 95-й перцентиль времени ответа за 1 час
      - record: job:probe_duration_seconds:p95_1h
        expr: quantile_over_time(0.95, probe_duration_seconds[1h])

      # SLO: Агрегированная доступность за 30 дней
      - record: job:probe_success:avg30d
        expr: avg_over_time(probe_success[30d])
```

## Дополнительная информация

*   **Таймауты:** Убедитесь, что `scrape_timeout` в Prometheus больше, чем `timeout` в модуле Blackbox Exporter, чтобы избежать некорректных нулей в метриках.
*   **Безопасность:** При проверке внутренних ресурсов через публичный экспортер используйте TLS и Basic Auth на стороне экспортера (настраивается в `web-config.yml`).

**См. также:**
*   [Предотвращение истечения SSL](../../../Kubernetes/Operations/ssl_expiration_prevention.md)
*   [Prometheus: Recording и Alerting Rules](../../rules.md)
*   [Настройка Alertmanager](../../alertmanager.md)
