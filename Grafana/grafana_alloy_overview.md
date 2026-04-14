# Grafana Alloy

## Определения

**Grafana Alloy** — флагманский агент Grafana Labs для унифицированного сбора телеметрии (метрики, логи, трейсы, профили). Основан на [OpenTelemetry Collector](../OpenTelemetry/opentelemetry_overview.md), использует язык конфигурации River.

**River** — язык конфигурации на базе HCL (HashiCorp Configuration Language) для описания потоков данных в виде графа компонентов.

**Связанные темы:**

- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Источники данных](./grafana_datasources.md) — настройка подключения к бэкендам
- [Провижининг](./grafana_provisioning.md) — автоматизация конфигурации Grafana
- [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md) — стандарт телеметрии

### Миграция с устаревших агентов

| Агент | Статус | Конец поддержки |
| :--- | :--- | :--- |
| **Grafana Agent (static mode)** | ⚠️ Deprecated | — |
| **Promtail** | ⚠️ Deprecated | — |
| **Grafana Alloy** | ✅ Активно развивается | — |

## Основные концепции

### Ключевые особенности Alloy

| Особенность | Описание |
| :--- | :--- |
| **Унификация** | Единый агент для метрик, логов, трейсов, профилей |
| **Компонентная модель** | Конфигурация на River (граф компонентов) |
| **Совместимость** | Prometheus, Loki, OpenTelemetry Collector |
| **Обработка данных** | Трансформация, фильтрация, обогащение |
| **Отладочный UI** | Встроенный веб-интерфейс для инспекции |
| **Масштабирование** | Горизонтальное масштабирование, кластерный режим |

### Язык конфигурации River

River (диалект HCL) описывает конфигурацию Alloy как граф компонентов. Выход одного компонента является входом для другого, что обеспечивает наглядность и переиспользуемость.

**Пример конфигурации River (сбор логов в Loki):**

```hcl
// Обнаружение локальных лог-файлов
discovery.file "local_files" {
  path_targets = [{
    __path__ = "/var/log/*.log",
  }]
}

// Чтение обнаруженных файлов
loki.source.file "local_logs" {
  targets = discovery.file.local_files.targets
  forward_to = [loki.write.to_loki_cloud.receiver]
}

// Отправка логов в Loki
loki.write "to_loki_cloud" {
  endpoint {
    url = "https://loki-prod-us-central-0.grafana.net/loki/api/v1/push"
  }
  external_labels = {
    source = "grafana-alloy",
  }
}
```

В этом примере: `discovery.file` находит файлы, `loki.source.file` их читает, а `loki.write` отправляет в Loki. Связь `forward_to` явно определяет поток данных.

## Практические сценарии

### Сценарий 1: Миграция на Grafana Alloy

Alloy включает встроенные конвертеры для упрощения перехода с устаревших агентов:

- Конвертация конфигураций **Promtail** в формат Alloy.
- Конвертация конфигураций **Grafana Agent** в формат Alloy.
- Конвертация `scrape_configs` **Prometheus** для использования Alloy в качестве скрапера метрик.
- Использование Alloy как замены **OpenTelemetry Collector**.

### Сценарий 2: Full-Stack Observability для PostgreSQL

Пример показывает сбор метрик, логов и трассировок от PostgreSQL и связанных приложений с помощью Alloy, их обогащение и отправку в Mimir/Prometheus, Loki и Tempo.

**Цель**:

1. Сбор метрик с `postgres_exporter`.
2. Сбор трейсов от приложения и `pg_tracing` через OTLP.
3. Сбор логов из `postgresql.log`.
4. Обогащение логов извлеченным `trace_id` для корреляции с трейсами.
5. Отправка данных в соответствующие бэкенды.

**Конфигурация Grafana Alloy (`alloy.conf`):**

```hcl
// --- 1. СБОР ТРЕЙСОВ ---
otelcol.receiver.otlp "traces_receiver" {
  grpc {}
  http {}
  output { traces = [otelcol.exporter.otlp.traces_exporter.input] }
}

otelcol.exporter.otlp "traces_exporter" {
  client {
    endpoint = "tempo:4317" // Адрес Tempo
    tls { insecure = true }
  }
}

// --- 2. СБОР ЛОГОВ ---
discovery.file "log_files" {
  path_targets = [{
    __path__ = "/var/lib/postgresql/data/log/postgresql.log",
    "host" = "postgresql", "job" = "postgres-logs",
  }]
}

loki.source.file "read_logs" {
  targets = discovery.file.log_files.targets
  forward_to = [loki.process.add_trace_id.receiver]
}

loki.process "add_trace_id" {
  stage.match {
    selector = `{job="postgres-logs"}`
    stages = [{ pipeline_name = "extract_trace_id", expression = ".*traceparent.*" }]
  }
  stage.regex {
    expression = ".*traceparent='00-(?P<trace_id>[a-f0-9]{32})-[a-f0-9]{16}-01'.*"
    source     = "log_line"
  }
  stage.label_drop {
    values = { "trace_id" = `^(?P<value>.*)$` }
    target_label = "traceID"
  }
  forward_to = [loki.write.loki_writer.receiver]
}

loki.write "loki_writer" {
  endpoint { url = "http://loki:3100/loki/api/v1/push" }
}

// --- 3. СБОР МЕТРИК ---
prometheus.scrape "postgres_exporter_scrape" {
  targets = [{
    "__address__" = "postgres_exporter:9187",
    "job" = "postgres-metrics",
  }]
  forward_to = [prometheus.remote_write.metrics_writer.receiver]
}

prometheus.remote_write "metrics_writer" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

**Поток данных:**

- **Трейсы**: Принимаются по OTLP (`otelcol.receiver.otlp`) и отправляются в Tempo (`otelcol.exporter.otlp`).
- **Логи**: Читаются (`loki.source.file`), обогащаются `trace_id` (`loki.process`) и отправляются в Loki (`loki.write`).
- **Метрики**: Скрапятся с `postgres_exporter` (`prometheus.scrape`) и отправляются в Mimir/Prometheus (`prometheus.remote_write`).

## Дополнительная информация

### Сравнение Alloy с OpenTelemetry Collector

| Характеристика | Grafana Alloy | OpenTelemetry Collector |
| :--- | :--- | :--- |
| **Язык конфигурации** | River (HCL) | YAML |
| **Интеграция** | Встроенный код Prometheus/Promtail | Требует внешних компонентов |
| **Фокус** | Экосистема Grafana (Loki, Mimir, Tempo) | Универсальный, любые OTel-бэкенды |
| **Сообщество** | Менее зрелое | Большое сообщество |

### Преимущества и ограничения

#### Преимущества

- **Унификация** — единый агент для всех типов телеметрии
- **Масштабируемость** — горизонтальное масштабирование, кластерный режим
- **Миграция** — встроенные конвертеры конфигураций Promtail/Grafana Agent
- **Стандартизация** — основан на OpenTelemetry

#### Ограничения

- **Новизна** — менее зрелая документация и сообщество
- **Зависимость** — развитие определяется Grafana Labs
- **Компоненты** — меньше встроенных компонентов vs FluentBit/Vector

### Актуальность информации

Информация актуальна на 2026 год. Статус агентов:

- **Promtail** — deprecated (весна 2026), миграция через [конвертер конфигураций](https://grafana.com/docs/alloy/latest/tasks/migrate/)
- **Grafana Agent (static mode)** — deprecated (ноябрь 2025)
- **Grafana Alloy** — активно развивается

Подробная [документация Alloy](https://grafana.com/docs/alloy/latest/) и [сравнение с OTel Collector](https://grafana.com/docs/alloy/latest/concepts/compare/) доступны на сайте Grafana Labs.
