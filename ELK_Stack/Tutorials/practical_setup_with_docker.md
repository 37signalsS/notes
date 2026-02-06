# Руководство: Настройка ELK стека с помощью Docker Compose

> Эта заметка является частью обзора [ELK стека](../elk_stack_overview.md) и описывает практический способ развертывания Elastic Stack (Elasticsearch, Kibana, Filebeat) для локальной разработки и тестирования с использованием Docker Compose.

## Определения

Для получения подробных определений Elasticsearch и Kibana, а также концепции Индекса, обратитесь к соответствующим обзорным документам: **[Обзор Elasticsearch](../Elasticsearch/elasticsearch_overview.md)** и **[Обзор Kibana](../Kibana/kibana_overview.md)**.

* **Filebeat**: Легковесный агент для сбора и отправки логов в Elasticsearch или Logstash.
* **Маппинг (Mapping)**: Схема данных для индекса, определяющая типы полей (например, `text`, `keyword`, `date`).
* **Data Stream**: Абстракция поверх индексов, предназначенная для работы с временными рядами (логи, метрики), которая упрощает управление ротацией данных.

## Основные концепции

### Зачем нужна централизация логов?

1. **Трудоемкий поиск**: Приходится подключаться к разным серверам и вручную агрегировать логи.
2. **Неэффективное хранение**: Растущий объем логов требует масштабирования дискового пространства на каждом сервере.
3. **Небезопасный доступ**: Предоставлять разработчикам и аналитикам прямой доступ к логам на боевых серверах небезопасно.

Эти проблемы решает централизованная система логирования, такая как Elastic Stack.

### Важность маппинга

Правильный маппинг позволяет Elasticsearch эффективно индексировать и искать данные. Поле, определенное как `date`, можно сортировать по времени; поле `keyword` — использовать для точных совпадений и агрегаций. По умолчанию Elasticsearch использует **динамический маппинг**, но в продуктивных средах это **не рекомендуется**, так как может привести к неоптимальному использованию ресурсов.

### Управление жизненным циклом (ILM)

**ILM (Index Lifecycle Management)** — это механизм, который автоматизирует управление индексами по фазам:

* **Hot**: Индекс активно используется для записи и чтения.
* **Warm**: Запись прекращена, но данные все еще часто запрашиваются.
* **Cold**: Данные редко используются, индекс можно сжать.
* **Delete**: Индекс удаляется по истечении срока хранения.

Ключевая операция — **Rollover (Ротация)**, при которой ILM автоматически создает новый индекс для записи, когда старый достигает определенного размера или возраста.

## Практические сценарии

### Шаг 1: Подготовка окружения

1. `docker-compose.yml`
2. `filebeat.yml`
3. `elasticsearch.yml`

### Шаг 2: Конфигурация компонентов

#### `docker-compose.yml`

Этот файл описывает все три сервиса (Elasticsearch, Kibana, Filebeat) и их взаимодействие.

```yaml
version: '3.8'

services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.14.1
    container_name: elasticsearch
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false # Отключаем безопасность для упрощения
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
      - /var/lib/docker/containers:/var/lib/docker/containers:ro # Сбор логов Docker
      - /var/run/docker.sock:/var/run/docker.sock:ro # Доступ к метаданным Docker
    user: root # Требуется для доступа к сокету Docker
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

* **Важно:** Для простоты в этом примере отключена безопасность (`xpack.security.enabled=false`). В реальных проектах используйте встроенные механизмы аутентификации.

#### `elasticsearch.yml`

Минимальная конфигурация для отключения ILM по умолчанию, чтобы индексы не удалялись автоматически во время тестов.

```yaml
# Отключить ILM по умолчанию
xpack.ilm.enabled: false
```

#### `filebeat.yml`

Filebeat будет собирать логи всех Docker-контейнеров на хосте и отправлять их в Elasticsearch.

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

* `autodiscover` позволяет Filebeat автоматически обнаруживать контейнеры и применять к ним нужные настройки.
* `add_docker_metadata` обогащает логи метаданными из Docker (имя контейнера, метки и т.д.).

### Шаг 3: Запуск стека

1. **Настройте системный параметр** для Elasticsearch на хост-машине:

    ```bash
    sudo sysctl -w vm.max_map_count=262144
    ```

2. **Запустите все сервисы** из директории `elk-stack`:

    ```bash
    docker-compose up -d
    ```

### Шаг 4: Проверка и просмотр логов

1. **Проверьте состояние Elasticsearch**. Откройте в браузере `http://localhost:9200`. Вы должны увидеть JSON-ответ с информацией о кластере.
2. **Откройте Kibana** по адресу `http://localhost:5601`.
3. **Создайте Data View**:
    * Перейдите в `Stack Management` -> `Data Views`.
    * Нажмите `Create data view`.
    * В качестве паттерна индекса (`Index pattern`) введите `filebeat-*` и нажмите `Create data view`.
4. **Просмотрите логи**:
    * Перейдите в меню `Discover`.
    * Вы должны увидеть логи от самих компонентов ELK-стека (`elasticsearch`, `kibana`, `filebeat`), которые Filebeat собрал и отправил.

Теперь любые логи, которые ваши приложения пишут в `stdout` внутри Docker-контейнеров, будут автоматически собираться и появляться в Kibana.

## Дополнительная информация

* **Logstash**: Для более сложной обработки логов (например, парсинг с помощью Grok, обогащение из внешних источников) между Filebeat и Elasticsearch добавляется Logstash.
* **Безопасность**: В продуктивной среде обязательно включите `xpack.security.enabled=true` и настройте пароли и TLS-сертификаты.
* **Производительность**: Для реальных нагрузок изучите официальные рекомендации Elastic по настройке JVM heap, дисковой подсистемы и других параметров.
* Более подробно с концепциями можно ознакомиться в [обзоре Elasticsearch](../Elasticsearch/elasticsearch_overview.md).
