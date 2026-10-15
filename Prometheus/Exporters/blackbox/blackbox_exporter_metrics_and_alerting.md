# Blackbox Exporter — Метрики и алертинг

## Определения

**Метрики Blackbox Exporter** — временные ряды, генерируемые экспортером в процессе выполнения сетевых проверок (probes). В отличие от внутренних метрик приложения, они отражают состояние сервиса с точки зрения внешнего клиента и позволяют обнаруживать проблемы, невидимые для агентов, развёрнутых внутри инфраструктуры.

*   **Эндпоинт `/probe`** — возвращает результаты проверки конкретной цели. При вызове без параметров возвращает ошибку или пустой результат. В параметре `target` передаётся проверяемый хост, URL или IP-адрес.
*   **Эндпоинт `/metrics`** — возвращает метрики состояния самого процесса экспортера: количество обработанных запросов, ошибки конфигурации, uptime.
*   **CEL (Common Expression Language)** — язык выражений, используемый в новых версиях экспортера для сложной валидации HTTP-ответов (например, проверки полей JSON или специфических заголовков).
*   **Prober** — компонент внутри экспортера, отвечающий за выполнение проверки определённого типа (HTTP, TCP, DNS, ICMP, gRPC). Каждый prober генерирует свой набор метрик.
*   **Внешний мониторинг (Blackbox Monitoring)** — подход, при котором проверки выполняются извне целевой системы, эмулируя действия реального пользователя или клиента. Позволяет фиксировать проблемы DNS, маршрутизации, балансировки и фаерволлов.

**Связанные документы:**
*   [Обзор и концепции](./blackbox_exporter_overview.md)
*   [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
*   [Установка и настройка](./blackbox_exporter_installation_and_setup.md)

## Основные концепции

### Ключевые метрики (v0.28.0+)

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `probe_success` | gauge | Основной индикатор доступности: `1` — успех, `0` — сбой. Отсутствие метрики означает, что проверка не была выполнена из-за ошибки конфигурации или недоступности экспортера. |
| `probe_duration_seconds` | gauge | Полное время выполнения проверки от момента отправки запроса до получения полного ответа. Включает все фазы, включая DNS, TCP/TLS и обработку. |
| `probe_http_version` | gauge | Версия протокола, использованная при ответе (`1.1`, `2`, `3`). Значение `0` или отсутствие метрики означает, что HTTP-проверка не была выполнена. |
| `probe_http_status_code` | gauge | HTTP-код состояния ответа. При отсутствии ответа метрика не экспортируется. |
| `probe_http_duration_seconds` | gauge | Время HTTP-запроса, разбитое по фазам (лейбл `phase`). |
| `probe_http_redirects` | gauge | Количество выполненных редиректов перед получением финального ответа. |
| `probe_grpc_status_code` | gauge | Код статуса gRPC в числовом формате (0 — OK, 14 — Unavailable и т.д.). |
| `probe_grpc_health_status` | gauge | Статус gRPC Health Check (1 — SERVING, 0 — не SERVING). |
| `probe_ssl_earliest_cert_expiry` | gauge | Unix-время (epoch) истечения ближайшего сертификата в цепочке. Может отсутствовать, если проверка не использует TLS. |
| `probe_tls_version_info` | info | Информация о версии TLS (лейбл `version`). Метрика типа `info` всегда равна 1 при наличии TLS-соединения. |
| `probe_failed_due_to_cel` | gauge | `1`, если валидация через CEL-выражение не прошла. |
| `probe_dns_lookup_time_seconds` | gauge | Время, затраченное на DNS-резолвинг. При отсутствии DNS-фазы метрика не экспортируется. |
| `probe_icmp_duration_seconds` | gauge | Время отклика ICMP (ping). Может отсутствовать, если модуль ICMP не настроен или права не позволяют выполнить ping. |
| `up` | gauge | Статус доступности самого Blackbox Exporter для Prometheus. `1` — экспортер отвечает, `0` — недоступен. |

### Детализация фаз HTTP (Лейбл phase)

Метрика `probe_http_duration_seconds` позволяет диагностировать, на каком этапе возникают задержки:

*   `resolve`: Время на DNS-резолвинг. Высокое значение указывает на проблемы с DNS-сервером или перегрузку кэша.
*   `connect`: Время установки TCP-соединения. Рост этого значения обычно означает сетевые задержки, перегруженный балансировщик или exhaustion портов на стороне сервера.
*   `tls`: Время выполнения TLS-handshake. Зависит от размера цепочки сертификатов, алгоритмов и производительности сервера.
*   `processing`: Время от отправки запроса до получения первого байта ответа (**TTFB**). Наиболее важный показатель для диагностики проблем приложения или базы данных.
*   `transfer`: Время передачи тела ответа. Рост значения указывает на большие объёмы данных или низкую пропускную способность канала.

### Лейблы метрик

| Лейбл | Описание | Пример |
| :--- | :--- | :--- |
| `instance` | Адрес Blackbox Exporter. | `127.0.0.1:9115` |
| `target` | Проверяемый URL или хост (после relabeling). | `https://api.myapp.com` |
| `module` | Имя модуля из `blackbox.yml`. | `http_v3_tls13` |

### Интерпретация метрик по протоколам

**HTTP/HTTPS:**
*   `probe_success == 1` при HTTP-коде 2xx или 3xx (в зависимости от конфигурации модуля).
*   `probe_http_status_code` позволяет детектировать специфические ошибки: 4xx — проблемы аутентификации или параметров запроса, 5xx — сбои на стороне сервиса.
*   `probe_http_version` помогает обнаружить проблемы с протоколом: например, клиент ожидает HTTP/2, но сервер отвечает HTTP/1.1.

**TCP:**
*   Метрика `probe_success` отражает факт установки соединения на указанный порт.
*   `probe_duration_seconds` включает время установки соединения и, при использовании `send_string`/`expect_string`, время обмена данными.

**DNS:**
*   `probe_success == 1` при получении ответа с кодом `NOERROR` или `NXDOMAIN` (если разрешено в конфигурации).
*   `probe_dns_lookup_time_seconds` показывает латентность запроса к резолверу.
*   Для детальной диагностики DNS-интеграции используйте [Мониторинг DNS](../../../Networking/Protocols/DNS/dns_monitoring.md).

**ICMP:**
*   `probe_success == 1` при получении ICMP echo reply.
*   `probe_icmp_duration_seconds` — round-trip time.
*   Важно: ICMP часто блокируется фаерволлом. Для проверки доступности хоста используйте TCP-проверки на порт 80 или 443.

**gRPC:**
*   `probe_grpc_status_code == 0` означает успешный вызов RPC.
*   `probe_grpc_health_status == 1` подтверждает статус `SERVING` на стороне сервера.

## Практические сценарии

### Предварительные требования для алертинга

Перед настройкой алертов убедитесь, что:
1.  Blackbox Exporter развёрнут и доступен из сети Prometheus.
2.  Модули `blackbox.yml` протестированы вручную: `curl "http://localhost:9115/probe?target=example.com&module=http_2xx"`.
3.  В Prometheus настроен `scrape_config` с параметром `metrics_path: /probe` и корректным `relabeling`.
4.  `scrape_timeout` в Prometheus строго больше, чем `timeout` в модуле Blackbox Exporter. Рекомендуемая разница — не менее 500мс.
5.  Alertmanager развёрнут и доступен для Prometheus.

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

**Теория и нюансы:**
*   Используйте `for: 2m` для подавления дребезга от кратковременных сетевых сбоев.
*   Если `probe_success` отсутствует (не `0`, а `NaN`), это означает проблему с самим экспортером или конфигурацией. Дополнительный алерт на `up == 0` или `absent(probe_success)` покрывает этот случай.

#### Multi-Window Burn Rate Alert (SLO-based)

Для SRE-подхода к алертингу используйте Burn Rate, который показывает, во сколько раз текущая скорость ошибок превышает допустимую для достижения цели SLO:

```yaml
groups:
  - name: blackbox_slo_alerts
    rules:
      # Burn Rate за 1 час при SLO 99.9%
      - alert: BlackboxErrorBudgetBurnRate1h
        expr: |
          (
            avg_over_time(probe_success[1h]) < 0.999
          ) and (
            avg_over_time(probe_success[5m]) < 0.999
          )
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Error Budget burn rate за 1ч превышает SLO 99.9%"
          description: "Доступность {{ $labels.target }} за 1ч: {{ $value | printf \"%.4f\" }}. SLO: 99.9%."

      # Burn Rate за 6ч при SLO 99.9%
      - alert: BlackboxErrorBudgetBurnRate6h
        expr: |
          (
            avg_over_time(probe_success[6h]) < 0.999
          ) and (
            avg_over_time(probe_success[30m]) < 0.999
          )
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Error Budget burn rate за 6ч превышает SLO 99.9%"
          description: "Доступность {{ $labels.target }} за 6ч: {{ $value | printf \"%.4f\" }}. SLO: 99.9%."
```

**Преимущества подхода:**
*   Раннее обнаружение проблем, когда бюджет ошибок тратится быстрее нормы.
*   Разделение на `warning` и `critical` позволяет реагировать до полного исчерпания бюджета.
*   Двухоконный подход (`short window AND long window`) снижает количество ложных срабатываний.

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

**Важно:** Для валидации используйте `probe_ssl_earliest_cert_expiry`, а не время на хосте. Это исключает проблемы с рассинхронизированными часами.

#### Деградация производительности (Latency) с фазами

```yaml
# Общая латентность
- alert: BlackboxSlowResponse
  expr: probe_duration_seconds > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Медленный ответ от {{ $labels.target }}"
    description: "Время ответа превышает 5 секунд (текущее: {{ $value | printf \"%.2f\" }}s)."

# Задержка на уровне приложения (TTFB)
- alert: BlackboxSlowProcessing
  expr: probe_http_duration_seconds{phase="processing"} > 3
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Высокий TTFB у {{ $labels.target }}"
    description: "Время обработки запроса: {{ $value | printf \"%.2f\" }}s."

# Задержка TLS-handshake
- alert: BlackboxSlowTLS
  expr: probe_http_duration_seconds{phase="tls"} > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Долгий TLS-handshake у {{ $labels.target }}"
    description: "Время TLS-handshake: {{ $value | printf \"%.2f\" }}s."
```

**Теория:** Разделение по фазам позволяет локализовать проблему без глубокого доступа к инфраструктуре. Например, высокий `connect` при нормальном `processing` указывает на сетевые проблемы, а не на проблемы приложения.

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

**Примечание:** Значение `0` означает, что DNS-резолвинг не удался. Отсутствие метрики (`NaN`) означает, что DNS-проверка не была выполнена вообще.

#### Ошибки CEL-валидации

```yaml
- alert: BlackboxCELValidationFailed
  expr: probe_failed_due_to_cel == 1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "CEL-валидация не прошла для {{ $labels.target }}"
    description: "Ответ не соответствует CEL-выражению в модуле {{ $labels.module }}."
```

**Когда использовать:** CEL-алерты полезны для детализированной проверки API-ответов (например, наличие обязательного поля `status: "ok"` в JSON).

#### gRPC-специфичные алерты

```yaml
# gRPC сервис недоступен
- alert: BlackboxGRPCUnavailable
  expr: probe_grpc_status_code != 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "gRPC сервис {{ $labels.target }} вернул ошибку"
    description: "Код статуса: {{ $labels.probe_grpc_status_code }}."

# gRPC Health Check не SERVING
- alert: BlackboxGRPCNotServing
  expr: probe_grpc_health_status != 1
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "gRPC Health Check failed для {{ $labels.target }}"
    description: "Сервис не в состоянии SERVING."
```

#### HTTP-редиректы (неожиданное поведение)

```yaml
- alert: BlackboxUnexpectedRedirect
  expr: probe_http_redirects > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Много редиректов у {{ $labels.target }}"
    description: "Количество редиректов: {{ $value }}. Возможна проблема с конфигурацией или цикличный редирект."
```

### Анализ SLO и SLI (Recording Rules)

Для расчета доступности и производительности на длинных интервалах рекомендуется использовать Recording Rules. Это снижает нагрузку на Prometheus и ускоряет дашборды.

```yaml
groups:
  - name: blackbox_slo_rules
    interval: 30s
    rules:
      # SLI: Доступность (Availability) за 5 минут
      - record: job:probe_success:ratio_rate5m
        expr: avg_over_time(probe_success[5m])

      # SLI: 95-й перцентиль времени ответа за 1 час
      - record: job:probe_duration_seconds:p95_1h
        expr: quantile_over_time(0.95, probe_duration_seconds[1h])

      # SLI: 99-й перцентиль времени ответа за 1 час
      - record: job:probe_duration_seconds:p99_1h
        expr: quantile_over_time(0.99, probe_duration_seconds[1h])

      # SLO: Агрегированная доступность за 30 дней
      - record: job:probe_success:avg30d
        expr: avg_over_time(probe_success[30d])

      # SLI: Доля успешных DNS-запросов за 5 минут
      - record: job:probe_dns_success_ratio:5m
        expr: avg_over_time(probe_dns_success[5m])

      # SLI: Процент редиректов относительно общего числа запросов
      - record: job:probe_http_redirects:avg5m
        expr: avg_over_time(probe_http_redirects[5m])
```

**Зачем нужны отдельные SLI-метрики:**
*   Дашборды и алерты работают быстрее, так как query к预先 вычисленным метрикам дешевле.
*   Позволяет централизованно управлять SLO для всех эндпоинтов через единые пороговые значения.

### Production Recording Rules (готовые шаблоны)

Ниже приведены рекомендуемые Recording Rules для production-окружения. Они разбиты на три группы: базовые SLI, агрегация по модулям и расширенные метрики.

```yaml
groups:
  # === Базовые SLI для дашбордов и алертов ===
  - name: blackbox_sli_base
    interval: 30s
    rules:
      # Доступность по модулям (5 мин)
      - record: blackbox:probe_success:ratio_rate5m
        expr: avg by (module) (avg_over_time(probe_success[5m]))

      # Доступность по целям (5 мин)
      - record: blackbox:probe_success_by_target:ratio_rate5m
        expr: avg_over_time(probe_success[5m])

      # 95-й перцентиль латентности по модулям (1 час)
      - record: blackbox:probe_duration:p95_by_module_1h
        expr: |
          quantile by (module) (
            0.95,
            avg_over_time(probe_duration_seconds[1h])
          )

      # 99-й перцентиль латентности по модулям (1 час)
      - record: blackbox:probe_duration:p99_by_module_1h
        expr: |
          quantile by (module) (
            0.99,
            avg_over_time(probe_duration_seconds[1h])
          )

      # Средняя латентность по модулям (5 мин)
      - record: blackbox:probe_duration:avg5m
        expr: avg by (module) (avg_over_time(probe_duration_seconds[5m]))

      # SSL: дни до истечения (минимальные по модулям)
      - record: blackbox:ssl_days_remaining:min
        expr: |
          min by (module) (
            (probe_ssl_earliest_cert_expiry - time()) / 86400
          )

      # DNS: время резолвинга (95-й перцентиль)
      - record: blackbox:dns_lookup:p95_1h
        expr: quantile_over_time(0.95, probe_dns_lookup_time_seconds[1h])

  # === Агрегация по модулям для SLO-алертов ===
  - name: blackbox_slo_aggregation
    interval: 30s
    rules:
      # Доступность HTTP за 1 час
      - record: blackbox:http_success:ratio_rate1h
        expr: |
          avg_over_time(
            probe_success{module=~"http_.*"}[1h]
          )

      # Доступность TCP за 1 час
      - record: blackbox:tcp_success:ratio_rate1h
        expr: |
          avg_over_time(
            probe_success{module=~"tcp_.*"}[1h]
          )

      # Доступность DNS за 1 час
      - record: blackbox:dns_success:ratio_rate1h
        expr: |
          avg_over_time(
            probe_success{module=~"dns_.*"}[1h]
          )

      # Multi-window burn rate (1 час / 5 мин)
      - record: blackbox:slo:burnrate_1h_5m
        expr: |
          (
            avg_over_time(probe_success[1h]) < 0.999
          ) and (
            avg_over_time(probe_success[5m]) < 0.999
          )

      # Multi-window burn rate (6 часов / 30 мин)
      - record: blackbox:slo:burnrate_6h_30m
        expr: |
          (
            avg_over_time(probe_success[6h]) < 0.999
          ) and (
            avg_over_time(probe_success[30m]) < 0.999
          )

  # === Расширенные метрики для дашбордов ===
  - name: blackbox_advanced_metrics
    interval: 60s
    rules:
      # HTTP фазы (разбивка по phase)
      - record: blackbox:http_phase:avg_resolve_5m
        expr: avg_over_time(probe_http_duration_seconds{phase="resolve"}[5m])

      - record: blackbox:http_phase:avg_connect_5m
        expr: avg_over_time(probe_http_duration_seconds{phase="connect"}[5m])

      - record: blackbox:http_phase:avg_tls_5m
        expr: avg_over_time(probe_http_duration_seconds{phase="tls"}[5m])

      - record: blackbox:http_phase:avg_processing_5m
        expr: avg_over_time(probe_http_duration_seconds{phase="processing"}[5m])

      - record: blackbox:http_phase:avg_transfer_5m
        expr: avg_over_time(probe_http_duration_seconds{phase="transfer"}[5m])

      # Доля успешных проверок по target за день
      - record: blackbox:probe_success:daily_ratio
        expr: avg_over_time(probe_success[24h])

      # Количество редиректов (среднее за 5 мин)
      - record: blackbox:http_redirects:avg5m
        expr: avg_over_time(probe_http_redirects[5m])
```

**Применение:**
1. Сохраните правила в файл `/etc/prometheus/rules/blackbox_recording_rules.yml`
2. Проверьте синтаксис: `promtool check rules blackbox_recording_rules.yml`
3. Добавьте в `rule_files` конфигурации Prometheus
4. Выполните `kill -HUP $(pidof prometheus)` для горячей перезагрузки

### Валидация работоспособности

#### Ручная проверка через curl

```bash
# HTTP 2xx проверка
curl -s "http://localhost:9115/probe?target=https://example.com&module=http_2xx" | grep probe_success
# → probe_success 1

# TCP проверка порта 443
curl -s "http://localhost:9115/probe?target=example.com:443&module=tcp_connect" | grep probe_success
# → probe_success 1

# DNS проверка
curl -s "http://localhost:9115/probe?target=example.com&module=dns_google" | grep probe_success
# → probe_success 1

# ICMP проверка (требует cap_net_raw)
curl -s "http://localhost:9115/probe?target=example.com&module=icmp" | grep probe_success
# → probe_success 1
```

#### Проверка конфигурации через promtool

```bash
# Валидация правил алертинга
promtool check rules prometheus_rules/blackbox_alerts.yml

# Проверка синтаксиса конфигурации Prometheus
promtool check config prometheus.yml
```

#### Диагностика в реальном времени

```bash
# Сбор метрик с экспортера напрямую
curl -s "http://localhost:9115/metrics" | grep probe_success

# Поиск по конкретному таргету
curl -s "http://localhost:9115/metrics" | grep 'probe_success{target="example.com"}'

# Проверка времени отклика по фазам
curl -s "http://localhost:9115/metrics" | grep probe_http_duration_seconds | grep example.com
```

**Диагностические запросы PromQL:**

```promql
# Эндпоинты, которые сейчас недоступны
probe_success == 0

# Дней до истечения TLS-сертификата (читаемая форма)
(probe_ssl_earliest_cert_expiry - time()) / 86400

# Среднее время пробы за час
avg_over_time(probe_duration_seconds[1h])
```

### Интеграция с Alertmanager

Пример маршрутизации алертов Blackbox Exporter по severity:

```yaml
route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'team-alpha'
  routes:
    - match:
        alertname: BlackboxProbeFailed|BlackboxGRPCUnavailable|BlackboxDNSFailure|BlackboxGRPCNotServing
      severity: critical
      receiver: 'oncall-pager'
    - match:
        alertname: BlackboxSlowResponse|BlackboxSlowProcessing|SSLCertExpiringSoon
      severity: warning
      receiver: 'team-alpha-email'

receivers:
  - name: 'oncall-pager'
    pagerduty_configs:
      - service_key: '<KEY>'
  - name: 'team-alpha-email'
    email_configs:
      - to: 'ops@example.com'
```

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `probe_success` всегда `0`, curl работает | ICMP блокирован фаерволлом | Переключитесь на TCP-проверки на порт 80/443 |
| `probe_success` отсутствует, а `up == 1` | Ошибка в конфигурации модуля или `target` не указан | Проверьте логи экспортера: `journalctl -u blackbox_exporter` |
| Высокий `connect` при низком `processing` | Проблемы с маршрутизацией или балансировщиком | Проверьте сетевую таблицу и состояние LB |
| `probe_ssl_earliest_cert_expiry` отсутствует | Проверка выполняется по HTTP, а не HTTPS | Убедитесь, что модуль использует prober `http` с `tls` |
| `probe_dns_lookup_time_seconds == 0` | DNS-сервер недоступен или блокирован | Проверьте доступность DNS из сети экспортера: `dig @<resolver> example.com` |
| Дребезг алертов | Порог слишком близок к нормальному значению | Увеличьте `for:` или добавьте hysteresis через `keep_firing_for` |
| `probe_http_redirects` = 0 при ожидаемом редиректе | `follow_redirects: false` в модуле | Включите `follow_redirects: true` или проверьте цепочку редиректов вручную |

### Диагностика CEL-ошибок

Если `probe_failed_due_to_cel == 1`, но ответ сервиса выглядит корректным:
1.  Проверьте синтаксис CEL-выражения в `blackbox.yml`.
2.  Убедитесь, что тело ответа действительно содержит ожидаемые поля (CEL чувствителен к типам данных).
3.  Проверьте кодировку ответа (CEL работает с UTF-8).

## Лучшие практики

1.  **Группировка по module и target:** Используйте `group_by: ['alertname', 'module', 'target']` в Alertmanager для уменьшения шума.
2.  **Избегайте алертов на отсутствие метрики:** Настройте отдельный алерт `absent(probe_success)`, чтобы детектировать проблемы с экспортером.
3.  **Используйте `for:` везде:** Без задержки `for` любые кратковременные сетевые флуктуации генерируют алерты.
4.  **Настройте `scrape_timeout` корректно:** Если `scrape_timeout` < `timeout` в модуле, Prometheus прервёт запрос, и метрика не будет экспортирована. Это выглядит как `NaN`, что может быть недетектировано простым `probe_success == 0`.
5.  **Разделяйте критические и предупреждающие алерты:** Не смешивайте в одной группе алерты с разной severity. Это усложняет настройку маршрутизации.
6.  **Документируйте пороги:** Каждый порог в алерте должен быть обоснован либо SLA, либо историческими данными (p99 latency).
7.  **Используйте recording rules для SLO:** Это позволяет строить burn rate alerts и дашборды без пересчёта тяжелых `avg_over_time` на лету.

## Крайние случаи и ограничения

*   **Отсутствие метрики ≠ сбой:** Если `probe_success` отсутствует, это не значит, что сервис недоступен. Это значит, что экспортер не смог выполнить проверку (неверный target, таймаут, ошибка конфигурации). Используйте `up` и `absent()` для детектирования таких случаев.
*   **ICMP и фаерволлы:** На уровне хоста или сети ICMP часто блокируется фаерволлом по умолчанию. Для проверки доступности хоста используйте TCP-проверки на порт 80 или 443.
*   **HTTP/3 (QUIC):** Поддержка HTTP/3 требует, чтобы целевой сервер поддерживал протокол QUIC (обычно на порту 443/UDP). Если сервер отвечает только HTTP/2, метрика `probe_http_version` покажет `2`.
*   **CORS и редиректы:** Blackbox Exporter не выполняет JavaScript и не обрабатывает CORS. Если страница требует браузерного рендеринга, используйте синтетические проверки через Browser or synthetics outside Prometheus.
*   **Масштабирование:** Один экземпляр Blackbox Exporter может обрабатывать тысячи targets, но при большом количестве одновременных проверок увеличьте `timeout` и ресурсы контейнера/хоста.
*   **IPv6:** Для проверки IPv6-целей используйте отдельные модули (например, `icmp6`). Убедитесь, что сеть экспортера имеет доступ к IPv6.
*   **Аутентификация:** При проверке защищённых эндпоинтов используйте `basic_auth` или `bearer_token` в конфигурации модуля. Не храните секреты в репозитории — используйте переменные окружения или внешние секреты.

## Валидация и отладка

### Проверка работы экспортера

```bash
# Проверка статуса systemd-сервиса
systemctl status blackbox_exporter

# Просмотр логов в реальном времени
journalctl -u blackbox_exporter -f

# Проверка открытого порта
ss -tlnp | grep 9115
# → LISTEN 0 4096 127.0.0.1:9115
```

### Проверка Prometheus Targets

```bash
# Проверка targets в Prometheus UI
curl -s http://localhost:9090/targets | grep blackbox

# Ручный запрос к API Prometheus
curl -s "http://localhost:9090/api/v1/targets" | jq '.data.activeTargets[] | select(.job=="blackbox") | {job: .job, instance: .instance, health: .health}'
```

### Проверка алертов

```bash
# Проверка активных алертов
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.job=="blackbox")'

# Имитация алерта через PromQL
curl -s -G http://localhost:9090/api/v1/query --data-urlencode 'query=probe_success == 0' | jq '.data.result'
```

## См. также

*   [Grafana-дашборды](./blackbox_exporter_grafana_dashboards.md) — визуализация метрик Blackbox Exporter
*   [Масштабирование и HA](./blackbox_exporter_scaling_and_ha.md) — горизонтальное масштабирование и отказоустойчивость
*   [Предотвращение истечения SSL](../../../Kubernetes/Operations/ssl_expiration_prevention.md)
*   [Prometheus: Recording и Alerting Rules](../../rules.md)
*   [Настройка Alertmanager](../../alertmanager.md)
*   [Мониторинг DNS](../../../Networking/Protocols/DNS/dns_monitoring.md)
*   [ICMP мониторинг](../../../Networking/Protocols/ICMP/icmp_monitoring.md)
*   [Сетевое наблюдение в Kubernetes](../../../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md)
