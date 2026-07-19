# Агентный сбор логов Docker

## Определения

**Агентный сбор логов** — это архитектурный подход, при котором для сбора, обработки и отправки логов используется отдельное приложение (агент), установленное на хосте. Этот агент работает независимо от Docker daemon и контейнеров.

**Централизованное логирование** — практика агрегации логов из различных источников в единую систему хранения и анализа для упрощения мониторинга, отладки и аудита. Агентный сбор является одним из способов реализации централизованного логирования.

## Базовые концепции

Основная идея подхода заключается в разделении ответственности: Docker daemon отвечает только за запуск контейнеров и запись их стандартных потоков вывода (`STDOUT`/`STDERR` — Standard Output / Standard Error) в локальные файлы, а специализированный агент — за их дальнейшую доставку.

**Схема работы:**
`Приложение → STDOUT/STDERR → Docker Engine (json-file / local driver) → Агент (Fluentd / Alloy / Vector) → Система хранения`

В качестве драйвера логирования Docker обычно используется `json-file` (настройка по умолчанию). Однако в современных инсталляциях (Docker 20.10+) часто применяется драйвер `local`, который более эффективно управляет дисковым пространством и предотвращает его переполнение за счет встроенной ротации. Агенты одинаково успешно читают логи обоих драйверов, так как они физически располагаются в `/var/lib/docker/containers/`.

### Преимущества агентного подхода

- **Надежность и буферизация**: Docker стабильно пишет логи на диск. Если агент или система-получатель временно недоступны, логи не теряются. После восстановления связи агент продолжит чтение с места, на котором остановился.
- **Разделение ответственности (Decoupling)**: Контейнеры и Docker daemon работают в штатном режиме, не завися от состояния системы логирования.
- **Простота конфигурации Docker**: Не требуется изменять конфигурацию Docker daemon (`daemon.json`) или указывать `--log-driver` для каждого контейнера.
- **Гибкость**: Агенты предоставляют широкие возможности по фильтрации, трансформации и обогащению логов метаданными (например, тегами и лейблами контейнеров) перед отправкой.

## Практические сценарии

В качестве агентов чаще всего выступают `Fluentd`, `Filebeat`, `Grafana Alloy` или `Vector`.

### Шаг 1: Использование Fluentd в качестве агента

**Реализация:**

1. **Docker**: Использует драйвер `json-file` или `local`.
2. **Fluentd**: Запускается как отдельный контейнер на каждом Docker-хосте.

**Пример `docker-compose.yml` для агента Fluentd:**

```yaml
services:
  fluentd-agent:
    image: fluent/fluentd:v1.19.3-debian-1
    container_name: fluentd-agent
    volumes:
      # Монтируем директорию с логами Docker и позиционные файлы fluentd
      - /var/lib/docker/containers:/fluentd/log/containers:ro
      - ./fluentd/pos:/fluentd/pos
      - ./fluentd/conf:/fluentd/etc:ro
    restart: unless-stopped
```

**Пример конфигурации `fluent.conf`:**

```conf
# 1. Источник: чтение лог-файлов Docker
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
```

# 2. Фильтр: обогащение логов ID контейнера
# Тег формируется из пути к файлу, например: docker.containers.CONTAINER_ID.CONTAINER_ID-json.log
<filter docker.**>
  @type record_transformer
  <record>
    container_id ${tag_parts[2]}
  </record>
</filter>

# 3. Назначение: отправка в Elasticsearch
<match docker.**>
  @type elasticsearch
  host elasticsearch.example.com
  port 9200
  # ... другие настройки ...
</match>
```

- **`@type tail`**: Плагин для чтения файлов "на лету" (`tail -f`).
- **`pos_file`**: Файл, в котором Fluentd хранит информацию о последней прочитанной строке. Это гарантирует, что при перезапуске не будут отправлены дубликаты.

### Шаг 2: Использование Filebeat в качестве агента

Этот подход аналогичен Fluentd, но использует Filebeat — легковесный агент из стека Elastic (ELK — Elasticsearch, Logstash, Kibana).

**Реализация:**

1. **Docker**: Использует драйвер `json-file` или `local`.
2. **Filebeat**: Устанавливается как сервис на хост или запускается как контейнер.

**Пример конфигурации `filebeat.yml`:**

```yaml
filebeat.inputs:
- type: container
  paths:
    - '/var/lib/docker/containers/*/*.log'

  # Обогащение событий метаданными Docker (имя, ID, лейблы)
  processors:
    - add_docker_metadata: ~

# Отправка в Logstash
output.logstash:
  hosts: ["logstash.example.com:5044"]
```

### Шаг 3: Использование Grafana Alloy (рекомендуется для Loki)

В 2026 году Grafana Alloy стал стандартным агентом для сбора телеметрии, полностью заменив Promtail. Он поддерживает как Pull, так и Push модели и глубоко интегрирован с OpenTelemetry.

**Пример конфигурации `config.alloy`:**

```alloy
loki.source.file "docker_logs" {
  targets = [
    { __path__ = "/var/lib/docker/containers/*/*.log" },
  ]
  forward_to = [loki.process.docker_meta.receiver]
}

loki.process "docker_meta" {
  stage.docker { } // Автоматически извлекает метаданные Docker
  forward_to = [loki.write.local.receiver]
}

loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

### Шаг 4: Использование Vector

Vector — высокопроизводительный агент от Datadog, написанный на Rust. Он отличается минимальным потреблением памяти и встроенным языком VRL (Vector Remap Language) для обработки данных.

**Пример `vector.yaml`:**

```yaml
sources:
  docker_logs:
    type: docker_logs

transforms:
  parse_json:
    type: remap
    inputs: [docker_logs]
    source: |
      . = parse_json!(.message)

sinks:
  emit_loki:
    type: loki
    inputs: [parse_json]
    endpoint: "http://loki:3100"
    labels:
      container_name: "{{ container_name }}"
```

## Дополнительная информация

### Сравнение современных агентов

| Критерий | Fluentd | Filebeat | Grafana Alloy | Vector |
| :--- | :--- | :--- | :--- | :--- |
| **Производительность** | Средняя (Ruby/C) | Высокая (Go) | Высокая (Go) | Экстремальная (Rust) |
| **Экосистема** | 500+ плагинов | Elastic Stack | Grafana / OTel | Универсальный |
| **Сложность** | Средняя | Низкая | Средняя (HCL-like) | Средняя (VRL) |
| **Лучшее применение** | Гетерогенные среды | Elastic Stack | Grafana Stack / OTel | High-load системы |

**Выбор:**

- **Grafana Alloy** — если ваша основная цель Grafana Loki и вы переходите на стандарты OpenTelemetry.
- **Vector** — если требуется максимальная производительность при минимальных ресурсах.
- **Filebeat** — для нативной работы с Elastic Stack.
- **Fluentd** — для сложных корпоративных сценариев с множеством кастомных плагинов.

> **Примечание о версиях:** Для production-систем используйте фиксированные версии.
>
> - **Fluentd:** v1.19.3 (июль 2026). Пакет `fluent-package` v6.0.x LTS.
> - **Filebeat:** v9.4.3 (июль 2026).
> - **Grafana Alloy:** v1.17.1 (июль 2026).
> - **Vector:** v0.41.x (июль 2026).

Для детального примера конфигурации Logstash для приема логов от Filebeat см. **[Logstash: Обзор и ключевые концепции](../../ELK_Stack/Logstash/logstash_overview.md)**. Сравнение с лог-драйверами доступно в **[Настройка лог-драйвера Grafana Loki для Docker](./loki_logging_driver_setup.md)**.
