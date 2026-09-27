# OpenTelemetry: Интеграция с Prometheus

## Определения

**Интеграция OpenTelemetry с Prometheus** — это процесс настройки взаимодействия между системой сбора телеметрии OpenTelemetry и сервером метрик Prometheus. Существует два основных направления интеграции:

1. **Prometheus как backend для OTel метрик** — Prometheus принимает метрики напрямую от OTel SDK или Collector через OTLP-протокол.
2. **OTel Collector как агент для Prometheus** — Collector собирает метрики из Prometheus и маршрутизирует их в другие системы.

В 2026 году Prometheus v3 имеет встроенный OTLP-приемник, что упрощает интеграцию без промежуточного Collector.

## Теоретический блок

### Архитектура интеграции

```text
Приложение (OTel SDK) → OTLP → Prometheus (OTLP receiver)
                           ↓
                    OTel Collector → Prometheus (remote write)
                           ↓
                    Backend (Mimir, VictoriaMetrics)
```

### Способы интеграции

| Способ | Описание | Использование |
| :--- | :--- | :--- |
| **OTLP-приемник Prometheus v3** | Prometheus принимает метрики напрямую по OTLP | Простые среды, локальная разработка |
| **OTel Collector → Prometheus remote write** | Collector отправляет метрики через remote write | Production, масштабируемые среды |
| **OTel Collector → Prometheus exporter** | Collector экспортирует метрики в формате Prometheus scrape | Интеграция с существующими Prometheus-инстансами |

### Ключевые компоненты

1. **OTLP Receiver в Prometheus** — включается флагом `--web.enable-otlp-receiver`. Принимает метрики по gRPC (4317) и HTTP (4318).
2. **OTel Collector Prometheus Exporter** — экспортирует метрики в формате Prometheus, доступном для скрейпинга.
3. **OTel Collector Prometheus Remote Write Exporter** — отправляет метрики через remote write протокол Prometheus.
4. **OTel Collector Prometheus Receiver** — скрейпит метрики из Prometheus endpoints.

### Преимущества интеграции

- **Единый стандарт** — OTLP становится стандартом для передачи телеметрии.
- **Гибкость** — возможность маршрутизации метрик в несколько backend-систем.
- **Обогащение** — Collector может обогащать метрики перед отправкой в Prometheus.
- **Фильтрация** — возможность фильтрации и агрегации метрик до отправки.

## Практические сценарии

### Сценарий 1: Prometheus v3 с OTLP-приемником

**Настройка Prometheus:**

```bash
# Запуск с включенным OTLP-приемником
prometheus --config.file=prometheus.yml --web.enable-otlp-receiver

# Prometheus.yml
global:
  scrape_interval: 15s

otlp:
  promote_resource_attributes:
    - service.name
    - service.version
    - k8s.namespace.name

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

**Конфигурация OTel SDK для отправки в Prometheus:**

```bash
# Переменные окружения
OTEL_EXPORTER_OTLP_ENDPOINT=http://prometheus:9090/api/v1/otlp/v1/metrics
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_SERVICE_NAME=my-service
```

**Валидация:**

```bash
# Проверка наличия OTLP-приемника
curl -s http://prometheus:9090/api/v1/status/flags | grep otlp

# Проверка принятых метрик
curl -s http://prometheus:9090/api/v1/query?query=up
```

### Сценарий 2: OTel Collector с Prometheus Exporter

**Конфигурация Collector:**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
  batch:
    timeout: 10s
    send_batch_size: 1024

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
    namespace: "otel"
    const_labels:
      env: production

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus]
```

**Конфигурация Prometheus для скрейпинга Collector:**

```yaml
scrape_configs:
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector:8889']
```

**Валидация:**

```bash
# Проверка метрик Collector
curl -s http://otel-collector:8889/metrics | head -20

# Проверка скрейпинга Prometheus
curl -s http://prometheus:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job=="otel-collector")'
```

### Сценарий 3: OTel Collector с Prometheus Remote Write

**Конфигурация Collector:**

```yaml
exporters:
  prometheusremotewrite:
    endpoint: "http://prometheus:9090/api/v1/write"
    resource_to_telemetry_conversion:
      enabled: true
    timeout: 10s
    retry_on_failure:
      enabled: true
      initial_interval: 1s
      max_interval: 30s

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheusremotewrite]
```

### Сценарий 4: Множественные backend

**Отправка метрик одновременно в Prometheus и другие системы:**

```yaml
exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
  prometheusremotewrite:
    endpoint: "http://mimir:9009/api/v1/push"

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus, prometheusremotewrite]
```

### Сценарий 5: Обогащение метрик перед отправкой

**Добавление атрибутов к метрикам:**

```yaml
processors:
  attributes:
    actions:
      - key: environment
        value: production
        action: upsert
      - key: team
        value: platform
        action: insert

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
    const_labels:
      env: production
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Метрики не появляются в Prometheus** | OTLP-приемник не включен или неверный endpoint | Проверить `--web.enable-otlp-receiver`, endpoint в OTel SDK |
| **Дублирование метрик** | Метрики отправляются и через OTLP, и через scrape | Использовать только один способ интеграции |
| **Потеря метрик при высокой нагрузке** | Переполнение очереди Collector | Увеличить `send_batch_size`, добавить `memory_limiter` |
| **Неверные имена метрик** | Несоответствие семантическим конвенциям OTel | Использовать OTel Semantic Conventions для именования |

### Best Practices

1. **Используйте OTLP** — это стандарт для передачи телеметрии в 2026 году.
2. **Настройте resource attributes** — они помогают идентифицировать источник метрик.
3. **Используйте BatchProcessor** — оптимизирует сетевую нагрузку.
4. **Мониторьте Collector** — отслеживайте метрики `otelcol_exporter_queue_size` и `otelcol_exporter_send_failed_*`.
5. **Тестируйте на staging** — проверяйте корректность интеграции перед продакшеном.

### Ссылки

- [Prometheus OTLP Receiver](https://prometheus.io/docs/guides/opentelemetry/)
- [OTel Collector Prometheus Exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/prometheusexporter)
- [OTel Collector Prometheus Remote Write Exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/prometheusremotewriteexporter)
- [OTel Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
