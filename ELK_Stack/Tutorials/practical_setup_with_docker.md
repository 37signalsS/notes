# Руководство: Развертывание ELK стека в Docker Compose

> Эта заметка является SSoT (авторитетным источником) по вопросам локального и прототипного развертывания Elastic Stack с использованием Docker Compose. Она описывает процесс настройки компонентов версии 8.17+ с учетом современных требований к безопасности и производительности.

## Определения

* **Docker Compose** — инструмент для управления жизненным циклом многоконтейнерных приложений. Описание базовых команд: [docker_compose_cli_commands.md](../../Docker/Docker_compose/docker_compose_cli_commands.md).
* **Setup-контейнер** — временный сервисный контейнер, используемый для автоматической генерации сертификатов TLS и инициализации системных настроек перед запуском основных узлов Elasticsearch.
* **Healthcheck** — механизм проверки готовности сервиса. В Elasticsearch критично проверять статус кластера через API, а не просто доступность TCP-порта.
* **Data View** — абстракция в Kibana для объединения одного или нескольких индексов в логическую группу для поиска (заменила Index Patterns).

## Основные концепции

### Задачи локального развертывания

*   **Прототипирование**: Тестирование Ingest-пайплайнов и правил парсинга перед выкаткой в Prod.
*   **Локальная разработка**: Интеграция микросервисов с поисковым движком и APM.
*   **Изучение ELK**: Отработка сценариев миграции маппинга и настройки ILM.

### Безопасность в Docker (Modern Approach)

Начиная с версии 8.0, функции безопасности включены по умолчанию. В локальной среде Docker рекомендуется:
1.  **Автоматизация TLS**: Использование встроенной утилиты `elasticsearch-certutil` для создания собственного CA и сертификатов узлов.
2.  **Шифрование HTTP**: Включение HTTPS для всех взаимодействий (клиент-узел и узел-узел).
3.  **Basic Auth**: Использование системных пользователей (`elastic`, `kibana_system`) с паролями, передаваемыми через переменные окружения.

### Системные требования

Elasticsearch требует специфических настроек хоста:
*   **Virtual Memory**: Параметр `vm.max_map_count` должен быть не менее 262144.
*   **Memory**: Минимум 4 ГБ RAM для стабильной работы связки ES + Kibana + Filebeat.

## Практические сценарии

### 1. Подготовка хостовой системы

Перед запуском выполните настройку лимитов памяти (актуально для Linux):
```bash
sudo sysctl -w vm.max_map_count=262144
# Сохранение после перезагрузки
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
```

### 2. Эталонная конфигурация `compose.yaml`

Данный файл автоматически настраивает TLS-сертификаты и запускает защищенный кластер.

```yaml
name: elk-stack

services:
  setup:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.17.0
    volumes:
      - certs:/usr/share/elasticsearch/config/certs
    user: "0"
    command: >
      bash -c '
        if [ ! -f config/certs/ca.zip ]; then
          echo "Creating CA";
          bin/elasticsearch-certutil ca --silent --pem -out config/certs/ca.zip;
          unzip config/certs/ca.zip -d config/certs;
        fi;
        if [ ! -f config/certs/certs.zip ]; then
          echo "Creating certs";
          echo -e "instances:\n  - name: elasticsearch\n    dns:\n      - elasticsearch\n      - localhost" > config/certs/instances.yml;
          bin/elasticsearch-certutil cert --silent --pem -out config/certs/certs.zip --in config/certs/instances.yml --ca-cert config/certs/ca/ca.crt --ca-key config/certs/ca/ca.key;
          unzip config/certs/certs.zip -d config/certs;
        fi;
        chown -R 1000:0 config/certs;
      '
    healthcheck:
      test: ["CMD-SHELL", "[ -f config/certs/elasticsearch/elasticsearch.crt ]"]
      interval: 1s
      timeout: 5s
      retries: 10

  elasticsearch:
    depends_on:
      setup:
        condition: service_healthy
    image: docker.elastic.co/elasticsearch/elasticsearch:8.17.0
    container_name: elasticsearch
    environment:
      - node.name=elasticsearch
      - cluster.name=docker-cluster
      - discovery.type=single-node
      - ELASTIC_PASSWORD=${ELASTIC_PASSWORD:-changeme}
      - xpack.security.enabled=true
      - xpack.security.http.ssl.enabled=true
      - xpack.security.http.ssl.key=certs/elasticsearch/elasticsearch.key
      - xpack.security.http.ssl.certificate=certs/elasticsearch/elasticsearch.crt
      - xpack.security.http.ssl.certificate_authorities=certs/ca/ca.crt
      - xpack.security.transport.ssl.enabled=true
      - xpack.security.transport.ssl.key=certs/elasticsearch/elasticsearch.key
      - xpack.security.transport.ssl.certificate=certs/elasticsearch/elasticsearch.crt
      - xpack.security.transport.ssl.certificate_authorities=certs/ca/ca.crt
      - ES_JAVA_OPTS=-Xms1g -Xmx1g
    volumes:
      - certs:/usr/share/elasticsearch/config/certs
      - esdata:/usr/share/elasticsearch/data
    ports:
      - "9200:9200"
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "curl -s -f -u elastic:${ELASTIC_PASSWORD:-changeme} --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt https://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=1s || exit 1"
        ]
      interval: 10s
      timeout: 10s
      retries: 5

  kibana:
    depends_on:
      elasticsearch:
        condition: service_healthy
    image: docker.elastic.co/kibana/kibana:8.17.0
    container_name: kibana
    environment:
      - ELASTICSEARCH_HOSTS=https://elasticsearch:9200
      - ELASTICSEARCH_USERNAME=kibana_system
      - ELASTICSEARCH_PASSWORD=${ELASTIC_PASSWORD:-changeme}
      - ELASTICSEARCH_SSL_CERTIFICATEAUTHORITIES=config/certs/ca/ca.crt
    volumes:
      - certs:/usr/share/kibana/config/certs
    ports:
      - "5601:5601"

  filebeat:
    depends_on:
      elasticsearch:
        condition: service_healthy
    image: docker.elastic.co/beats/filebeat:8.17.0
    container_name: filebeat
    user: root
    command: filebeat -e -strict.perms=false
    volumes:
      - ./filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - certs:/usr/share/filebeat/certs:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - ELASTIC_PASSWORD=${ELASTIC_PASSWORD:-changeme}

volumes:
  certs:
  esdata:
```

### 3. Конфигурация Filebeat (`filebeat.yml`)

Использование `autodiscover` с подсказками (hints) для автоматического сбора логов контейнеров.

```yaml
filebeat.autodiscover:
  providers:
    - type: docker
      hints.enabled: true

processors:
  - add_docker_metadata: ~

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "elastic"
  password: "${ELASTIC_PASSWORD}"
  ssl.certificate_authorities: ["/usr/share/filebeat/certs/ca/ca.crt"]
```

### 4. Проверка и визуализация

1.  **Запуск**: `docker compose up -d`.
2.  **Инициализация**: Установите пароль для `kibana_system`, если он не совпадает с переменной:
    ```bash
    docker exec -it elasticsearch bin/elasticsearch-reset-password -u kibana_system -i
    ```
3.  **Kibana**: Перейдите на `https://localhost:5601`.
4.  **Data View**:
    *   **Stack Management** -> **Data Views**.
    *   Создайте паттерн `filebeat-*` с временной меткой `@timestamp`.

## Дополнительная информация

### Типичные проблемы

*   **Exit Code 137**: Контейнер Elasticsearch убит OOM Killer. Выделите больше памяти в Docker Desktop (мин. 4 ГБ) или уменьшите `ES_JAVA_OPTS` до `-Xms512m -Xmx512m`.
*   **"Kibana is not ready"**: Обычно вызвано тем, что ES еще проходит стадию `recovering`. Проверьте статус через `docker ps` и логи.
*   **SSL Handshake Failed**: Убедитесь, что Filebeat и Kibana используют верный путь к `ca.crt`.

### Рекомендации по развитию

*   **OTel-native**: В версии 9.x рекомендуется использовать **OpenTelemetry Collector** вместо Filebeat для отправки данных напрямую в Elasticsearch.
*   **Persistent Storage**: Используйте именованные тома (`volumes`) вместо bind-mounts для повышения производительности дисковых операций в Docker.
*   **Мониторинг**: Добавьте Metricbeat для отслеживания здоровья самого кластера ELK.

---
*   **[Обзор Elastic Stack](../elk_stack_overview.md)** — архитектура и компоненты.
*   **[Настройка кластера Elasticsearch](./cluster_setup.md)** — мультинодовая конфигурация.
*   **[Filebeat: Обзор и настройка](../filebeat_overview.md)**.
