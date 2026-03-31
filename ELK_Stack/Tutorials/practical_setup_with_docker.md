# Руководство: Настройка ELK стека с помощью Docker Compose

> Практическое руководство по развертыванию Elastic Stack (Elasticsearch, Kibana, Filebeat) для локальной разработки и тестирования через Docker Compose.
>
> **Базовые понятия:** [Elasticsearch](../Elasticsearch/elasticsearch_overview.md), [Kibana](../Kibana/kibana_overview.md), [Filebeat](../filebeat_overview.md), [Маппинг и ILM](../Elasticsearch/elasticsearch_mapping_and_indexing.md).

## Определения

* **Docker Compose**: Инструмент для определения и запуска многоконтейнерных приложений Docker через YAML-файл.
* **ELK стек в Docker**: Контейнеризированная версия Elastic Stack для локальной разработки с упрощенной конфигурацией.

## Основные концепции

### Назначение локального ELK стека

* **Тестирование конфигураций**: Отладка filebeat.yml, elasticsearch.yml перед развертыванием в production.
* **Локальная разработка**: Запуск полного стека на рабочей машине для отладки интеграций.
* **Демонстрация**: Быстрое развертывание для демонстрации возможностей Elastic Stack.

### Особенности Docker-развертывания

* **Упрощенная безопасность**: Для локальных тестов безопасность отключается (`xpack.security.enabled=false`).
* **Single-node режим**: Elasticsearch запускается как один узел (`discovery.type=single-node`).
* **Отключение ILM**: Для тестов ILM отключается, чтобы индексы не удалялись автоматически.
* **Сбор логов Docker**: Filebeat настроен на сбор логов контейнеров через `/var/lib/docker/containers` и Docker socket.

## Практические сценарии

### Подготовка файлов конфигурации

Создайте директорию `elk-stack` и три файла:

1. `docker-compose.yml`
2. `elasticsearch.yml`
3. `filebeat.yml`

### Конфигурация компонентов

#### `docker-compose.yml`

```yaml
version: '3.8'

services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.14.1
    container_name: elasticsearch
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
    volumes:
      - ./elasticsearch.yml:/usr/share/elasticsearch/config/elasticsearch.yml
      - esdata:/usr/share/elasticsearch/data
    ports:
      - "9200:9200"
    networks:
      - elk

  kibana:
    image: docker.elastic.co/kibana/kibana:8.14.1
    container_name: kibana
    ports:
      - "5601:5601"
    depends_on:
      - elasticsearch
    networks:
      - elk

  filebeat:
    image: docker.elastic.co/beats/filebeat:8.14.1
    container_name: filebeat
    command: filebeat -e -strict.perms=false
    volumes:
      - ./filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    user: root
    depends_on:
      - elasticsearch
    networks:
      - elk

volumes:
  esdata:
    driver: local

networks:
  elk:
    driver: bridge
```

#### `elasticsearch.yml`

```yaml
xpack.ilm.enabled: false
```

#### `filebeat.yml`

```yaml
filebeat.autodiscover:
  providers:
    - type: docker
      hints.enabled: true

processors:
  - add_docker_metadata: ~

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  protocol: "http"

logging.level: info
```

### Запуск стека

1. **Настройте системный параметр** на хост-машине:

    ```bash
    sudo sysctl -w vm.max_map_count=262144
    ```

2. **Запустите сервисы** из директории `elk-stack`:

    ```bash
    docker-compose up -d
    ```

### Проверка и просмотр логов

1. **Elasticsearch**: Откройте `http://localhost:9200` — JSON-ответ с информацией о кластере.
2. **Kibana**: Откройте `http://localhost:5601`.
3. **Создайте Data View**:
   * `Stack Management` → `Data Views` → `Create data view`
   * Введите `filebeat-*` → `Create data view`
4. **Просмотр логов**:
   * Перейдите в `Discover`
   * Выберите `filebeat-*`
   * Отобразятся логи компонентов ELK-стека

## Дополнительная информация

* **Безопасность**: В production включите `xpack.security.enabled=true`, настройте пароли и TLS-сертификаты.
* **Logstash**: Для сложной обработки (Grok, обогащение) добавьте Logstash между Filebeat и Elasticsearch.
* **Производительность**: Изучите рекомендации Elastic по настройке JVM heap и дисковой подсистемы для production.
* **Версии**: Используйте конкретные версии образов (например, `8.14.1`), избегайте тега `latest`.
