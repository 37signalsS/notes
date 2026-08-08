# Grafana Alloy — обзор

## Определения

**Grafana Alloy** — универсальный агент для сбора телеметрии (метрики, логи, трассировки, профили), пришедший на смену Grafana Agent. Построен на базе **OpenTelemetry Collector**, но оптимизирован для работы со стеком LGTM (Loki, Grafana, Tempo, Mimir). Ключевой особенностью является использование декларативного языка конфигурации River.

**River** — язык конфигурации, вдохновленный HCL, который позволяет описывать конвейеры обработки данных (pipelines) в виде направленного графа компонентов. Поддерживает динамическое обновление конфигурации без полной остановки агента.

**OTLP (OpenTelemetry Protocol)** — стандартный протокол, используемый Alloy как основной транспорт для взаимодействия с современными системами наблюдаемости.

### Статус агентов и миграция (SSoT)

| Агент | Статус | Конец поддержки (EOL) |
| :--- | :--- | :--- |
| **Promtail** | Устарело (Deprecated) | Весна 2026 |
| **Grafana Agent (static/flow)** | Устарело (Deprecated) | Октябрь 2025 |
| **Grafana Alloy** | **Актуальный стандарт** | — |

---

## Основные концепции

### Ключевые возможности Alloy

| Возможность | Техническое описание |
| :--- | :--- |
| **Унифицированный сбор** | Заменяет связку `node_exporter`, `promtail` и `otel-collector` одним бинарным файлом. |
| **Компонентная модель (DAG)** | Каждый блок конфигурации — это компонент с входами (arguments) и выходами (exports). |
| **Авто-инструментирование (eBPF)**| Сбор сетевых метрик и трейсов на уровне ядра Linux без изменения кода приложений. |
| **Кластеризация** | Встроенный механизм распределения нагрузки между узлами Alloy для масштабирования сбора данных. |
| **Native Prometheus** | Прямое использование кода Prometheus для сбора (scraping) и релейблинга (relabeling). |
| **Debug UI** | Визуальный интерфейс на порту `12345` для анализа состояния графа и поиска ошибок в реальном времени. |

### Язык конфигурации River

River ориентирован на связность. Вместо глобальных настроек каждый компонент явно указывает, куда передавать данные через аргумент `forward_to`.

**Пример архитектуры пайплайна (сбор логов):**

```hcl
// 1. Обнаружение локальных лог-файлов
discovery.file "local_files" {
  path_targets = [{
    __path__ = "/var/log/*.log",
  }]
}

// 2. Чтение обнаруженных файлов
loki.source.file "local_logs" {
  targets = discovery.file.local_files.targets
  forward_to = [loki.write.to_loki_cloud.receiver]
}

// 3. Отправка логов в Loki
loki.write "to_loki_cloud" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
  external_labels = {
    source = "grafana-alloy",
  }
}
```

### Высокая доступность и масштабирование

Alloy поддерживает **Clustering** — режим, в котором несколько экземпляров агента объединяются в логический кластер. Это позволяет:
- **Распределять цели сбора (Scrape Targets)**: каждый узел берет на себя часть нагрузки.
- **Обеспечивать отказоустойчивость**: при падении одного узла его цели перераспределяются между оставшимися.
- **Контролировать состояние**: через компонент `cluster.enabled = true` в конфигурации.

---

## Практические сценарии

### Сценарий 1: Использование eBPF для сетевой наблюдаемости

Компонент `otelcol.receiver.ebpf` позволяет получать данные о задержках и сетевых соединениях без внесения изменений в приложение.

```hcl
otelcol.receiver.ebpf "network_telemetry" {
  network_interface = "eth0"
  output {
    traces  = [otelcol.exporter.otlp.tempo.input]
    metrics = [otelcol.exporter.prometheus.mimir.input]
  }
}
```

### Сценарий 2: Full-Stack Observability для PostgreSQL

Комплексный пример сбора всех сигналов от БД и приложения, их корреляция через `trace_id`.

```hcl
// --- 1. Сбор трейсов ---
otelcol.receiver.otlp "traces_receiver" {
  grpc { endpoint = "0.0.0.0:4317" }
  output { traces = [otelcol.exporter.otlp.traces_exporter.input] }
}

otelcol.exporter.otlp "traces_exporter" {
  client { endpoint = "tempo:4317"; tls { insecure = true } }
}

// --- 2. Сбор логов с извлечением trace_id ---
discovery.file "log_files" {
  path_targets = [{
    __path__ = "/var/lib/postgresql/data/log/postgresql.log",
    "job" = "postgres-logs",
  }]
}

loki.source.file "read_logs" {
  targets = discovery.file.log_files.targets
  forward_to = [loki.process.add_trace_id.receiver]
}

loki.process "add_trace_id" {
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

// --- 3. Сбор метрик ---
prometheus.scrape "postgres_metrics" {
  targets = [{ "__address__" = "postgres_exporter:9187", "job" = "postgres" }]
  forward_to = [prometheus.remote_write.mimir.receiver]
}

prometheus.remote_write "mimir" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

### Сценарий 3: Миграция с помощью встроенного конвертера

Alloy включает инструменты для быстрого перехода с устаревших агентов.

1. **Конвертация:**
   ```bash
   alloy convert --source-format=promtail --output=config.alloy promtail-config.yaml
   ```
2. **Проверка:** Запустите Alloy с флагом `--dry-run`, чтобы убедиться в валидности графа перед деплоем.

---

## Дополнительная информация

### Сравнение Alloy и OpenTelemetry Collector

| Характеристика | Grafana Alloy | OTel Collector (Upstream) |
| :--- | :--- | :--- |
| **Язык** | River (Динамический граф) | YAML (Статический стек) |
| **Сбор метрик** | Нативный код Prometheus (Scrape/Relabel) | `prometheusreceiver` (Legacy/Contrib) |
| **Фокус** | Экосистема Grafana + OTel | Универсальный стандарт |
| **Отладка** | Потоковая визуализация в UI | Текстовые логи и метрики |

### Преимущества и ограничения

#### Преимущества
- **Консолидация:** уменьшение количества агентов на хосте снижает нагрузку на CPU/RAM и упрощает патчинг.
- **Прозрачность:** Debug UI позволяет мгновенно увидеть, почему метрика не дошла до хранилища (фильтрация или ошибка соединения).
- **Готовность к будущему:** Alloy является фундаментом для технологий **Adaptive Metrics** и **Profiles-to-Traces**.

#### Ограничения
- **Порог входа:** River требует обучения и понимания принципов экспорта/импорта данных между компонентами.
- **Потребление ресурсов:** в очень простых сценариях (только сбор логов) Alloy может быть тяжелее, чем Promtail.

### Актуальность и ссылки

Информация актуальна на **август 2026 года**. Основные направления развития: глубокая интеграция с **Grafana Alloy Operator** в Kubernetes и поддержка **OpenTelemetry Profiles**.

- [Официальный репозиторий GitHub](https://github.com/grafana/alloy)
- [Документация по компонентам River](https://grafana.com/docs/alloy/latest/reference/components/)
- [Установка в Kubernetes](../Loki/loki_stack_setup/alloy_installation.md)

**См. также:** [Обзор Grafana](./grafana_overview.md), [Источники данных](./grafana_datasources.md), [OpenTelemetry Collector](../OpenTelemetry/opentelemetry_overview.md).
