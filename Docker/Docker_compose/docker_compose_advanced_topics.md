# Продвинутые темы

### Продвинутый пример: HA-кластер PostgreSQL с Patroni

Docker Compose отлично подходит для моделирования сложных систем, таких как отказоустойчивый кластер PostgreSQL на базе [Patroni](../../PostgreSQL/scaling.md#высокая-доступность-high-availability-с-patroni).

В этом примере разворачивается полноценный кластер, состоящий из:

-   **etcd**: Распределенное хранилище конфигурации, которое Patroni использует для выбора лидера и хранения состояния кластера.
-   **HAProxy**: Балансировщик нагрузки, который направляет запросы на чтение-запись на текущий ведущий узел (master), а запросы только на чтение — на реплики.
-   **Три узла Patroni**: Каждый узел запускает экземпляр PostgreSQL и управляется Patroni.

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
      - PATroni_RESTAPI_URL=http://patroni1:8008
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

- **Масштабирование:** Запуск нескольких экземпляров одного сервиса:

  ```sh
  docker compose up -d --scale <имя-сервиса>=<количество>
  ```

- **Секция `deploy`:**

  Эта секция является ключевой при работе с **Docker Swarm** и используется исключительно командой `docker stack deploy`. Обычная команда `docker compose up` **полностью игнорирует** эту секцию.

  Внутри `deploy` определяются все параметры, связанные с развертыванием, масштабированием и поведением сервиса в кластере.

  **Основные параметры:**

  *   `replicas`: Количество экземпляров (контейнеров) сервиса, которые должны быть запущены.
  *   `update_config`: Стратегия выполнения обновлений (rolling updates).
      *   `parallelism`: Сколько контейнеров обновлять одновременно.
      *   `delay`: Задержка между обновлениями групп контейнеров.
  *   `restart_policy`: Политика перезапуска в случае сбоя.
  *   `placement`: Ограничения на размещение контейнеров (например, `constraints: [node.role == worker]`).
  *   `resources`: Ограничения на потребление CPU и памяти.
  *   `labels`: **Ключевой механизм для интеграции с другими системами**, такими как реверс-прокси [Traefik](../../WebServers/Traefik/traefik_overview.md).

  **Пример использования с Traefik:**

  В этом примере метки (`labels`) сообщают Traefik, как маршрутизировать трафик на сервис `my-web-app`.

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
          # Включаем Traefik для этого сервиса
          - "traefik.enable=true"
          # Задаем правило маршрутизации по домену
          - "traefik.http.routers.my-app.rule=Host(`app.example.com`)"
          # Указываем, что роутер работает на HTTPS
          - "traefik.http.routers.my-app.entrypoints=websecure"
          # Включаем получение SSL-сертификата через Let's Encrypt
          - "traefik.http.routers.my-app.tls.certresolver=myresolver"
          # Указываем порт, на котором работает приложение внутри контейнера
          - "traefik.http.services.my-app.loadbalancer.server.port=8000"

  networks:
    traefik-public:
      external: true
  ```

  В этом примере также используется [интерполяция переменных](#интерполяция-использование-переменных-в-composeyml) для тега образа (`${APP_VERSION:-latest}`), что является стандартной практикой в CI/CD для развертывания конкретных версий приложения.

- **Интерполяция: использование переменных в `compose.yml`**:

  Docker Compose позволяет использовать переменные окружения из вашего терминала или из файла `.env` для подстановки значений в `compose.yml`. Это делает конфигурацию гибкой и позволяет избежать жесткого кодирования портов, тегов образов или паролей.

  **Источники переменных и приоритет:**

  1.  **Переменные из оболочки (shell):** Наивысший приоритет.
  2.  **Файл `.env`:** Используются, если переменная не задана в оболочке.

  **Синтаксис:**

  - `${VARIABLE}`: Простая подстановка.
  - `${VARIABLE:-default}`: Подставить `default`, если `VARIABLE` не задана.
  - `${VARIABLE:?error message}`: Показать ошибку и прервать выполнение, если `VARIABLE` не задана.

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
      image: my-app:${WEB_IMAGE_TAG}
      ports:
        - "${WEB_HOST_PORT}:80"
  ```

  **Как это работает:**

  - Если запустить `docker compose up`, будет использован образ `my-app:1.2.0` и порт `8080`.
  - Если выполнить команду `WEB_IMAGE_TAG=1.3.0 docker compose up`, то будет использован образ `my-app:1.3.0`, так как переменная из оболочки имеет более высокий приоритет.
  - Если убрать `WEB_IMAGE_TAG` из `.env` и не задавать в оболочке, будет использовано значение по умолчанию `latest`.

- **Использование нескольких файлов и переопределение (`-f`)**:

  Для сложных проектов часто требуется иметь базовую конфигурацию и изменять ее для разных окружений (например, для локальной разработки добавлять порты и монтировать исходный код). Для этого используется флаг `-f`, который можно указывать несколько раз.

  **Правило:** Файлы считываются и объединяются в том порядке, в котором они указаны. Значения из последних файлов **переопределяют** значения из предыдущих.

  **Лучшая практика: `docker-compose.override.yml`**

  Вам не обязательно использовать флаг `-f`. По умолчанию `docker compose` автоматически ищет и использует два файла, если они существуют в одной директории:
  1. `docker-compose.yml` (базовая конфигурация)
  2. `docker-compose.override.yml` (переопределения для разработки)

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

  **Как это работает:**
  - При запуске `docker compose up` в этой директории, Compose автоматически объединит оба файла. В итоговой конфигурации сервис `web` будет собираться из исходников, публиковать порт `8080` и монтировать локальную директорию.
  - При этом на production-сервере будет лежать только docker-compose.yml, и там приложение запустится в безопасной, изолированной конфигурации из готового образа.
