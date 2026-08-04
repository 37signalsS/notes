# Агентный сбор логов Docker

## Определения

**Агентный сбор логов (Agent-based Logging)** — архитектурный подход, при котором сбор, обработка и отправка телеметрии выполняются специализированным приложением (агентом), работающим независимо от Docker Engine.

**Node-агент** — экземпляр агента, запущенный на каждом хосте (в контейнере или как системный сервис), который собирает логи всех контейнеров данного узла. Это наиболее эффективный и масштабируемый метод для Docker-сред.

**Sidecar-агент** — запуск агента в отдельном контейнере рядом с конкретным приложением. Используется редко, обычно для изоляции критических сервисов или при отсутствии доступа к файловой системе хоста.

## Базовые концепции

Основная идея — разделение ответственности (Decoupling). Docker Engine отвечает за работу контейнеров и запись их `STDOUT/STDERR` в локальные файлы, а агент — за чтение этих файлов, их парсинг, обогащение метаданными и доставку в систему хранения.

**Схема работы:**
`Приложение → STDOUT/STDERR → Docker Engine (json-file driver) → Локальный диск (/var/lib/docker/containers/) → Агент → Сеть → Система хранения`

### Механизмы сбора: Файлы vs API

Агенты могут собирать логи двумя способами:
1.  **Прямое чтение файлов (Tail)**: Агент монтирует `/var/lib/docker/containers/` и читает файлы напрямую. Это максимально производительный метод, не нагружающий Docker API.
2.  **Docker API (Events/Logs)**: Агент подключается к `/var/run/docker.sock` и получает поток логов через вызовы API. Это проще в настройке прав доступа, но создает нагрузку на Docker Engine при больших объемах данных.

### Чекпоинты (Checkpointing) и надежность

Для предотвращения потери данных и дубликатов агенты используют **позиционные файлы (checkpoints)**.
*   **Механизм**: Агент записывает смещение (offset) последнего прочитанного байта каждого файла на персистентный диск.
*   **Отказоустойчивость**: После перезагрузки агента или хоста чтение возобновляется строго с места остановки.
*   **Важно**: Позиционные файлы необходимо выносить на Volume хоста, иначе при пересоздании контейнера агента он начнет читать все логи заново.

### Преимущества агентного подхода

- **Надежность**: Локальная буферизация на диске (средствами Docker Engine) позволяет переживать сбои сети или временную недоступность хранилища.
- **Гибкость**: Возможность сложной обработки (парсинг JSON, маскирование паролей, фильтрация ненужных логов) до их отправки в сеть.
- **Метаданные**: Автоматическое добавление меток (имя контейнера, образ, лейблы, ID) через интеграцию с Docker API.

## Практические сценарии

### Сценарий 1: Использование Fluentd в качестве агента

Fluentd остается стандартом для сложных энтерпрайз-решений благодаря огромному количеству плагинов.

**Пример `docker-compose.yml` для Node-агента:**
```yaml
services:
  fluentd:
    image: fluent/fluentd:v1.19.3-debian-1
    volumes:
      # Чтение логов и сокета для метаданных
      - /var/lib/docker/containers:/fluentd/log/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      # Сохранение позиции чтения (checkpoints)
      - ./fluentd/pos:/fluentd/pos
      - ./fluentd/conf:/fluentd/etc:ro
    user: root # Требуется для доступа к логам Docker
```

**Пример конфигурации `fluent.conf` с парсингом JSON:**
```conf
<source>
  @type tail
  path /fluentd/log/containers/*/*-json.log
  pos_file /fluentd/pos/docker-logs.pos
  tag docker.*
  <parse>
    @type json
    time_format %Y-%m-%dT%H:%M:%S.%NZ
  </parse>
</source>

<filter docker.**>
  @type record_transformer
  <record>
    container_id ${tag_parts[2]}
    node_name "#{Socket.gethostname}"
  </record>
</filter>

<match docker.**>
  @type elasticsearch
  host "elasticsearch:9200"
  logstash_format true
  flush_interval 5s
</match>
```

### Сценарий 2: Использование Filebeat (Elastic Stack)

Filebeat — максимально простое решение, если вы используете ELK.

**Пример конфигурации `filebeat.yml`:**
```yaml
filebeat.inputs:
- type: container
  paths:
    - '/var/lib/docker/containers/*/*.log'
  # Автоматическое определение формата (json-file)
  stream: all

processors:
  - add_docker_metadata:
      host: "unix:///var/run/docker.sock"
  - decode_json_fields:
      fields: ["message"]
      target: "data"

output.logstash:
  hosts: ["logstash:5044"]
```

### Сценарий 3: Использование Grafana Alloy (рекомендуется для Loki)

В 2026 году Alloy — стандарт для стека Grafana, объединяющий возможности Promtail и OTel.

**Пример `config.alloy`:**
```alloy
// Обнаружение контейнеров
discovery.docker "local" {
  host = "unix:///var/run/docker.sock"
}

// Сбор логов
loki.source.docker "logs" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.docker.local.targets
  forward_to = [loki.process.main.receiver]
}

// Обработка
loki.process "main" {
  stage.docker { } // Извлечение стандартных метаданных
  forward_to = [loki.write.loki_backend.receiver]
}

loki.write "loki_backend" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

### Сценарий 4: Использование Vector (максимальная производительность)

Vector (написан на Rust) потребляет в 10 раз меньше ресурсов, чем Fluentd.

**Пример `vector.yaml`:**
```yaml
sources:
  docker:
    type: docker_logs # Сбор через Docker API (событийно)

transforms:
  process:
    type: remap
    inputs: [docker]
    source: |
      . = parse_json!(.message)
      .app_name = .container_name

sinks:
  loki:
    type: loki
    inputs: [process]
    endpoint: "http://loki:3100"
    labels:
      container: "{{ container_name }}"
```

### Работа с многострочными логами (Multiline)

Одна из главных задач агента — склеивание Stack Traces в одно событие.
*   **Проблема**: Docker пишет каждую строку трейса как отдельный JSON-объект.
*   **Решение**: Использование Multiline-фильтров по паттерну начала строки (обычно дата).

**Пример для Grafana Alloy:**
```alloy
loki.process "multiline" {
  stage.multiline {
    firstline = "^[\\d{4}-\\d{2}-\\d{2}]" // Начало строки: 2026-08-03
    max_wait  = "3s"
  }
}
```

## Дополнительная информация

### Сравнение современных агентов (2026)

| Критерий | Fluentd | Filebeat | Grafana Alloy | Vector |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | Ruby / C | Go | Go | Rust |
| **Потребление ресурсов** | Среднее / Высокое | Низкое | Среднее | Экстремально низкое |
| **Сложная логика** | Плагины Ruby | Скрипты (ограничено) | River (декларативно) | VRL (очень мощно) |
| **Экосистема** | Максимальная | Elastic | Grafana / OTel | Универсальная |

### Резюме и выбор решения

1.  **Grafana Stack**: Используйте **Grafana Alloy**. Это будущее сбора телеметрии в экосистеме Grafana.
2.  **Elastic Stack**: Используйте **Filebeat**. Бесшовная интеграция с Kibana и Elasticsearch.
3.  **Высокая нагрузка**: Используйте **Vector**. Rust гарантирует отсутствие пауз GC и минимальный Footprint.
4.  **Сложный Legacy / Custom**: Используйте **Fluentd**, если нужны специфические Ruby-плагины для трансформации данных.

### Ссылки на смежные темы
*   **[Обзор драйверов логирования Docker](./docker_logging_drivers_overview.md)**
*   **[Настройка лог-драйвера Grafana Loki для Docker](./loki_logging_driver_setup.md)**
*   **[Vector: Обзор и архитектура](../../Vector/vector_overview.md)**
*   **[Grafana Alloy: Обзор](../../Grafana/grafana_alloy_overview.md)**
*   **[Logstash: Обзор и ключевые концепции](../../ELK_Stack/Logstash/logstash_overview.md)**
