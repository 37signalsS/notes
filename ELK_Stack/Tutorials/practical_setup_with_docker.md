# Руководство: Развертывание ELK стека в Docker Compose

> Эта заметка является авторитетным источником по вопросам локального и прототипного развертывания Elastic Stack с использованием Docker Compose и Docker CLI. Она описывает процессы настройки компонентов версий 8.x (актуальная LTS-ветка — 8.19) и 9.x (на август 2026 — 9.5) с учетом современных требований к безопасности: TLS через certutil, автоконфигурация безопасности, hardened-образы Wolfi и проверка подписей образов.

## Определения

* **Docker Compose** — инструмент для управления жизненным циклом многоконтейнерных приложений. Описание базовых команд: [docker_compose_cli_commands.md](../../Docker/Docker_compose/docker_compose_cli_commands.md).
* **Setup-контейнер** — временный сервисный контейнер, используемый для автоматической генерации сертификатов TLS и инициализации системных настроек (пароли системных пользователей) перед запуском основных узлов Elasticsearch.
* **Healthcheck** — механизм проверки готовности сервиса. В Elasticsearch критично проверять статус кластера через API, а не просто доступность TCP-порта.
* **Data View** — абстракция в Kibana для объединения одного или нескольких индексов в логическую группу для поиска (заменила Index Patterns).
* **Токен регистрации (Enrollment Token)** — ключ автоконфигурации безопасности: при первом старте контейнер Elasticsearch генерирует пароль пользователя `elastic` и токен для подключения Kibana/новых узлов. Действует 30 минут.
* **Wolfi-образ** — hardened-вариант официального образа (суффикс `-wolfi` в теге), собранный на минималистичном дистрибутиве Wolfi: минимальная поверхность атаки и отсутствие shell-утилит общего назначения. Требует Docker ≥ 20.10.10.

## Основные концепции

### Задачи локального развертывания

*   **Прототипирование**: Тестирование Ingest-пайплайнов и правил парсинга перед выкаткой в Prod.
*   **Локальная разработка**: Интеграция микросервисов с поисковым движком и APM.
*   **Изучение ELK**: Отработка сценариев миграции маппинга и настройки ILM.

### Безопасность в Docker (Modern Approach)

Начиная с версии 8.0, функции безопасности включены по умолчанию. В локальной среде Docker доступны два подхода:

1.  **Автоматизация TLS**: Использование встроенной утилиты `elasticsearch-certutil` для создания собственного CA и сертификатов узлов (подход setup-контейнера, Сценарий 3).
2.  **Автоконфигурация безопасности**: При первом старте контейнера Elasticsearch сам генерирует CA, сертификаты HTTP-слоя и учетные данные — подходит для single-node стендов (Сценарий 2). Не масштабируется на произвольные топологии так гибко, как certutil.
3.  **Шифрование HTTP**: Включение HTTPS для всех взаимодействий (клиент-узел и узел-узел).
4.  **Basic Auth**: Использование системных пользователей (`elastic`, `kibana_system`) с паролями, передаваемыми через переменные окружения или файл `.env`.
5.  **Целостность образов**: Официальные образы подписаны Sigstore Cosign; проверка перед запуском:
    ```bash
    wget https://artifacts.elastic.co/cosign.pub
    cosign verify --key cosign.pub docker.elastic.co/elasticsearch/elasticsearch:9.5.2
    # → The following checks were performed on each of these signatures:
    # → - The cosign claims were validated
    # → - Existence of the claims in the transparency log was verified offline
    # → - The signatures were verified against the specified public key
    ```

### Системные требования

Elasticsearch требует специфических настроек хоста:
*   **Virtual Memory**: Параметр `vm.max_map_count` должен быть не менее 262144.
*   **Memory**: Минимум 4 ГБ RAM для стабильной работы связки ES + Kibana + Filebeat. В Docker Desktop задается в **Settings → Resources** (рекомендация Elastic — не менее 4 ГБ).
*   **Права на тома**: Контейнер Elasticsearch работает под пользователем `1000:0`; том `certs` после генерации передается ему командой `chown -R 1000:0`.

## Практические сценарии

### 1. Подготовка хостовой системы

Перед запуском выполните настройку лимитов памяти:

```bash
sudo sysctl -w vm.max_map_count=262144
# Проверка
sysctl vm.max_map_count
# → vm.max_map_count = 262144
```

```bash
# Сохранение после перезагрузки
echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-elasticsearch.conf
sudo sysctl --system
```

Особенности платформ:

*   **Linux** — настройка обязательна, как показано выше.
*   **Windows (WSL2)** — команда выполняется внутри дистрибутива WSL (`wsl -u root sysctl -w vm.max_map_count=262144`) либо добавляется в `/etc/sysctl.conf` дистрибутива для персистентности.
*   **macOS (Docker Desktop)** — параметр настраивается внутри VM Linux; в актуальных версиях Docker Desktop значение по умолчанию обычно достаточно, но при ошибке bootstrap check увеличьте лимит согласно документации Docker Desktop.

### 2. Быстрый single-node стенд без ручных сертификатов

Самый короткий путь для разработки: автоконфигурация безопасности делает все сама при первом старте ([официальный гайд](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-basic)).

```bash
# 1. Сеть для будущего расширения стенда
docker network create elastic

# 2. Запуск узла; флаг -m задает лимит памяти контейнера
#    и автоматически определяет размер JVM heap (без ES_JAVA_OPTS)
docker run --name es01 --net elastic -p 9200:9200 -it -m 1GB \
  docker.elastic.co/elasticsearch/elasticsearch:9.5.2
# → в выводе появятся одноразовые секреты:
# → Security is enabled ... generated password for the elastic user: <PASSWORD>
# → ... enrollment token for Kibana: eyJ2ZXIiOiI5LjUuMiIs...
```

3. Сохраните пароль и токен из первого старта (выводятся один раз); их можно перегенерировать позже:

```bash
docker exec -it es01 /usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic
docker exec -it es01 /usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s kibana
export ELASTIC_PASSWORD="your_password"
```

4. Скопируйте CA-сертификат HTTP-слоя и проверьте API:

```bash
docker cp es01:/usr/share/elasticsearch/config/certs/http_ca.crt .
curl --cacert http_ca.crt -u elastic:$ELASTIC_PASSWORD https://localhost:9200
# → {
# →   "name" : "es01", "cluster_name" : "docker-cluster",
# →   "version" : { "number" : "9.5.2", ... },
# →   "tagline" : "You Know, for Search"
# → }
```

5. Подключение Kibana — просто запустите контейнер и откройте напечатанную в терминале ссылку, введя enrollment token:

```bash
docker run --name kib01 --net elastic -p 5601:5601 docker.elastic.co/kibana/kibana:9.5.2
```

6. Добавление узла в кластер (по желанию): сгенерируйте node-токен (`-s node`) и стартуйте новый контейнер с переменной `ENROLLMENT_TOKEN`:

```bash
docker exec -it es01 /usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s node
docker run -e ENROLLMENT_TOKEN="<token>" --name es02 --net elastic -it -m 1GB \
  docker.elastic.co/elasticsearch/elasticsearch:9.5.2
curl --cacert http_ca.crt -u elastic:$ELASTIC_PASSWORD https://localhost:9200/_cat/nodes
# → ip        heap.percent ram.percent cpu load_1m load_5m load_15m node.role master name
# → 172.18.0.2           62          78   3    0.12    0.09     0.06 cdfhilmrstw *      es01
# → 172.18.0.3           45          78   2    0.08    0.07     0.05 cdfhilmrstw -      es02
```

Для ML-функций (например, ELSER) стартуйте контейнер с большим лимитом: `-m 6GB -e "xpack.ml.use_auto_machine_memory_percent=true"`.

### 3. Эталонная конфигурация `compose.yaml` (TLS через setup-контейнер)

Данный файл автоматически настраивает TLS-сертификаты, пароли системных пользователей и запускает защищенный стек. Версия стека и пароли вынесены в `.env` по образцу [официального примера](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-compose).

Файл `.env` рядом с `compose.yaml`:

```ini
# Пароль пользователя 'elastic' (минимум 6 символов, только буквы и цифры)
ELASTIC_PASSWORD=changeme
# Пароль пользователя 'kibana_system' (только буквы и цифры!)
KIBANA_PASSWORD=changeme
# Версия всех компонентов стека должна совпадать
STACK_VERSION=9.5.2
# Порт HTTP API на хосте; биндинг на localhost скрывает API от внешних сетей
ES_PORT=127.0.0.1:9200
CLUSTER_NAME=docker-cluster
LICENSE=basic
MEM_LIMIT=1073741824
```

> Ограничение: bash-скрипт setup-контейнера корректно работает только с буквенно-цифровыми паролями без спецсимволов (`!`, `@` и т.п.).

```yaml
name: elk-stack

services:
  setup:
    image: docker.elastic.co/elasticsearch/elasticsearch:${STACK_VERSION}
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
    image: docker.elastic.co/elasticsearch/elasticsearch:${STACK_VERSION}
    container_name: elasticsearch
    environment:
      - node.name=elasticsearch
      - cluster.name=${CLUSTER_NAME}
      - discovery.type=single-node
      - ELASTIC_PASSWORD=${ELASTIC_PASSWORD}
      - bootstrap.memory_lock=true
      - xpack.security.enabled=true
      - xpack.security.http.ssl.enabled=true
      - xpack.security.http.ssl.key=certs/elasticsearch/elasticsearch.key
      - xpack.security.http.ssl.certificate=certs/elasticsearch/elasticsearch.crt
      - xpack.security.http.ssl.certificate_authorities=certs/ca/ca.crt
      - xpack.security.transport.ssl.enabled=true
      - xpack.security.transport.ssl.key=certs/elasticsearch/elasticsearch.key
      - xpack.security.transport.ssl.certificate=certs/elasticsearch/elasticsearch.crt
      - xpack.security.transport.ssl.certificate_authorities=certs/ca/ca.crt
      - ES_JAVA_OPTS=-Xms${ES_HEAP:-1g} -Xmx${ES_HEAP:-1g}
      - MEM_LIMIT=${MEM_LIMIT}
    ulimits:
      memlock:
        soft: -1
        hard: -1
    volumes:
      - certs:/usr/share/elasticsearch/config/certs
      - esdata:/usr/share/elasticsearch/data
    ports:
      - "${ES_PORT}:9200"
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "curl -s -f -u elastic:${ELASTIC_PASSWORD} --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt https://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=1s || exit 1"
        ]
      interval: 10s
      timeout: 10s
      retries: 5

  kibana-setup:
    depends_on:
      elasticsearch:
        condition: service_healthy
    image: docker.elastic.co/elasticsearch/elasticsearch:${STACK_VERSION}
    volumes:
      - certs:/usr/share/elasticsearch/config/certs
    user: "0"
    command: >
      bash -c '
        echo "Waiting for Elasticsearch availability";
        until curl -s --cacert config/certs/ca/ca.crt -u elastic:${ELASTIC_PASSWORD} https://elasticsearch:9200 | grep -q "You Know, for Search"; do sleep 10; done;
        echo "Setting kibana_system password";
        until curl -s --cacert config/certs/ca/ca.crt -u elastic:${ELASTIC_PASSWORD} -X POST https://elasticsearch:9200/_security/user/kibana_system/_password -d "{\"password\":\"${KIBANA_PASSWORD}\"}" -H "Content-Type: application/json" | grep -q "^{}"; do sleep 10; done;
        echo "All done!";
      '

  kibana:
    depends_on:
      kibana-setup:
        condition: service_completed_successfully
    image: docker.elastic.co/kibana/kibana:${STACK_VERSION}
    container_name: kibana
    environment:
      - ELASTICSEARCH_HOSTS=https://elasticsearch:9200
      - ELASTICSEARCH_USERNAME=kibana_system
      - ELASTICSEARCH_PASSWORD=${KIBANA_PASSWORD}
      - ELASTICSEARCH_SSL_CERTIFICATEAUTHORITIES=config/certs/ca/ca.crt
    volumes:
      - certs:/usr/share/kibana/config/certs
    ports:
      - "5601:5601"
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "curl -s -I http://localhost:5601/api/status | grep -q \"HTTP/1.[01] [23]..\" || exit 1"
        ]
      interval: 10s
      timeout: 10s
      retries: 10

  filebeat:
    depends_on:
      elasticsearch:
        condition: service_healthy
    image: docker.elastic.co/beats/filebeat:${STACK_VERSION}
    container_name: filebeat
    user: root
    command: filebeat -e -strict.perms=false
    volumes:
      - ./filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - certs:/usr/share/filebeat/certs:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - ELASTIC_PASSWORD=${ELASTIC_PASSWORD}

volumes:
  certs:
  esdata:
```

Что изменилось относительно классической схемы и почему:

*   **Версии через `${STACK_VERSION}`**: все компоненты обновляются заменой одной строки в `.env`; рассинхрон версий исключен.
*   **Сервис `kibana-setup`**: пароль `kibana_system` устанавливается автоматически через `_security/user/_password` API сразу после готовности Elasticsearch — ручной `docker exec ... reset-password` больше не нужен.
*   **`bootstrap.memory_lock=true` + ulimits memlock**: heap блокируется от свапа (см. тюнинг в [руководстве по кластеру](./cluster_setup.md)).
*   **`${ES_PORT}`**: по умолчанию API доступен только с самого хоста (`127.0.0.1:9200`).
*   Для hardened-варианта добавьте суффикс `-wolfi` ко всем тегам образов (например, `elasticsearch-wolfi:${STACK_VERSION}`). Учтите: в Wolfi-образах нет bash, поэтому setup-контейнер должен остаться на стандартном образе.

### 4. Конфигурация Filebeat (`filebeat.yml`)

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

Контейнеры сами управляют сбором своих логов через labels — в `compose.yaml` сервиса достаточно добавить:

```yaml
    labels:
      co.elastic.logs/enabled: "true"
      co.elastic.logs/json.keys_under_root: "true"
```

### 5. Запуск, проверка и визуализация

1.  **Запуск**: 
    ```bash
    docker compose up -d
    # → Network elk-stack_default    Created
    # → Container elasticsearch      Healthy
    # → Container kibana-setup       Exited (код 0 = пароль установлен)
    # → Container kibana             Started
    ```
2.  **Проверка кластера** (пароль берется из `.env`):
    ```bash
    docker cp elasticsearch:/usr/share/elasticsearch/config/certs/ca/ca.crt http_ca.crt
    curl --cacert http_ca.crt -u elastic:$ELASTIC_PASSWORD "https://127.0.0.1:9200/_cluster/health?pretty"
    # → {
    # →   "cluster_name" : "docker-cluster",
    # →   "status" : "yellow",
    # →   "number_of_nodes" : 1,
    # →   ...
    # → }
    ```
    Статус `yellow` для single-node — норма: у системных индексов есть реплики, размещать которые некуда (один узел). Если пароль `kibana_system` менялся вручную до внедрения сервиса `kibana-setup`, сбросьте его явно:
    ```bash
    docker exec -it elasticsearch bin/elasticsearch-reset-password -u kibana_system -i
    ```
3.  **Kibana**: Перейдите на `http://localhost:5601` (TLS терминируется на Elasticsearch; Kibana наружу отдает HTTP) и войдите как `elastic` с паролем из `.env`.
4.  **Data View**:
    *   **Stack Management** -> **Data Views**.
    *   Создайте паттерн `filebeat-*` с временной меткой `@timestamp`.

## Дополнительная информация

### Типичные проблемы

*   **Exit Code 137**: Контейнер Elasticsearch убит OOM Killer. Выделите больше памяти в Docker Desktop (мин. 4 ГБ) или уменьшьте `ES_JAVA_OPTS` до `-Xms512m -Xmx512m`. Диагностика: `docker inspect elk-stack-elasticsearch-1 --format '{{.State.OOMKilled}}'`.
*   **Ошибка `max virtual memory areas` в логах**: Bootstrap check не пройден — вернитесь к шагу 1 и убедитесь, что `vm.max_map_count` применен именно на хосте, где работает Docker Engine (в WSL2 — внутри дистрибутива).
*   **"Kibana is not ready"**: Обычно вызвано тем, что ES еще проходит стадию `recovering`. Проверьте статус через `docker ps` и логи (`docker logs kibana`). Если сервис `kibana-setup` завершился с ошибкой — проверьте, что `KIBANA_PASSWORD` буквенно-цифровой и совпадает с фактически установленным.
*   **SSL Handshake Failed**: Убедитесь, что Filebeat и Kibana используют верный путь к `ca.crt`. После пересоздания volume `certs` CA меняется — перезапустите зависимые сервисы, чтобы они получили новые сертификаты.
*   **Permission denied на volume данных**: Том `esdata` принадлежит UID 1000; не запускайте контейнер с `user:` отличным от дефолта, либо исправьте владельца: `docker compose down && docker run --rm -v elk-stack_esdata:/data alpine chown -R 1000:0 /data`.
*   **Устаревшие сертификаты после смены версии**: Полная регенерация PKI выполняется удалением тома: `docker compose down && docker volume rm elk-stack_certs` (данные индексов в `esdata` при этом сохраняются).

### Резервное копирование и обновление стенда

*   **Снапшот данных**: подключите репозиторий файловой системы или S3 и делайте снимки перед экспериментами; для локального стенда достаточно копирования тома `esdata` при остановленном стеке: `docker compose stop elasticsearch && docker run --rm -v elk-stack_esdata:/src -v $PWD/backup:/dst alpine cp -a /src/. /dst/`.
*   **Обновление версии**: измените `STACK_VERSION` в `.env` и выполните `docker compose up -d` — компоненты пересоздадутся с сохранением данных. Обновляйтесь последовательно между минорными версиями и читайте release notes; ветку выбирайте из поддерживаемых (август 2026: 9.5, 9.4 или LTS 8.19).

### Рекомендации по развитию

*   **OTel-native**: В версии 9.x рекомендуется использовать **OpenTelemetry Collector** вместо Filebeat для отправки данных напрямую в Elasticsearch.
*   **Persistent Storage**: Используйте именованные тома (`volumes`) вместо bind-mounts для повышения производительности дисковых операций в Docker.
*   **Мониторинг**: Добавьте Metricbeat для отслеживания здоровья самого кластера ELK.
*   **Hardened-образы**: Для стендов с повышенными требованиями к безопасности используйте варианты с суффиксом `-wolfi` и проверяйте подписи образов через Cosign.
*   **Лимиты ресурсов**: Задайте `mem_limit` (или `deploy.resources.limits` в Swarm-совместимом синтаксисе) для каждого сервиса, чтобы OOM одного компонента не убивал весь хост.

---
*   **[Обзор Elastic Stack](../elk_stack_overview.md)** — архитектура и компоненты.
*   **[Настройка кластера Elasticsearch](./cluster_setup.md)** — мультинодовая конфигурация.
*   **[Filebeat: Обзор и настройка](../filebeat_overview.md)**.
