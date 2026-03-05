# Продвинутые возможности Docker Compose

## Определения

**Продвинутые возможности Docker Compose** — это набор техник, которые позволяют гибко управлять сложными многоконтейнерными приложениями, адаптировать конфигурации для разных окружений и переиспользовать код.

## Базовые концепции

#### 1. Интерполяция переменных

Docker Compose позволяет использовать переменные окружения из вашего терминала или из файла `.env` для подстановки значений в `compose.yml`.

* **Приоритет и источники переменных:**
    1. **Переменные из оболочки (shell):** Наивысший приоритет.
    2. **Файл `.env` в корне проекта:** Используются, если переменная не задана в оболочке.

* **Синтаксис:**
  * `${VARIABLE}`: Простая подстановка.
  * `${VARIABLE:-default}`: Подставить `default`, если `VARIABLE` не задана.
  * `${VARIABLE:?error message}`: Показать ошибку, если `VARIABLE` не задана.

> **Важно:** Использование `.env` файлов удобно для разработки, но **небезопасно для хранения секретов в production**. Для безопасного управления секретами используйте директиву `secrets` ([Управление секретами в Docker](../Docker_security/secrets_management.md)).

#### 2. Разделение конфигурации для разных окружений

* **Лучшая практика: `compose.override.yml`**
    По умолчанию `docker compose` автоматически ищет и объединяет два файла:
    1. `compose.yml` (базовая конфигурация)
    2. `compose.override.yml` (переопределения для локальной разработки)

    Это позволяет хранить на production-сервере только `compose.yml` для безопасной, изолированной конфигурации, а локально добавлять монтирование исходного кода, порты и т.д.

* **Альтернативный способ:** Явно указать несколько файлов с помощью флага `-f`. Последний файл имеет наивысший приоритет.

    ```sh
    docker compose -f compose.yml -f compose.prod.yml up -d
    ```

#### 3. Использование `extends` для переиспользования конфигураций

Директива `extends` позволяет совместно использовать общие конфигурации между различными сервисами или даже разными проектами.

```yaml
# common-services.yml
services:
  base_service:
    env_file: .env
    restart: unless-stopped
    networks:
      - some_network

# compose.yml
services:
  web:
    extends:
      file: common-services.yml
      service: base_service
    build: .
    ports:
      - "8000:8000"
```

> **Предостережение:** `extends` может усложнить понимание и отладку конфигурации, так как часть определения сервиса "спрятана" в другом файле. В современных проектах часто предпочитают использовать **YAML anchors & aliases (`&` и `*`)** для переиспользования кода в пределах одного файла, так как это делает конфигурацию более явной и читаемой.

#### 4. Секция `deploy` и интеграция с Docker Swarm

Секция `deploy` является ключевой при работе с **[Docker Swarm](../../Docker_swarm/docker_swarm_overview.md)**.

> **Важно:** Изначально `deploy` использовалась только командой `docker stack deploy` и полностью игнорировалась `docker compose up`. Однако **современные версии `docker compose` частично поддерживают** некоторые параметры из этой секции (например, `deploy.replicas` и `deploy.resources`) даже без режима Swarm.

* **Основные параметры:**
  * `replicas`: Количество экземпляров сервиса.
  * `update_config`: Стратегия выполнения обновлений (rolling updates).
  * `restart_policy`: Политика перезапуска в случае сбоя.
  * `placement`: Ограничения на размещение контейнеров (`constraints: [node.role == worker]`).
  * `resources`: Ограничения на потребление CPU и памяти.
  * `labels`: Интеграция с другими системами, например, с реверс-прокси **[Traefik](../../../WebServers/Traefik/traefik_overview.md)**.

> Подробнее о развертывании стеков: [Развертывание приложений в Docker Swarm](../../Docker_swarm/swarm_stack_deployment.md).

#### 5. Масштабирование сервисов (для `docker compose`)

Для горизонтального масштабирования сервисов на **одной машине** можно использовать флаг `--scale` или директиву `deploy.replicas`.

```sh
# Запустить 3 экземпляра сервиса 'worker'
docker compose up -d --scale worker=3
```

## Практические сценарии

### Пример: HA-кластер PostgreSQL с Patroni

Docker Compose отлично подходит для моделирования сложных систем, таких как отказоустойчивый кластер PostgreSQL.

* **Концепция:** В основе лежит **[Patroni](../../Databases/PostgreSQL/Concepts/high_availability.md)**, система для автоматизации высокой доступности PostgreSQL.
* **Компоненты стека:**
  * **etcd**: Распределенное хранилище для выбора лидера и хранения состояния кластера.
  * **HAProxy**: Балансировщик нагрузки для направления запросов.
  * **Три узла Patroni/PostgreSQL**.

```yaml
services:
  etcd:
    image: 'bitnami/etcd:3.4'
    environment:
      - ALLOW_NONE_AUTHENTICATION=yes
      - ETCD_ADVERTISE_CLIENT_URLS=http://etcd:2379
    ports:
      - '2379:2379'

  haproxy:
    image: 'haproxy:2.1'
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    ports:
      - '5000:5000' # Порт для записи (мастер)
      - '5001:5001' # Порт для чтения (реплики)
      - '8008:8008' # Статистика HAProxy
    depends_on:
      - patroni1
      - patroni2
      - patroni3

  patroni1: &patroni-base
    image: 'bitnami/patroni:3.0'
    environment: &patroni-env
      - PATRONI_SCOPE=my-postgres-cluster
      - PATRONI_ETCD_HOSTS=etcd:2379
      - PATRONI_POSTGRESQL_LISTEN=0.0.0.0:5432
    depends_on:
      - etcd

  patroni2:
    <<: *patroni-base # Используем YAML якорь для переиспользования
    environment:
      <<: *patroni-env
      - PATRONI_NAME=patroni2
      - PATRONI_RESTAPI_URL=http://patroni2:8008
      - PATRONI_POSTGRESQL_CONNECT_ADDRESS=patroni2:5432
      - PATRONI_POSTGRESQL_DATA_DIR=/data/patroni2
    volumes:
      - patroni_data2:/data/patroni2

  patroni3:
    <<: *patroni-base
    image: 'bitnami/patroni:3.0' # ИСПРАВЛЕНО
    environment:
      <<: *patroni-env
      - PATRONI_NAME=patroni3
      - PATRONI_RESTAPI_URL=http://patroni3:8008
      - PATRONI_POSTGRESQL_CONNECT_ADDRESS=patroni3:5432
      - PATRONI_POSTGRESQL_DATA_DIR=/data/patroni3
    volumes:
      - patroni_data3:/data/patroni3

# Определяем patroni1 отдельно, чтобы задать уникальные значения
services:
  patroni1:
    environment:
      <<: *patroni-env
      - PATRONI_NAME=patroni1
      - PATRONI_RESTAPI_URL=http://patroni1:8008
      - PATRONI_POSTGRESQL_CONNECT_ADDRESS=patroni1:5432
      - PATRONI_POSTGRESQL_DATA_DIR=/data/patroni1
    volumes:
      - patroni_data1:/data/patroni1

volumes:
  patroni_data1:
  patroni_data2:
  patroni_data3:
```

В данном примере для `patroni2` и `patroni3` используется YAML-якорь `*patroni-base`, чтобы не дублировать общие поля `image` и `depends_on`.
