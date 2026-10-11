# Миграция с ELK на Grafana Loki

## Определения

**ELK Stack (Elasticsearch, Logstash, Kibana)** — стек для сбора, индексации и визуализации логов. Elasticsearch хранит и индексирует данные, Logstash обрабатывает и маршрутизирует, Kibana предоставляет UI для поиска и анализа. Требует значительных ресурсов RAM для индексации.

**Loki (Grafana Loki)** — lightweight alternative to ELK, использующая только labels для индексации. Хранит сырые логи в объектном хранилище (S3/GCS), что снижает стоимость хранения в 5–10 раз. Использует LogQL вместо KQL/Lucene.

**Logstash** — инструмент обработки логов с pipeline input → filter → output. Поддерживает丰富的 плагины для парсинга, обогащения и маршрутизации. Заменяется на Alloy/Promtail/Fluent Bit.

**Elasticsearch** — поисковый движок с полнотекстовым индексированием. Требует значительных ресурсов RAM (JVM heap). Индексирует каждый лог целиком, что делает его дорогим для больших объемов.

**Kibana** — UI для Elasticsearch с поддержкой поиска, агрегации и визуализации. Заменяется на Grafana.

**Fluent Bit** — lightweight collector, поддерживаемый cả ELK и Loki. Используется как dual-write агент во время миграции.

---

## Основные концепции

### Архитектура ELK vs Loki

```
ELK Stack:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Файлы     │────▶│  Logstash   │────▶│Elasticsearch│────▶│   Kibana    │
│   логов     │     │  (фильтр)  │     │ (хранилище) │     │   (UI)      │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      RAM: Нет         RAM: Среднее        RAM: Высокое         RAM: Низкое
      CPU: Низкое      CPU: Среднее        CPU: Высокое         CPU: Низкое
      Стоимость: $     Стоимость: $$      Стоимость: $$$       Стоимость: $

Loki Stack:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Файлы     │────▶│   Alloy     │────▶│    Loki     │────▶│  Grafana    │
│   логов     │     │  (фильтр)  │     │ (хранилище) │     │   (UI)      │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      RAM: Нет         RAM: Низкое         RAM: Среднее         RAM: Низкое
      CPU: Низкое      CPU: Низкое         CPU: Среднее         CPU: Низкое
      Стоимость: $     Стоимость: $       Стоимость: $$        Стоимость: $
```

### Сравнение ELK и Loki

| Критерий | ELK Stack | Grafana Loki |
| :--- | :--- | :--- |
| **Стоимость хранения** | Высокая (Elasticsearch) | Низкая (S3/GCS) |
| **Скорость поиска** | Мгновенно (indexed) | Зависит от volume (indexed labels only) |
| **Полнотекстовый поиск** | Встроенный | Только через grep |
| **Cardinality labels** | Не ограничена | Ограничена (index only) |
| **Ресурсы RAM** | Высокие (JVM heap) | Средние |
| **Сложность настройки** | Высокая | Средняя |
| **Готовые дашборды** | Kibana | Grafana |
| **Кластеризация** | Сложная | Простая |
| **Backup/Restore** | Сложный | Простой (S3 versioning) |

### Этапы миграции

```
1. Подготовка (1-2 недели)
   ├── Установка Loki + Grafana
   ├── Настройка Alloy/Promtail
   └── Тестирование LogQL запросов

2. Dual-Write (2-4 недели)
   ├── Alloy пишет в ELK и Loki одновременно
   ├── Сравнение данных
   └── Оптимизация pipeline

3. Миграция по сервисам (2-4 недели)
   ├── Миграция по 1-2 сервиса в неделю
   ├── Мониторинг
   └── Обучение команды

4. Завершение (1-2 недели)
   ├── Отключение ELK
   ├── Очистка данных
   └── Документация
```

### Ключевые отличия LogQL от KQL/Lucene

| ELK (KQL/Lucene) | Loki (LogQL) | Описание |
| :--- | :--- | :--- |
| `message:"error"` | `{app="nginx"} \|= "error"` | Поиск по тексту |
| `level:error` | `{level="error"}` | Поиск по label |
| `response_time > 1000` | `{app="nginx"} \| json \| response_time > 1000` | Поиск по числовому полю |
| `*` (all fields) | `{app=~".+"}` | Поиск по всем |
| `AND`, `OR` | `\|~ "error\|warn"` | Комбинирование условий |
| `range:[now-1h TO now]` | `{app="nginx"} [1h]` | Временной диапазон |

---

## Практические сценарии

### Сценарий 1: Установка Loki + Grafana (baseline)

```bash
# Docker Compose для baseline
mkdir -p /opt/loki-migration
cd /opt/loki-migration

cat > docker-compose.yaml << 'EOF'
services:
  loki:
    image: grafana/loki:3.4.2
    container_name: loki
    ports:
      - "3100:3100"
    volumes:
      - ./loki-config.yaml:/etc/loki/local-config.yaml
      - loki-data:/loki
    command: -config.file=/etc/loki/local-config.yaml

  grafana:
    image: grafana/grafana:11.5.2
    container_name: grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-data:/var/lib/grafana

  alloy:
    image: grafana/alloy:v1.7.3
    container_name: alloy
    ports:
      - "12345:12345"
    volumes:
      - ./alloy-config.yaml:/etc/alloy/config.alloy
    command: run --storage.path=/tmp/alloy-storage --stability.level=generally-available /etc/alloy/config.alloy

volumes:
  loki-data:
  grafana-data:
EOF

cat > loki-config.yaml << 'EOF'
auth_enabled: false
server:
  http_listen_port: 3100
common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory
schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
limits_config:
  retention_period: 30d
compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
  retention_enabled: true
EOF

cat > alloy-config.yaml << 'EOF'
discovery.kubernetes "pods" {
  role = "pod"
}

loki.source.kubernetes "pods" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.write.output.receiver]
}

loki.write "output" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
EOF

docker compose up -d
```

### Сценарий 2: Dual-Write (Alloy → ELK + Loki)

```hcl
// Alloy config: dual-write в ELK и Loki

// Сбор логов из контейнеров
loki.source.kubernetes "containers" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.process.reduce_volume.receiver]
}

// Снижение объема перед отправкой
loki.process "reduce_volume" {
  forward_to = [loki.write.output.receiver]

  // Удаление DEBUG логов
  stage.drop {
    source = ""
    expression = "^(?s)*(?i)(debug|dbg|trace)\\b"
    older_than = "0s"
  }

  // Удаление высококардинальных labels
  stage.label_drop {
    values = ["trace_id", "span_id", "user_id", "request_id"]
  }
}

// Запись в Loki
loki.write "output" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}

// Параллельная запись в ELK (через HTTP)
loki.write "elk" {
  endpoint {
    url = "http://logstash:5044"  // Logstash HTTP input
  }
}
```

**Logstash конфигурация для dual-write:**

```ruby
# logstash.conf
input {
  http {
    port => 5044
    codec => json
  }
}

filter {
  # Парсинг JSON логов
  if [message] =~ /^\{/ {
    json {
      source => "message"
      target => "parsed"
    }
  }

  # Установка level из parsed поля
  if [parsed][level] {
    mutate {
      add_field => { "level" => "%{[parsed][level]}" }
    }
  }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "logs-%{{yyyy.MM.dd}}"
  }
}
```

### Сценарий 3: Миграция по сервисам

```bash
# Шаг 1: Миграция nginx (простой сервис)
# alloy-config-nginx.hcl

loki.source.kubernetes "nginx" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.process.nginx.receiver]

  // Фильтрация по namespace
  selector = "namespace == 'production' && app == 'nginx'"
}

loki.process "nginx" {
  forward_to = [loki.write.output.receiver]

  // Парсинг JSON
  stage.json {
    expressions = {
      "level" = "level",
      "message" = "message",
      "status" = "status",
      "method" = "method",
      "path" = "path",
    }
  }

  // Установка labels
  stage.labels {
    values = {
      "level" = "level"
      "status" = "status"
      "method" = "method"
    }
  }
}
```

```bash
# Шаг 2: Миграция application (сложный сервис)
# alloy-config-app.hcl

loki.source.kubernetes "app" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.process.app.receiver]

  selector = "namespace == 'production' && app == 'myapp'"
}

loki.process "app" {
  forward_to = [loki.write.output.receiver]

  // Парсинг JSON
  stage.json {
    expressions = {
      "level" = "level",
      "message" = "message",
      "service" = "service",
      "trace_id" = "trace_id",
    }
  }

  // Установка labels
  stage.labels {
    values = {
      "level" = "level"
      "service" = "service"
    }
  }

  // Удаление trace_id (высокая кардинальность)
  stage.label_drop {
    values = ["trace_id"]
  }
}
```

### Сценарий 4: Конвертация KQL → LogQL

| KQL (Elasticsearch) | LogQL (Loki) | Описание |
| :--- | :--- | :--- |
| `message:"error"` | `{app="nginx"} \|= "error"` | Поиск по тексту |
| `level:error AND message:"timeout"` | `{app="nginx", level="error"} \|= "timeout"` | AND условие |
| `level:error OR level:warn` | `{app="nginx"} \|= "error" \|= "warn"` | OR условие |
| `response_time:>1000` | `{app="nginx"} \| json \| response_time > 1000` | Числовое сравнение |
| `user_agent:*Chrome*` | `{app="nginx"} \| json \| user_agent =~ ".*Chrome.*"` | Regex поиск |
| `status:[200 TO 299]` | `{app="nginx"} \| json \| status >= 200 and status < 300` | Диапазон |
| `NOT message:"health"` | `{app="nginx"} != "health"` | Исключение |

### Сценарий 5: Миграция дашбордов Kibana → Grafana

```logql
// Kibana: Log Rate (per second)
// rate(index="logs", interval=1m, filter="level:error")

// Loki: Log Rate (per second)
sum(rate({app="nginx", level="error"} [1m]))

// Kibana: Top 10 Error Messages
// terms(message, size=10, order="desc", filter="level:error")

// Loki: Top 10 Error Messages
topk(10, sum by (message) (count_over_time({app="nginx", level="error"} [5m])))

// Kibana: Response Time Distribution
// histogram(response_time, interval=100, filter="status:200")

// Loki: Response Time Distribution
{app="nginx"} | json | line_format "{{.status}} {{.response_time}}"

// Kibana: Errors by Status Code
// terms(status, size=10, filter="level:error")

// Loki: Errors by Status Code
sum by (status) (count_over_time({app="nginx"} |= "error" [5m]))
```

### Сценарий 6: Валидация данных после миграции

```bash
# Сравнение количества логов
# ELK:
curl -s "http://elasticsearch:9200/logs-*/_count" | jq '.count'

# Loki:
curl -s "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode "query=sum(count_over_time({app=\"nginx\"}[24h]))" | jq '.data.result[0].value[1]'

# Сравнение распределения level
# ELK:
curl -s "http://elasticsearch:9200/logs-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "aggs": {
      "levels": {
        "terms": { "field": "level.keyword", "size": 10 }
      }
    }
  }' | jq '.aggregations.levels.buckets'

# Loki:
curl -s "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode "query=sum by (level) (count_over_time({app=\"nginx\"}[24h]))" | jq '.data.result'

# Проверка sample логов
# ELK:
curl -s "http://elasticsearch:9200/logs-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 5,
    "sort": [{"@timestamp": {"order": "desc"}}]
  }' | jq '.hits.hits[]._source'

# Loki:
curl -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode "query={app=\"nginx\"}" \
  --data-urlencode "limit=5" | jq '.data.result[0].values'
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Данные не появляются в Loki** | Alloy не отправляет | Проверьте `alloy config test`, логи Alloy |
| **Дублирование данных** | Dual-write не отключен | Отключите ELK pipeline после валидации |
| **Разные результаты запросов** | Разные pipeline/filters | Сравните pipeline: ELK vs Loki |
| **Высокая кардинальность** | Labels не оптимизированы | Удалите trace_id, span_id из labels |
| **Медленные запросы** | Нет индексации по тексту | Используйте grep (`\|= "keyword"`) |
| **Grafana не показывает данные** | Datasource не настроен | Добавьте Loki datasource в Grafana |
| **Нет level labels** | Pipeline не настроен | Добавьте stage.labels для level |

---

## Дополнительная информация

### Лучшие практики

1. **Dual-write перед миграцией:** Всегда используйте dual-write для валидации данных.
2. **Миграция по сервисам:** Не мигрируйте все сразу — по 1-2 сервиса в неделю.
3. **Обучение команды:** Обучите команду LogQL перед миграцией.
4. **Валидация данных:** Сравнивайте количество логов, распределение level, sample данные.
5. **Backup ELK:** Сохраняйте ELK 30 дней после миграции.
6. **Документация:** Запишите pipeline, labels, retention policies.
7. **Мониторинг:** Настройте алерты на volume, errors, latency.
8. **Постепенное отключение:** Отключайте ELK по сервисам, не все сразу.

### См. также

- [Обзор Grafana Loki](./loki_overview.md) — архитектура и жизненный цикл данных
- [ELK Stack Overview](../ELK_Stack/elk_stack_overview.md) — сравнение архитектур
- [Установка Alloy](./loki_stack_setup/alloy_installation.md) — конфигурация pipeline
- [Эффективный LogQL](./loki_stack_setup/logql_examples.md) — паттерны запросов
- [Снижение объема логов](./loki_log_volume_reduction.md) — оптимизация storage
