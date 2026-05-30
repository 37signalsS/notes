# Руководство: Настройка ELK стека с помощью Docker Compose

> Практическое руководство по развертыванию Elastic Stack (Elasticsearch, Kibana, Filebeat) для локальной разработки и тестирования через Docker Compose.
>
> Базовые понятия: [Обзор Elasticsearch](../Elasticsearch/elasticsearch_overview.md), [Kibana](../Kibana/kibana_overview.md), [Filebeat](../filebeat_overview.md), [Маппинг и ILM](../Elasticsearch/elasticsearch_mapping_and_indexing.md).

## Определения

* **Docker Compose**: инструмент для определения и запуска многоконтейнерных приложений Docker через YAML-файл. Подробнее — в [Обзоре Docker Compose](../../Docker/Docker_compose/docker_compose_overview.md).
* **ELK стек в Docker**: контейнеризированная версия Elastic Stack для локальной разработки с упрощенной конфигурацией, позволяющая быстро развернуть среду мониторинга.

## Основные концепции

### Назначение локального стека

* **Тестирование конфигураций**: отладка файлов `filebeat.yml`, `elasticsearch.yml` перед развертыванием в промышленную эксплуатацию (production).
* **Локальная разработка**: запуск полного стека на рабочей машине для отладки интеграций с приложениями.
* **Демонстрация**: быстрое развертывание для ознакомления с возможностями платформы.

### Особенности развертывания в Docker

* **Упрощенная безопасность**: для локальных тестов в данном руководстве безопасность отключается (`xpack.security.enabled=false`).
* **Режим одного узла (Single-node)**: Elasticsearch запускается как один узел без формирования полноценного кластера (`discovery.type=single-node`).
* **Сбор логов Docker**: Filebeat настраивается на автоматический сбор логов контейнеров через сокет Docker (`/var/run/docker.sock`) и директорию с логами хоста.

## Практические сценарии

### Настройка конфигурационных файлов

Создайте рабочую директорию и подготовьте следующие файлы.

#### 1. Файл `docker-compose.yml`

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

#### 2. Файл `elasticsearch.yml`

```yaml
# Отключение жизненного цикла индексов для экономии ресурсов в тестах
xpack.ilm.enabled: false
```

#### 3. Файл `filebeat.yml`

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

### Запуск и проверка

1. **Настройка системы**: Elasticsearch требует увеличения лимита на количество областей маппинга памяти (mmap counts). На хост-машине выполните:

    ```bash
    sudo sysctl -w vm.max_map_count=262144
    ```

2. **Запуск контейнеров**:

    ```bash
    docker-compose up -d
    ```

3. **Проверка состояния**:
   * **Elasticsearch**: `http://localhost:9200` — должен вернуть JSON с информацией об узле.
   * **Kibana**: `http://localhost:5601` — веб-интерфейс для работы с данными.

4. **Настройка отображения логов в Kibana**:
   * Перейдите в `Stack Management` → `Data Views`.
   * Создайте новый Data View с паттерном `filebeat-*`.
   * В разделе `Discover` выберите созданный паттерн для просмотра поступающих логов.

## Дополнительная информация

### Рекомендации по эксплуатации

* **Безопасность**: при выходе за пределы локального тестирования необходимо включить `xpack.security.enabled=true`, настроить аутентификацию и TLS-шифрование.
* **Обработка данных**: для сложной трансформации логов (парсинг нестандартных форматов, обогащение данными GeoIP) рекомендуется добавить Logstash в цепочку между Filebeat и Elasticsearch.
* **Версионирование**: всегда указывайте конкретные версии образов. Использование тега `latest` в Docker-файлах затрудняет воспроизводимость среды и поиск причин сбоев при обновлении компонентов.
* **Ресурсы**: для стабильной работы стека в Docker рекомендуется выделить не менее 4 ГБ оперативной памяти для Docker-демона.
