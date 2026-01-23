# Продвинутые возможности Docker Compose

Этот документ описывает продвинутые техники работы с Docker Compose, которые упрощают управление сложными конфигурациями и различными окружениями.

## Базовые концепции

### Интерполяция переменных

Docker Compose позволяет использовать переменные окружения из вашего терминала или из файла `.env` для подстановки значений в `compose.yml`. Это делает конфигурацию гибкой и позволяет избежать жесткого кодирования портов, тегов образов или паролей.

**Приоритет и источники переменных:**

1.  **Переменные из оболочки (shell):** Наивысший приоритет.
2.  **Файл `.env` в корне проекта:** Используются, если переменная не задана в оболочке.

**Синтаксис:**

-   `${VARIABLE}`: Простая подстановка.
-   `${VARIABLE:-default}`: Подставить `default`, если `VARIABLE` не задана.
-   `${VARIABLE:?error message}`: Показать ошибку и прервать выполнение, если `VARIABLE` не задана.

**Пример:**

**Файл `.env`:**
```ini
# Задает тег по умолчанию для нашего веб-приложения
WEB_IMAGE_TAG=1.2.0
# Задает порт, который будет опубликован на хосте
WEB_HOST_PORT=8080
```

**Файл `compose.yml`:**
```yaml
services:
  web:
    image: my-app:${WEB_IMAGE_TAG:-latest}
    ports:
      - "${WEB_HOST_PORT}:80"
```

-   При запуске `docker compose up` будет использован образ `my-app:1.2.0` и порт `8080`.
-   При выполнении `WEB_IMAGE_TAG=1.3.0 docker compose up` будет использован образ `my-app:1.3.0`, так как переменная из оболочки имеет более высокий приоритет.

> **Важно:** Использование `.env` файлов удобно для разработки, но является **небезопасным для хранения секретов в production**. Переменные окружения могут легко утечь в логи или быть прочитаны через `docker inspect`. Для безопасного управления секретами используйте встроенные механизмы оркестраторов, такие как Docker Secrets или Kubernetes Secrets.
>
> Подробнее о рисках и лучших практиках читайте в заметке [Управление секретами в Docker](../Docker_security/secrets_management.md).

### Разделение конфигурации для разных окружений

Для сложных проектов часто требуется иметь базовую конфигурацию для production и изменять ее для локальной разработки (например, добавлять порты и монтировать исходный код).

**Лучшая практика: `docker-compose.override.yml`**

По умолчанию `docker compose` автоматически ищет и использует два файла, если они существуют в одной директории:
1.  `docker-compose.yml` (базовая конфигурация)
2.  `docker-compose.override.yml` (переопределения для конкретного окружения, например, разработки)

Значения из `override.yml` **переопределяют или дополняют** значения из основного файла.

**Пример:**

**Файл `docker-compose.yml` (базовый, для production):**
```yaml
services:
  web:
    image: my-app:1.3.0
    # порты не публикуются, исходники внутри образа
```

**Файл `docker-compose.override.yml` (для локальной разработки):**
```yaml
services:
  web:
    build: . # собирать локально
    ports:
      - "8080:80" # опубликовать порт
    volumes:
      - .:/app # монтировать исходный код
```

При запуске `docker compose up` на локальной машине Compose автоматически объединит оба файла. На production-сервере будет лежать только `docker-compose.yml`, и приложение запустится в безопасной, изолированной конфигурации.

В качестве альтернативы можно явно указать несколько файлов с помощью флага `-f`. Файлы объединяются в указанном порядке.

### Секция `deploy` и интеграция с Docker Swarm

Секция `deploy` является ключевой при работе с **[Docker Swarm](../../Docker/Docker_swarm/docker_swarm_overview.md)** и используется исключительно командой `docker stack deploy`.

> **Важно:** Обычная команда `docker compose up` **полностью игнорирует** эту секцию.

Внутри `deploy` определяются параметры, связанные с развертыванием, масштабированием и поведением сервиса в кластере Swarm.

**Основные параметры:**
*   `replicas`: Количество экземпляров (контейнеров) сервиса.
*   `update_config`: Стратегия выполнения обновлений (rolling updates).
*   `restart_policy`: Политика перезапуска в случае сбоя.
*   `placement`: Ограничения на размещение контейнеров (например, `constraints: [node.role == worker]`).
*   `resources`: Ограничения на потребление CPU и памяти.
*   `labels`: Ключевой механизм для интеграции с другими системами, такими как реверс-прокси [Traefik](../../WebServers/Traefik/traefik_overview.md).

**Пример использования с Traefik в Swarm:**
```yaml
version: '3.8'
services:
  my-web-app:
    image: my-app:${APP_VERSION:-latest}
    networks:
      - traefik-public
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 10s
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.my-app.rule=Host(`app.example.com`)"
        - "traefik.http.routers.my-app.entrypoints=websecure"
        - "traefik.http.routers.my-app.tls.certresolver=myresolver"
        - "traefik.http.services.my-app.loadbalancer.server.port=8000"

networks:
  traefik-public:
    external: true
```
> Подробнее о работе с Traefik в Swarm читайте в руководстве [Docker Swarm - Ingress Traffic Management with Traefik](../../Docker/Docker_swarm/swarm_ingress_traefik.md).

### Масштабирование сервисов (для `docker compose`)

Для простого горизонтального масштабирования сервисов, управляемых через `docker compose` на одной машине, используется флаг `--scale`.

```sh
# Запустить 3 экземпляра сервиса 'worker' и 1 экземпляр всех остальных
docker compose up -d --scale worker=3
```
Эта команда создаст независимые контейнеры для указанного сервиса.

## Практические сценарии

### Пример: HA-кластер PostgreSQL с Patroni

Docker Compose отлично подходит для моделирования сложных систем. Данный пример демонстрирует развертывание отказоустойчивого кластера PostgreSQL на базе **[Patroni](../../Databases/PostgreSQL/Concepts/high_availability.md)**.

Кластер состоит из:
-   **etcd**: Распределенное хранилище конфигурации для выбора лидера и хранения состояния кластера.
-   **HAProxy**: Балансировщик нагрузки для направления запросов на ведущий узел и реплики.
-   **Три узла Patroni**: Экземпляры PostgreSQL, управляемые Patroni.

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