# Рекомендуемая архитектура: `json-file` + Fluentd Agent

Вместо использования `fluentd` как лог-драйвера, более надежный и гибкий подход — использовать его как **агент-сборщик**, который читает стандартные `json-file` логи, создаваемые Docker по умолчанию.

**Схема:** `Приложение -> STDOUT/STDERR -> Docker (json-file) -> Fluentd (агент) -> [Elasticsearch](../../ELK_Stack/Elasticsearch/elasticsearch_sharding_replication_cluster.md)/etc.`

**Преимущества:**

- **Надежность и буферизация:** Docker стабильно пишет логи на локальный диск. Если Fluentd или сеть до ELK-стека недоступны, логи не теряются. Fluentd-агент продолжит чтение с места, на котором остановился, после восстановления связи.
- **Разделение ответственности (Decoupling):** Контейнеры и Docker-демон работают в штатном режиме, не зная о системе логирования. Сбор и отправка логов — полностью задача агента Fluentd.
- **Простота конфигурации Docker:** Не нужно менять `daemon.json` или указывать `--log-driver` для каждого контейнера.

**Реализация:**

1.  **Docker:** Продолжает использовать драйвер `json-file` (настройка по умолчанию).
2.  **Fluentd Agent:** Запускается как отдельный контейнер на каждом Docker-хосте.

**Пример `docker-compose.yml` для агента Fluentd:**

```yaml
services:
  fluentd-agent:
    image: fluent/fluentd:v1.19.0-debian-1.0
    container_name: fluentd-agent
    volumes:
      # Монтируем директорию с логами Docker и позиционные файлы fluentd
      - /var/lib/docker/containers:/fluentd/log/containers:ro
      - ./fluentd/pos:/fluentd/pos
      - ./fluentd/conf:/fluentd/etc:ro
    restart: unless-stopped
```

**Пример `fluent.conf` для чтения `json-file` логов:**

```conf
# Источник: читаем все *-json.log файлы из директории с логами Docker
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

# Фильтр: обогащаем логи метаданными из имени файла
# Пример: /fluentd/log/containers/CONTAINER_ID/CONTAINER_ID-json.log
<filter docker.**>
  @type record_transformer
  <record>
    container_id ${tag_parts[1]}
  </record>
</filter>

# Назначение: отправляем в Elasticsearch
<match docker.**>
  @type elasticsearch
  host elasticsearch.example.com
  port 9200
  # ... другие настройки ...
</match>
```
- **`@type tail`**: Плагин для чтения файлов "на лету", как `tail -f`.
- **`pos_file`**: Fluentd запоминает в этом файле, на какой строке он остановил чтение, чтобы не отправлять дубликаты после перезапуска.
- **`@type record_transformer`**: Мощный фильтр для добавления/изменения полей. Здесь мы извлекаем ID контейнера из тега, который `in_tail` формирует из имени файла.

---

# Альтернативная архитектура: `json-file` + Filebeat (ELK Стек)

Этот подход аналогичен использованию Fluentd как агента, но использует компоненты из стека Elastic (ELK). Filebeat — это легковесный агент для сбора и отправки логов, разработанный Elastic.

**Схема:** `Приложение -> STDOUT/STDERR -> Docker (json-file) -> Filebeat (агент) -> Logstash (опционально) -> Elasticsearch`

**Преимущества:**

- **Нативная интеграция с ELK:** Если вы уже используете Elasticsearch и Kibana, Filebeat является естественным выбором.
- **Надежность:** Как и Fluentd, Filebeat отслеживает позицию в файлах и гарантирует доставку "at-least-once".
- **Простота:** Конфигурация Filebeat для сбора логов Docker достаточно проста.

**Реализация:**

1.  **Docker:** Продолжает использовать драйвер `json-file` по умолчанию.
2.  **Filebeat:** Устанавливается как сервис на хост-машину или запускается как контейнер.

**Пример конфигурации `filebeat.yml`:**

```yaml
filebeat.inputs:
- type: container
  paths:
    - '/var/lib/docker/containers/*/*.log'

  # Обогащение событий метаданными Docker
  processors:
    - add_docker_metadata: ~

output.logstash:
  hosts: ["logstash.example.com:5044"]
  # Или можно отправлять напрямую в Elasticsearch:
  # output.elasticsearch:
  #   hosts: ["elasticsearch.example.com:9200"]
```
- **`type: container`**: Специальный тип `input` в Filebeat, который понимает формат логов Docker и автоматически парсит JSON-строки.
- **`add_docker_metadata`**: Процессор, который обогащает логи информацией о контейнере (имя, ID, лейблы).

**Пример конфигурации `logstash.conf` для приема от Filebeat:**

```conf
input {
  beats {
    port => 5044
  }
}

filter {
  # Здесь можно добавить дополнительную обработку, если необходимо
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch.example.com:9200"]
    index => "docker-logs-%{+YYYY.MM.dd}"
  }
}
```
