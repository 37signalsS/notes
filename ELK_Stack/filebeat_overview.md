# Filebeat: Обзор и Конфигурация

> Эта заметка является частью обзора [ELK стека](./elk_stack_overview.md) и служит основной точкой входа для изучения Filebeat.

## Определения

* **Filebeat** — это легковесный агент для пересылки логов (lightweight shipper), который является частью Elastic Stack. Он предназначен для сбора логов и файловых данных с серверов и отправки их в Logstash или Elasticsearch для индексации.
* **Модули (Modules)** — это предварительно настроенные наборы конфигураций для популярных источников логов (Nginx, MySQL, System, и т.д.). Они включают в себя настройки сбора, парсинг данных на стороне Elasticsearch (Ingest Pipeline) и готовые дашборды в Kibana.

## Основные концепции

### Как работает Filebeat

Filebeat устанавливается на серверы-источники и отслеживает указанные файлы.

* **Harvesters (Сборщики)**: Отвечают за чтение содержимого одного файла. Каждый Harvester считывает новые данные по мере их появления и держит файл открытым.
* **Inputs (Входы)**: Управляют Harvesters и находят все источники, соответствующие конфигурации. Основные типы: `filestream` (современный, для файлов), `log` (устаревший), `container`, `tcp`, `udp`.
* **Registry File**: Filebeat хранит состояние (смещение) для каждого файла в специальном `registry` файле. Это позволяет возобновить чтение с того же места после перезапуска и гарантирует, что данные не будут пропущены или отправлены дважды.

### Обработка данных (Processors)

Filebeat может обрабатывать события перед их отправкой. Это позволяет обогащать, фильтровать и структурировать данные на стороне агента, снижая нагрузку на Logstash или Ingest-узлы Elasticsearch.

* **Примеры процессоров:** `add_cloud_metadata` (добавляет метаданные из AWS, GCP, Azure), `drop_fields` (удаляет ненужные поля), `decode_json_fields` (парсит строковые поля с JSON).

### Механизм обратного давления (Backpressure)

Если Elasticsearch или Logstash перегружены и не могут принимать данные так же быстро, как их отправляет Filebeat, агент автоматически замедляет чтение файлов. Этот механизм предотвращает потерю данных и защищает下游 (downstream) компоненты от перегрузки.

### Автообнаружение (Autodiscover)

В динамических средах, таких как Docker и Kubernetes, Autodiscover позволяет Filebeat автоматически обнаруживать новые контейнеры и применять к ним соответствующие конфигурации на основе их метаданных (лейблов или аннотаций).

## Конфигурация (`filebeat.yml`)

### Пример: Отправка логов в Elasticsearch

Это базовый пример, который отслеживает все файлы `/var/log/*.log` и отправляет их напрямую в защищенный кластер Elasticsearch.

```yaml
filebeat.inputs:
- type: filestream
  id: my-filestream-id
  paths:
    - /var/log/*.log
  # Исключение файлов .gz
  exclude_files: [".gz$"]

# ---------------------------- Elasticsearch Output ----------------------------
output.elasticsearch:
  hosts: ["https://es01:9200", "https://es02:9200"]
  # Использование API ключа для аутентификации (рекомендуется)
  api_key: "id:api_key" 
  
  # Или логин/пароль
  # username: "elastic"
  # password: "password"

  # Укажите путь к CA сертификату вашего кластера
  ssl.certificate_authorities: ["/etc/filebeat/certs/ca.crt"]
```

### Пример: Использование модуля Nginx

Модули значительно упрощают сбор стандартных логов.

1. **Включить модуль:**

    ```bash
    filebeat modules enable nginx
    ```

2. **Настроить модуль** в `modules.d/nginx.yml`:

    ```yaml
    - module: nginx
      # Разделы для access и error логов
      access:
        enabled: true
        var.paths: ["/var/log/nginx/access.log*"]
      error:
        enabled: true
        var.paths: ["/var/log/nginx/error.log*"]
    ```

    *Filebeat автоматически применит правильный парсинг и направит данные на соответствующие дашборды в Kibana.*

### Пример: Использование процессоров

Процессоры добавляются в конфигурацию входа и выполняются последовательно.

```yaml
filebeat.inputs:
- type: filestream
  paths:
    - /var/log/my-app/*.json
  
  # Парсинг JSON-логов
  json.keys_under_root: true
  json.add_error_key: true

  processors:
    # Добавляет метаданные из облачного провайдера
    - add_cloud_metadata: {}
    
    # Добавляет статическое поле
    - add_fields:
        target: project
        fields:
          name: my-awesome-app
          version: "1.0"

    # Удаляет "тяжелое" поле, которое не нужно в логах
    - drop_fields:
        fields: ["request.body.content"]
        ignore_missing: true
```

## Дополнительная информация

* **Настройка Filebeat и ELK**: Для ознакомления с полным циклом настройки стека см. [Практическое руководство по настройке ELK](./Tutorials/practical_setup_with_docker.md).
* **Официальный список модулей**: [Filebeat Modules](https://www.elastic.co/guide/en/beats/filebeat/current/filebeat-modules.html)
