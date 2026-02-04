# Продвинутые возможности Docker Compose

### Определения

**Продвинутые возможности Docker Compose** — это набор техник, которые позволяют гибко управлять сложными многоконтейнерными приложениями, адаптировать конфигурации для разных окружений (например, разработка и production) и интегрировать Compose с системами оркестрации, такими как Docker Swarm.

### Базовые концепции

#### 1. Интерполяция переменных

Docker Compose позволяет использовать переменные окружения из вашего терминала или из файла `.env` для подстановки значений в `compose.yml`. Это делает конфигурацию гибкой и позволяет избежать жесткого кодирования портов, тегов образов или паролей.

* **Приоритет и источники переменных:**
    1. **Переменные из оболочки (shell):** Наивысший приоритет.
    2. **Файл `.env` в корне проекта:** Используются, если переменная не задана в оболочке.

* **Синтаксис:**
  * `${VARIABLE}`: Простая подстановка.
  * `${VARIABLE:-default}`: Подставить `default`, если `VARIABLE` не задана.
  * `${VARIABLE:?error message}`: Показать ошибку и прервать выполнение, если `VARIABLE` не задана.

> **Важно:** Использование `.env` файлов удобно для разработки, но является **небезопасным для хранения секретов в production**. Переменные окружения могут легко утечь в логи или быть прочитаны через `docker inspect`. Для безопасного управления секретами используйте встроенные механизмы, описанные в заметке [Управление секретами в Docker](../Docker_security/secrets_management.md).

#### 2. Разделение конфигурации для разных окружений

Для сложных проектов часто требуется иметь базовую конфигурацию для production и изменять ее для локальной разработки (например, добавлять порты и монтировать исходный код).

* **Лучшая практика: `docker-compose.override.yml`**
    По умолчанию `docker compose` автоматически ищет и использует два файла, если они существуют в одной директории:
    1. `docker-compose.yml` (базовая конфигурация)
    2. `docker-compose.override.yml` (переопределения для конкретного окружения)

    Значения из `override.yml` **переопределяют или дополняют** значения из основного файла. Это позволяет на production-сервере хранить только `docker-compose.yml` для безопасной, изолированной конфигурации.

* **Альтернативный способ:** Явно указать несколько файлов с помощью флага `-f`. Файлы объединяются в указанном порядке, и последний указанный файл имеет наивысший приоритет.

    ```sh
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
    ```

#### 3. Секция `deploy` и интеграция с Docker Swarm

Секция `deploy` является ключевой при работе с **[Docker Swarm](../../Docker/Docker_swarm/docker_swarm_overview.md)** и используется исключительно командой `docker stack deploy`.

> **Важно:** Обычная команда `docker compose up` **полностью игнорирует** эту секцию.

Внутри `deploy` определяются параметры, связанные с развертыванием, масштабированием и поведением сервиса в кластере Swarm.

* **Основные параметры:**
  * `replicas`: Количество экземпляров (контейнеров) сервиса.
  * `update_config`: Стратегия выполнения обновлений (rolling updates).
  * `restart_policy`: Политика перезапуска в случае сбоя.
  * `placement`: Ограничения на размещение контейнеров (например, `constraints: [node.role == worker]`).
  * `resources`: Ограничения на потребление CPU и памяти.
  * `labels`: Ключевой механизм для интеграции с другими системами, например, с реверс-прокси **[Traefik](../../WebServers/Traefik/traefik_overview.md)**.

> Подробнее о развертывании стеков в Swarm читайте в руководстве [Развертывание приложений в Docker Swarm с помощью docker stack deploy](../../Docker/Docker_swarm/swarm_stack_deployment.md).

#### 4. Масштабирование сервисов (для `docker compose`)

Для простого горизонтального масштабирования сервисов, управляемых через `docker compose` на **одной машине**, используется флаг `--scale`.

```sh
# Запустить 3 экземпляра сервиса 'worker' и 1 экземпляр всех остальных
docker compose up -d --scale worker=3
```

Эта команда создаст независимые контейнеры для указанного сервиса, в отличие от `replicas` в Swarm, которые управляются централизованно.

### Практические сценарии

#### Пример: HA-кластер PostgreSQL с Patroni

Docker Compose отлично подходит для моделирования сложных систем. Данный пример демонстрирует развертывание отказоустойчивого кластера PostgreSQL.

* **Концепция:** В основе лежит **[Patroni](../../Databases/PostgreSQL/Concepts/high_availability.md)**, система для автоматизации высокой доступности PostgreSQL.
* **Компоненты стека:**
  * **etcd**: Распределенное хранилище конфигурации для выбора лидера и хранения состояния кластера.
  * **HAProxy**: Балансировщик нагрузки для направления запросов на ведущий узел и реплики.
  * **Три узла Patroni**: Экземпляры PostgreSQL, управляемые Patroni.

```yaml
version: '3.5'

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

  patroni1:
    image: 'bitnami/patroni:2.0'
    environment:
      - PATRONI_NAME=patroni1
      - PATRONI_SCOPE=my-postgres-cluster
      - PATRONI_RESTAPI_URL=http://patroni1:8008
      - PATRONI_ETCD_HOSTS=etcd:2379
      - PATRONI_POSTGRESQL_CONNECT_ADDRESS=patroni1:5432
      - PATRONI_POSTGRESQL_LISTEN=0.0.0.0:5432
      - PATRONI_POSTGRESQL_DATA_DIR=/data/patroni1
    volumes:
      - patroni_data1:/data/patroni1
    depends_on:
      - etcd

  patroni2:
    image: 'bitnami/patroni:2.0'
    environment:
      - PATRONI_NAME=patroni2
      - PATRONI_SCOPE=my-postgres-cluster
      - PATRONI_RESTAPI_URL=http://patroni2:8008
      - PATRONI_ETCD_HOSTS=etcd:2379
      - PATRONI_POSTGRESQL_CONNECT_ADDRESS=patroni2:5432
      - PATRONI_POSTGRESQL_LISTEN=0.0.0.0:5432
      - PATRONI_POSTGRESQL_DATA_DIR=/data/patroni2
    volumes:
      - patroni_data2:/data/patroni2
    depends_on:
      - etcd

  patroni3:
    image: 'bitnami/patroni:2.0'
    environment:
      - PATRONI_NAME=patroni3
      - PATRONI_SCOPE=my-postgres-cluster
      - PATRONI_RESTAPI_URL=http://patroni3:8008
      - PATRONI_ETCD_HOSTS=etcd:2379
      - PATRONI_POSTGRESQL_CONNECT_ADDRESS=patroni3:5432
      - PATRONI_POSTGRESQL_LISTEN=0.0.0.0:5432
      - PATRONI_POSTGRESQL_DATA_DIR=/data/patroni3
    volumes:
      - patroni_data3:/data/patroni3
    depends_on:
      - etcd

volumes:
  patroni_data1:
  patroni_data2:
  patroni_data3:
```

### Дополнительная информация

Для получения полного списка директив и их синтаксиса обратитесь к следующим ресурсам:

* **[Справочник по директивам Docker Compose](./docker_compose_directives.md)**
* **[Сравнение версий файла Docker Compose (v2 vs v3)](./docker_compose_versions_comparison.md)**
