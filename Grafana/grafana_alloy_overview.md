# Grafana Alloy — обзор

## Определения

**Grafana Alloy** — флагманский агент Grafana Labs для унифицированного сбора телеметрии (метрики, логи, трейсы, профили). Основан на **OpenTelemetry Collector** (OTel Collector), использует декларативный язык конфигурации River.

**River** — язык конфигурации на базе HCL (HashiCorp Configuration Language) для описания потоков данных в виде графа компонентов. Позволяет динамически изменять конфигурацию без перезапуска агента.

**OTLP (OpenTelemetry Protocol)** — стандартный протокол передачи данных телеметрии, который Alloy использует как для приема, так и для отправки данных.

### Статус агентов и миграция

| Агент | Статус | Конец поддержки (EOL) |
| :--- | :--- | :--- |
| **Promtail** | Устарело (Deprecated) | Весна 2026 |
| **Grafana Agent (static mode)** | Устарело (Deprecated) | Ноябрь 2025 |
| **Grafana Alloy** | **Актуально** | — |

## Основные концепции

### Ключевые особенности Alloy

| Особенность | Описание |
| :--- | :--- |
| **Унификация** | Единый агент для всех типов сигналов: метрик, логов, трейсов и профилей. |
| **Компонентная модель** | Конфигурация в виде направленного графа (DAG), где выход одного компонента — вход для другого. |
| **Совместимость** | Полная поддержка экосистемы Prometheus, Loki, Tempo, Pyroscope и OpenTelemetry. |
| **Обработка данных** | Мощные инструменты фильтрации, релейблинга (relabeling) и трансформации данных на лету. |
| **Отладочный UI** | Встроенный веб-интерфейс (порт 12345 по умолчанию) для визуализации графа и инспекции состояния компонентов. |
| **Масштабирование** | Поддержка кластерного режима для распределения нагрузки и обеспечения отказоустойчивости. |

### Язык конфигурации River

River (диалект HCL) ориентирован на связность компонентов. Это избавляет от дублирования настроек и делает поток данных (pipeline) прозрачным.

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
    url = "http://loki:3100/loki/api/v1/push"
  }
  external_labels = {
    source = "grafana-alloy",
  }
}
```

В этом примере: `discovery.file` находит файлы, `loki.source.file` их читает, а `loki.write` отправляет в Loki. Связь `forward_to` явно определяет конвейер обработки.

## Практические сценарии

### Сценарий 1: Миграция на Grafana Alloy

Alloy предоставляет инструменты для автоматической конвертации устаревших конфигураций. Команда `alloy convert` позволяет перевести существующие файлы в формат River:

- **Promtail:** конвертация YAML-пайплайнов в компоненты `loki.process`.
- **Grafana Agent:** миграция со статического режима в компонентную модель.
- **Prometheus:** преобразование `scrape_configs` в `prometheus.scrape`.
- **OTel Collector:** адаптация конфигураций OpenTelemetry для работы в среде Alloy.

### Сценарий 2: Full-Stack Observability для PostgreSQL

Комплексный пример сбора всех типов телеметрии от базы данных и приложения, их корреляция через `trace_id` и отправка в стек LGTM (Loki, Grafana, Tempo, Mimir).

**Конфигурация Grafana Alloy (`config.alloy`):**

```hcl
// --- 1. Сбор трейсов (Tracing) ---
otelcol.receiver.otlp "traces_receiver" {
  grpc {
    endpoint = "0.0.0.0:4317"
  }
  http {
    endpoint = "0.0.0.0:4318"
  }
  output { traces = [otelcol.exporter.otlp.traces_exporter.input] }
}

otelcol.exporter.otlp "traces_exporter" {
  client {
    endpoint = "tempo:4317"
    tls { insecure = true }
  }
}

// --- 2. Сбор логов (Logging) ---
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

// --- 3. Сбор метрик (Metrics) ---
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

**Логика работы:**
1. **Трейсы:** принимаются по протоколу OTLP и экспортируются в Tempo.
2. **Логи:** читаются с диска, парсятся регулярным выражением для извлечения `trace_id`, после чего отправляются в Loki с прикрепленным ID для сквозной навигации.
3. **Метрики:** собираются с экспортера и отправляются в Mimir через Remote Write.

## Дополнительная информация

### Сравнение Alloy и OpenTelemetry Collector

| Характеристика | Grafana Alloy | OpenTelemetry Collector |
| :--- | :--- | :--- |
| **Язык конфигурации** | River (HCL) — динамический, DAG-ориентированный | YAML — статический |
| **Библиотеки** | Нативный код Prometheus и Promtail | Сообщество/Contrib репозитории |
| **Фокус** | Оптимизация под Grafana Cloud и LGTM Stack | Максимальная универсальность |
| **Интерфейс** | Богатый UI для отладки графа | Ограниченная телеметрия самого коллектора |

### Преимущества и ограничения

#### Преимущества
- **Гибкость:** замена классических агентов (Promtail, Agent) одним бинарным файлом.
- **Прозрачность:** отладочный UI позволяет видеть, на каком этапе «застряли» или отфильтровались данные.
- **Современность:** нативная поддержка OTLP и профилирования (Pyroscope).

#### Ограничения
- **Кривая обучения:** River требует привыкания после YAML.
- **Ресурсоемкость:** в сложных конфигурациях с большим количеством компонентов потребление памяти выше, чем у специализированных агентов.

### Актуальность и ссылки

Информация актуальна на **июль 2026 года**. Основные направления развития Alloy: расширение поддержки eBPF для авто-инструментирования и углубленная интеграция с сервисными сетками (Service Mesh).

- [Официальная документация Grafana Alloy](https://grafana.com/docs/alloy/latest/)
- [Установка Alloy в Kubernetes](../Loki/loki_stack_setup/alloy_installation.md)
- [Конвертер конфигураций](https://grafana.com/docs/alloy/latest/tasks/migrate/)

**См. также:** [Обзор Grafana](./grafana_overview.md), [Источники данных](./grafana_datasources.md), [OpenTelemetry Collector](../OpenTelemetry/opentelemetry_overview.md).
