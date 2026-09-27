# Снижение объема логов в Grafana Loki: стратегии и практики

## Определения

**Drop Rules (Правила удаления)** — конфигурация pipeline стадий, автоматически удаляющая определенные labels, fields или entire entries перед отправкой в Loki. Снижают объем хранимых данных и стоимость хранения без потери важной информации.

**Log Level (Уровень логов)** — классификация логов по важности: DEBUG, INFO, WARN, ERROR, FATAL. Уровни DEBUG и INFO thường thường составляют 80–90% от общего объема логов и могут быть отфильтрованы в production.

**Sampling (Выборка)** — метод сохранения не всех логов, а их выборочной подмножества. Например, сохранять только 10% от DEBUG логов или каждый 5-й request log. Снижает объем на 50–90% при приемлемом качестве данных.

**Structured Metadata (Структурированные метаданные)** — дополнительные метаданные, передаваемые в Loki без увеличения размера логов. Используются вместо labels для часто меняющихся значений (trace_id, user_id).

**Log Pipeline (Пайплайн логов)** — конфигурация стадий обработки логов на агенте (Alloy/Promtail/Fluent Bit). Включает фильтрацию, трансформацию, обогащение и маршрутизацию перед отправкой в Loki.

**Cardinality (Кардинальность)** — количество уникальных значений labels. Высокая кардинальность (millions of unique label values) приводит к росту индекса и снижению производительности.

---

## Основные концепции

### Архитектура снижения объема

```
┌──────────────────────────────────────────────────────────────┐
│                     Источники логов                           │
│  (приложения, контейнеры, системы)                            │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                     Агент сбора логов                         │
│  (Alloy / Promtail / Fluent Bit)                             │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Drop      │  │   Filter    │  │   Sample    │         │
│  │   Rules     │  │   Rules     │  │   Rules     │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Level     │  │   Label     │  │   Pipeline  │         │
│  │   Filter    │  │   Drop      │  │   Transform │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                     Grafana Loki                              │
│                     (объем снижен на 50–90%)                  │
└──────────────────────────────────────────────────────────────┘
```

### Эффективность стратегий

| Стратегия | Снижение объема | Потеря данных | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Удаление DEBUG логов** | 50–80% | Полная потеря DEBUG | Production с высокой нагрузкой |
| **Удаление INFO логов** | 30–60% | Полная потеря INFO | Только для非常 шумных сервисов |
| **Sampling (10%)** | 80–90% | 90% логов потеряно | Для DEBUG/TRACE логов |
| **Drop labels** | 10–30% | Потеря детализации | Всегда рекомендуется |
| **Drop fields** | 5–20% | Потеря детализации | Для неиспользуемых полей |
| **Structured metadata** | 0% (замена) | Нет потери | Вместо высококардинальных labels |

### Приоритет снижения объема

| Приоритет | Действие | Эффект |
| :--- | :--- | :--- |
| 1 (Высокий) | Удалить DEBUG логи в production | Снижение 50–80% |
| 2 (Высокий) | Удалить высококардинальные labels | Снижение индекса |
| 3 (Средний) | Sampling для TRACE логов | Снижение 80–90% для TRACE |
| 4 (Средний) | Удалить неиспользуемые fields | Снижение 5–20% |
| 5 (Низкий) | Оптимизировать формат логов | Снижение 10–30% |

### Влияние на запросы

| Стратегия | Влияние на LogQL запросы |
| :--- | :--- |
| **Drop DEBUG** | `{level="debug"}` не вернет результатов |
| **Drop labels** | `| label="value"` не будет работать |
| **Sampling** | Метрики (rate, count) будут приблизительными |
| **Drop fields** | `| json | field != ""` не вернет поле |

---

## Практические сценарии

### Сценарий 1: Удаление DEBUG логов (Alloy)

```hcl
// Alloy config: /etc/alloy/config.alloy

// Сбор логов из контейнеров
loki.source.kubernetes "containers" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.process.drop_debug.receiver]
}

// Удаление DEBUG логов
loki.process "drop_debug" {
  forward_to = [loki.write.output.receiver]

  // Удаление DEBUG логов
  stage.drop {
    source = ""
    expression = "^(?s)*(?i)(debug|dbg|trace)\\b"
    older_than = "0s"
  }
}
```

### Сценарий 2: Удаление DEBUG логов (Promtail)

```yaml
# promtail-config.yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: containers
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        target_label: app
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
    pipeline_stages:
      # Удаление DEBUG логов
      - drop:
          expression: "^(?s)*(?i)(debug|dbg|trace)\\b"
          older_than: 0s

      # Удаление неиспользуемых labels
      - label_drop:
          - __meta_kubernetes_pod_label_hash
          - __meta_kubernetes_pod_annotation_hash
          - __meta_kubernetes_pod_uid
          - __meta_kubernetes_pod_name
          - __meta_kubernetes_pod_ip
          - __meta_kubernetes_pod_controller_kind
          - __meta_kubernetes_pod_controller_name

      # Удаление timestamp из body (если есть в логах)
      - regex:
          expression: "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}.*?\\s+(?P<level>\\w+)\\s+(?P<body>.*)$"
      - labels:
          level:
      - output:
          source: body
```

### Сценарий 3: Sampling для DEBUG логов (Alloy)

```hcl
// Alloy config: sampling DEBUG логов (сохраняем 10%)

loki.process "sample_debug" {
  forward_to = [loki.write.output.receiver]

  // Sampling DEBUG логов — сохраняем 10%
  stage.drop {
    source = "level"
    expression = "^(?s)*(?i)(debug|dbg|trace)\\b"
    older_than = "0s"
    percentage = 90  // Удаляем 90% DEBUG логов
  }
}
```

### Сценарий 4: Удаление высококардинальных labels (Alloy)

```hcl
// Alloy config: удаление проблемных labels

loki.process "drop_high_cardinality" {
  forward_to = [loki.write.output.receiver]

  // Удаление labels с высокой кардинальностью
  stage.label_drop {
    values = ["trace_id", "span_id", "user_id", "request_id", "session_id", "correlation_id"]
  }

  // Удаление метаданных Kubernetes
  stage.label_drop {
    values = ["__meta_kubernetes_pod_annotation_prometheus_io_scrape", "__meta_kubernetes_pod_annotation_prometheus_io_port"]
  }

  // Удаление hash labels
  stage.label_drop {
    values = ["__meta_kubernetes_pod_label_hash", "__meta_kubernetes_pod_controller_uid"]
  }
}
```

### Сценарий 5: Pipeline для снижения объема (Alloy)

```hcl
// Полная pipeline для снижения объема логов

loki.process "reduce_volume" {
  forward_to = [loki.write.output.receiver]

  // 1. Удаление DEBUG логов
  stage.drop {
    source = ""
    expression = "^(?s)*(?i)(debug|dbg|trace)\\b"
    older_than = "0s"
  }

  // 2. Удаление высококардинальных labels
  stage.label_drop {
    values = ["trace_id", "span_id", "user_id", "request_id"]
  }

  // 3. Удаление неиспользуемых Kubernetes labels
  stage.label_drop {
    values = ["__meta_kubernetes_pod_label_hash", "__meta_kubernetes_pod_annotation_hash"]
  }

  // 4. Удаление timestamp из body (если дублируется с label)
  stage.regex {
    expression = "^(?P<ts>\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}.*?\\s+)(?P<level>\\w+)\\s+(?P<body>.*)$"
  }

  // 5. Установка level label
  stage.labels {
    values = {
      "level" = "level"
    }
  }

  // 6. Обрезка body (удаление timestamp)
  stage.output {
    source = "body"
  }
}

// Маршрутизация
loki.relabel "drop_debug" {
  forward_to = [loki.process.reduce_volume.receiver]

  rule {
    source_labels = ["level"]
    regex = "(?i)(debug|dbg|trace)"
    action = "drop"
  }
}
```

### Сценарий 6: Удаление неиспользуемых fields из JSON (Alloy)

```hcl
// Удаление неиспользуемых JSON полей

loki.process "drop_fields" {
  forward_to = [loki.write.output.receiver]

  // Парсинг JSON
  stage.json {
    expressions = {
      "level" = "level",
      "message" = "message",
      "timestamp" = "timestamp",
      "service" = "service",
      "trace_id" = "trace_id",
      "span_id" = "span_id",
      "user_agent" = "user_agent",
      "ip_address" = "ip_address",
    }
  }

  // Удаление ненужных полей из body
  stage.template {
    source = "output"
    template = "{{ if .Value.level }}{{ .Value.level }}{{ end }} {{ if .Value.message }}{{ .Value.message }}{{ end }}"
  }
}
```

### Сценарий 7: Мониторинг эффективности снижения объема

**Ключевые метрики:**

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| `loki_distributor_sent_bytes_total` | Объем отправленных данных | Снижение на 50–80% |
| `loki_ingester_memory_streams` | Количество активных streams | Снижение пропорционально |
| `loki_compactor_bytes_processed_total` | Объем обработанных данных компактором | Снижение пропорционально |
| `rate(loki_push_requests_bytes_total[5m])` | Rate отправки байтов | Снижение на 50–80% |

**Прометеус-правила:**

```yaml
groups:
  - name: loki-volume-reduction
    rules:
      - alert: LokiVolumeNotReduced
        expr: |
          rate(loki_push_requests_bytes_total[1h]) > 100 * 1024 * 1024  # > 100 MB/s
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Loki log volume is high"
          description: "Current rate: {{ $value | humanize1024 }}B/s"

      - alert: LokiDebugLogsDetected
        expr: |
          sum(rate({level="debug"} [5m])) > 0
        for: 5m
        labels:
          severity: info
        annotations:
          summary: "DEBUG logs detected in Loki"
          description: "Consider dropping DEBUG logs to reduce volume"
```

**Dashboard в Grafana:**

```logql
// Panel: Log Volume Reduction (Time Series)
sum(rate(loki_push_requests_bytes_total[5m])) by (job)

// Panel: Log Level Distribution (Pie Chart)
sum(count_over_time({job=~".+"} [5m])) by (level)

// Panel: High Cardinality Labels (Table)
topk(10, count by (label_name) (count_over_time({job=~".+"} [5m])))
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **DEBUG логи не удаляются** | Неверное expression в drop | Проверьте regex expression, протестируйте на sample данных |
| **Потеря важных данных** | Слишком агрессивные drop rules | Проверьте что drop не затрагивает критичные логи |
| **Высокая кардинальность сохраняется** | Labels не удалены | Проверьте label_drop конфигурацию |
| **Sampling делает метрики неточными** | Слишком маленький sample rate | Увеличьте sample rate для DEBUG (10–50%) |
| **Pipeline ошибки** | Неверный порядок stage | Проверьте pipeline: drop → label_drop → json → labels |
| **Увеличение latency pipeline** | Слишком много stage | Оптимизируйте pipeline, объедините stage |

---

## Дополнительная информация

### Лучшие практики

1. **Начинайте с удаления DEBUG:** Это дает максимальное снижение объема с минимальной потерей данных.
2. **Мониторьте объем до/после:** Используйте `loki_push_requests_bytes_total` для отслеживания.
3. **Не удаляйте ERROR логи:** Они критичны для troubleshooting.
4. **Используйте sampling для TRACE:** 10–50% от TRACE логов достаточно для аналитики.
5. **Удаляйте высококардинальные labels:** trace_id, span_id, user_id → structured metadata.
6. **Тестируйте drop rules:** Сначала в dev/test, затем в production.
7. **Версионируйте конфигурацию:** Храните drop rules в Git.
8. **Регулярно пересматривайте rules:** Логи меняются, drop rules тоже.

### См. также

- [Обзор Grafana Loki](./loki_overview.md) — архитектура и жизненный цикл данных
- [Установка Alloy](./loki_stack_setup/alloy_installation.md) — конфигурация pipeline
- [Эффективный LogQL](./loki_stack_setup/logql_examples.md) — оптимизация запросов
- [Установка Loki в Kubernetes](./loki_stack_setup/loki_installation.md) — Helm-конфигурация
