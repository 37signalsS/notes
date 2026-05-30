# Filebeat: Обзор и Конфигурация

> Эта заметка является частью обзора [ELK стека](./elk_stack_overview.md) и служит основной точкой входа для изучения Filebeat.

## Определения

* **Filebeat**: Легковесный агент для пересылки логов (lightweight shipper) в Elastic Stack. Собирает логи и файловые данные с серверов, отправляет в Logstash или Elasticsearch.
* **Модули (Modules)**: Предварительно настроенные конфигурации для популярных источников логов (Nginx, MySQL, System). Включают настройки сбора, парсинг через Ingest Pipeline и готовые дашборды в Kibana.

## Основные концепции

### Как работает Filebeat

Filebeat устанавливается на серверы-источники и отслеживает указанные файлы.

* **Harvesters (Сборщики)**: Чтение содержимого одного файла. Harvester считывает новые данные по мере появления, держит файл открытым.
* **Inputs (Входы)**: Управление Harvesters, поиск источников по конфигурации. Типы: `filestream` (современный), `log` (устаревший), `container`, `tcp`, `udp`.
* **Registry File**: Хранение состояния (смещения) для каждого файла. Позволяет возобновить чтение после перезапуска, гарантирует доставку без дубликатов.

### Обработка данных (Processors)

Filebeat обрабатывает события перед отправкой: обогащение, фильтрация, структурирование данных на стороне агента.

* **Примеры процессоров:** `add_cloud_metadata` (метаданные AWS, GCP, Azure), `drop_fields` (удаление полей), `decode_json_fields` (парсинг JSON).

### Механизм обратного давления (Backpressure)

При перегрузке Elasticsearch/Logstash Filebeat автоматически замедляет чтение файлов, предотвращая потерю данных и защищая downstream-компоненты.

### Автообнаружение (Autodiscover)

В Docker и Kubernetes Autodiscover автоматически обнаруживает новые контейнеры и применяет конфигурации на основе метаданных (лейблы, аннотации).

## Практические сценарии

### Отправка логов в Elasticsearch

Базовый пример: отслеживание `/var/log/*.log` и отправка в защищенный кластер Elasticsearch.

```yaml
filebeat.inputs:
- type: filestream
  id: my-filestream-id
  paths:
    - /var/log/*.log
  exclude_files: [".gz$"]

output.elasticsearch:
  hosts: ["https://es01:9200", "https://es02:9200"]
  api_key: "<id>:<api_key>"
  # username: "<username>"
  # password: "<password>"
  ssl.certificate_authorities: ["/etc/filebeat/certs/ca.crt"]
```

### Использование модуля Nginx

Модули упрощают сбор стандартных логов.

1. **Включить модуль:** `filebeat modules enable nginx`

2. **Настроить в `modules.d/nginx.yml`:**

    ```yaml
    - module: nginx
      access:
        enabled: true
        var.paths: ["/var/log/nginx/access.log*"]
      error:
        enabled: true
        var.paths: ["/var/log/nginx/error.log*"]
    ```

    Filebeat автоматически применит парсинг и направит данные на дашборды в Kibana.

### Использование процессоров

Процессоры добавляются в конфигурацию входа и выполняются последовательно.

```yaml
filebeat.inputs:
- type: filestream
  paths:
    - /var/log/my-app/*.json

  json.keys_under_root: true
  json.add_error_key: true

  processors:
    - add_cloud_metadata: {}
    - add_fields:
        target: project
        fields:
          name: my-awesome-app
          version: "1.0"
    - drop_fields:
        fields: ["request.body.content"]
        ignore_missing: true
```

## Дополнительная информация

* **Сбор логов Docker:** примеры использования Filebeat как агента для сбора логов контейнеров — в **[Агентный сбор логов в Docker](../Docker/Docker_logs/docker_agent_based_logging.md)**.
* **Практика настройки:** полный цикл развертывания стека с Docker Compose — в **[Практическое руководство по настройке ELK](./Tutorials/practical_setup_with_docker.md)**.
* **Документация:** список поддерживаемых модулей доступен в [официальной документации Elastic](https://www.elastic.co/guide/en/beats/filebeat/current/filebeat-modules.html).

> **Примечание о версиях:** Для совместимости компонентов ELK стека рекомендуется использовать одинаковые версии Elasticsearch, Logstash, Kibana и Filebeat. Актуальные мажорные версии — 8.x и 9.x (по состоянию на март 2026 года).
