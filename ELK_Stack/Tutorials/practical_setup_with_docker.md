# Руководство: Развертывание ELK стека в Docker Compose

> Практическое руководство по настройке связки Elasticsearch, Kibana и Filebeat для локальной разработки и тестирования. Описанная конфигурация актуальна для версий 8.17+.
>
> Базовые понятия: [Обзор ELK стека](../elk_stack_overview.md), [Elasticsearch: Обзор](../Elasticsearch/elasticsearch_overview.md), [Kibana: Обзор](../Kibana/kibana_overview.md), [Filebeat: Обзор](../filebeat_overview.md).

## Определения

* **Docker Compose** — инструмент для управления жизненным циклом многоконтейнерных приложений. Описание базовых команд доступно в [Обзоре Docker Compose](../../Docker/Docker_compose/docker_compose_overview.md).
* **ELK в Docker** — контейнеризированное решение, обеспечивающее изоляцию компонентов стека и быстрое воспроизведение среды сбора и анализа логов.

## Основные концепции

### Задачи локального развертывания

* **Прототипирование**: быстрая проверка гипотез по парсингу логов перед внесением изменений в промышленный кластер.
* **Отладка приложений**: использование полноценного поискового движка вместо стандартного `STDOUT` при разработке микросервисов.
* **Изучение функционала**: знакомство с новыми возможностями Kibana (Dashboards, Maps, Canvas) без риска для стабильности системы.

### Особенности конфигурации для Docker

* **Упрощенная безопасность (Basic Auth)**: вместо полного отключения безопасности (что не рекомендуется даже для локальных сред в версии 8.x), в данном руководстве используется настройка фиксированного пароля.
* **Режим Single-node**: установка `discovery.type=single-node` отключает проверки кворума, необходимые для мультинодового кластера.
* **Сетевое взаимодействие**: компоненты общаются внутри Docker-сети по именам сервисов, используя порты 9200 (ES API) и 5601 (Kibana UI).

## Практические сценарии

### Подготовка инфраструктуры

Создайте директорию проекта и подготовьте конфигурационные файлы.

#### 1. Файл `docker-compose.yml`

```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.17.0
    container_name: elasticsearch
    environment:
      - node.name=elasticsearch
      - discovery.type=single-node
      - ELASTIC_PASSWORD=changeme
      - xpack.security.enabled=true
      - xpack.security.http.ssl.enabled=false
      - xpack.license.self_generated.type=trial
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    volumes:
      - esdata:/usr/share/elasticsearch/data
    ports:
      - "9200:9200"
    networks:
      - elk

  kibana:
    image: docker.elastic.co/kibana/kibana:8.17.0
    container_name: kibana
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
      - ELASTICSEARCH_USERNAME=kibana_system
      - ELASTICSEARCH_PASSWORD=changeme
    depends_on:
      - elasticsearch
    ports:
      - "5601:5601"
    networks:
      - elk

  filebeat:
    image: docker.elastic.co/beats/filebeat:8.17.0
    container_name: filebeat
    user: root
    command: filebeat -e -strict.perms=false
    volumes:
      - ./filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
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

#### 2. Файл `filebeat.yml`

```yaml
filebeat.autodiscover:
  providers:
    - type: docker
      hints.enabled: true

processors:
  - add_docker_metadata: ~

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  username: "elastic"
  password: "changeme"

logging.level: info
```

### Запуск и первичная настройка

1. **Системные требования**: для работы Elasticsearch необходимо увеличить лимит `mmap`:
    ```bash
    # Временное изменение
    sudo sysctl -w vm.max_map_count=262144
    ```

2. **Запуск стека**:
    ```bash
    docker compose up -d
    ```

3. **Инициализация пароля для Kibana**:
    Поскольку мы задали пароль только для `elastic`, пользователю `kibana_system` нужно задать пароль вручную или через API, чтобы Kibana могла подключиться к ES. Выполните команду внутри контейнера ES:
    ```bash
    docker exec -it elasticsearch bin/elasticsearch-reset-password -u kibana_system -b -i
    # Введите "changeme", чтобы соответствовать настройкам в docker-compose.yml
    ```

4. **Проверка**:
    * Elasticsearch: `curl -u elastic:changeme http://localhost:9200`
    * Kibana: откройте `http://localhost:5601` в браузере.

### Настройка визуализации данных

В версии 8.x концепция Index Patterns заменена на **Data Views**:

1. Откройте Kibana → **Stack Management** → **Data Views**.
2. Нажмите **Create data view**.
3. Укажите имя и паттерн `filebeat-*`.
4. В поле **Timestamp field** выберите `@timestamp`.
5. Перейдите в раздел **Discover** для анализа поступающих логов.

## Дополнительная информация

### Типичные проблемы

* **Контейнер ES падает с ошибкой 137**: нехватка оперативной памяти. Увеличьте лимиты в настройках Docker Desktop (рекомендуется от 4 ГБ) или уменьшите `ES_JAVA_OPTS`.
* **Kibana: "Elasticsearch is not ready"**: проверьте сетевую связность и корректность пароля в `ELASTICSEARCH_PASSWORD`.
* **Логи Docker не собираются**: убедитесь, что путь `/var/lib/docker/containers` на хосте совпадает с указанным в `volumes` (актуально для Linux; на macOS/Windows сбор через сокет Docker приоритетнее).

### Рекомендации по развитию

* **Использование Logstash**: если требуется сложная фильтрация (Grok, Dissect) или обогащение данных (GeoIP), добавьте Logstash в пайплайн. См. [Настройка пайплайнов Logstash](../Logstash/logstash_pipelines.md).
* **Жизненный цикл данных**: настройте политики **ILM (Index Lifecycle Management)** для автоматического удаления старых логов и экономии места на диске. Детали в [Elasticsearch: Политики хранения](../Elasticsearch/elasticsearch_ilm_and_retention.md).
* **Версионирование**: всегда фиксируйте мажорную и минорную версии образов (например, `8.17.0`) для обеспечения воспроизводимости инфраструктуры.

> **См. также:**
> * [Настройка мультинодового кластера Elasticsearch](./cluster_setup.md)
> * [Безопасность в Elasticsearch](../Elasticsearch/elasticsearch_overview.md#безопасность-по-умолчанию)
> * [Docker Compose: Практические примеры](../../Docker/Docker_compose/examples/common_patterns.md)
