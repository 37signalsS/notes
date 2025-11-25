# Docker Compose

**Docker Compose** — это инструмент для определения и запуска многоконтейнерных приложений Docker. С помощью одного YAML-файла вы описываете все сервисы, [сети](./docker_network.md) и [тома](./docker_volumes.md), а затем одной командой создаете и запускаете всю конфигурацию.

**`docker compose` (v2) vs. `docker-compose` (v1)**

- **`docker compose` (v2, без дефиса):** Современный плагин, интегрированный в Docker CLI. Написан на Go.
- **`docker-compose` (v1, с дефисом):** Устаревшая версия, отдельный исполняемый файл на Python.

---

## Пример файла `compose.yml`

Рассмотрим пример для веб-приложения (`web`) и базы данных (`database`), которые работают в общей изолированной сети(могу в ней общаться между собой по именнам сервисов присвоенных им, при помощи dns имени, например, db) и используют именованный том для хранения данных.

```yaml
# Имя проекта, которое будет использоваться как префикс
name: taxi-app

services:
  web:
    build: .
    image: my-taxi-app # Имя для локально собранного образа
    restart: always
    env_file:
      - .env
    ports:
      # Проброс портов: IP:ХОСТ_ПОРТ:КОНТЕЙНЕР_ПОРТ
      - "100.64.0.13:3845:3000"
    networks:
      - app-network
    depends_on:
      database:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://127.0.0.1:3000/api/health || exit 1"]
      interval: 10s
      start_period: 30s

  database:
    image: paradedb/paradedb:0.20.0-pg17
    restart: always
    # Переменные окружения загружаются из .env файла
    env_file:
      - .env
    ports:
      - "100.64.0.13:3856:5432"
    networks:
      - app-network
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 30s
      retries: 3
      start_period: 80s

networks:
  app-network:
    driver: bridge

volumes:
  db-data:
    driver: local
```

### Файл `.env` для секретов и конфигураций

> **ВАЖНО:** Никогда не храните пароли, токены и другие секреты прямо в `compose.yml`. Используйте для этого `.env` файл.

```ini
# .env

POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_strong_password_here
POSTGRES_DB=taxi

API_KEY=some_secret_key
```

---

## Ключевые директивы

### `services`

- `image` vs. `build`:

  - `image`: Указывает готовый образ из registry (например, `postgres:16.3`).

  - `build`: Указывает путь к `Dockerfile` для сборки образа локально (`build: .`).

- `ports`: Пробрасывает порты в формате `IP:ХОСТ_ПОРТ:КОНТЕЙНЕР_ПОРТ`.

- `environment` и `env_file`:
  - `environment`: Задает переменные окружения прямо в YAML (`environment: [ "POSTGRES_USER=user" ]`). **Не используйте для секретов.**
  - `env_file`: Загружает переменные из файла. **Предпочтительный способ.**

- `depends_on`: Определяет порядок запуска сервисов. В примере `web` не запустится, пока `database` не станет `healthy`.

- `command` и `entrypoint`: Позволяют переопределить инструкции `CMD` и `ENTRYPOINT` из `Dockerfile` образа.
  
  Директива `command` в `compose.yml` заменяет `CMD` в `Dockerfile`, а `entrypoint` заменяет `ENTRYPOINT`. Это позволяет изменять команду по умолчанию или основной исполняемый файл для конкретного сервиса без пересборки образа.
  
  Подробное описание их взаимодействия и таблица всех возможных комбинаций находятся в документе **[Dockerfile](./docker_dockerfile.md#entrypoint-vs-cmd)**.

- `user`: Запускает процесс внутри контейнера от имени указанного пользователя (`user:group` или `user`). Использование `user: "0:0"` (root) может быть небезопасно.

- `restart`: Определяет политику перезапуска контейнера.

| Политика | Описание |
| :--- | :--- |
| `no` | Не перезапускать (по умолчанию). |
| `on-failure` | Перезапускать только при завершении с ошибкой. Можно добавить `:<число_попыток>`. |
| `always` | Перезапускать всегда, кроме случаев, когда контейнер остановлен вручную. |
| `unless-stopped` | Перезапускать всегда, даже после перезагрузки демона, кроме остановки вручную. |

- `healthcheck`: Позволяет Docker проверять работоспособность приложения внутри контейнера. Эта директива аналогична инструкции [`HEALTHCHECK` в `Dockerfile`](./docker_dockerfile.md#healthcheck) и имеет те же параметры (`test`, `interval`, `timeout`, `retries`, `start_period`).

---

### Версии файла Compose: Ключевые различия (v2 vs v3)

#### `depends_on` и проверка состояния

Это **главное функциональное различие** при использовании `docker compose up`:

-   **Версия 2.x:** `depends_on` поддерживает опцию `condition: service_healthy`. Это заставляет один сервис ждать, пока зависимый сервис не только запустится, но и пройдет свою проверку `healthcheck`.
    ```yaml
    # V2 СИНТАКСИС
    depends_on:
      database:
        condition: service_healthy
    ```
-   **Версия 3.x:** Формат **не поддерживает** `condition`. Директива `depends_on` гарантирует только **порядок запуска** сервисов, но не их готовность к работе. Для ожидания полной готовности сервиса (например, инициализации базы данных) в v3 необходимо использовать дополнительные скрипты, такие как `wait-for-it.sh` или аналоги.

#### Ограничение ресурсов (CPU, память)

-   **Версия 2.x:** Лимиты ресурсов задавались прямо на уровне сервиса с помощью ключей `cpu_shares`, `mem_limit` и т.д.

    ```yaml
    # V2 СИНТАКСИС
    web:
      image: nginx:1.25.5
      mem_limit: 1g
      cpu_shares: 73
    ```
-   **Версия 3.x:** Эти ключи были **убраны**. Вместо них появилась секция `deploy`, предназначенная для Docker Swarm. Ограничения ресурсов теперь задаются внутри нее. **Важно:** секция `deploy` и все ее содержимое, а также директивы `container_name` и `restart` **полностью игнорируются** командой `docker compose up` и используются только командой `docker stack deploy` в Swarm-кластере.

    ```yaml
    # V3 СИНТАКСИС
    web:
      image: nginx:1.25.5
      deploy:
        resources:
          limits:
            cpus: '0.50'
            memory: 512M
        # Другие параметры развертывания для Swarm, например, replicas, update_config
        replicas: 3
    ```
---

## Основные команды `docker compose`

| Команда | Описание |
| :--- | :--- |
| `docker compose up` | Создает и запускает контейнеры. С флагом `-d` (detached) запускает в фоновом режиме. Флаг `--build` принудительно пересобирает образы. |
| `docker compose down` | Останавливает и удаляет контейнеры, сети. С флагом `-v` удаляет и тома (volumes). |
| `docker compose ps` | Показывает статус контейнеров проекта. |
| `docker compose logs` | Выводит логи сервисов. С флагом `-f` (follow) выводит логи в реальном времени. |
| `docker compose exec <сервис> <команда>` | Выполняет команду внутри работающего контейнера (например, `docker compose exec web sh`). |
| `docker compose run <сервис> <команда>` | Запускает новый контейнер для выполнения одноразовой команды. |
| `docker compose build` | Собирает или пересобирает образы для сервисов. |
| `docker compose pull` | Скачивает последние версии образов для сервисов. |
| `docker compose config` | Проверяет и отображает итоговую конфигурацию после применения всех переменных и шаблонов. |

---

### Детальный разбор `docker compose up`

Команда `up` имеет несколько важных флагов, которые управляют её поведением.

- **Поведение по умолчанию (без флагов)**: Если не использовать флаги, `docker compose up` работает «интеллектуально». Он **пересоздаст контейнер только в том случае, если его конфигурация в `compose.yml` или соответствующий Docker-образ изменились**. Если изменений не было, команда просто запустит остановленные контейнеры. 

- **`--force-recreate`**: Этот флаг принудительно **пересоздаёт все контейнеры** с нуля, даже если их конфигурация или образ не изменились. Он останавливает, удаляет (`docker rm`) и затем создаёт абсолютно новые контейнеры. 

    - **Когда использовать** Для "жёсткой перезагрузки" сервиса, который работает некорректно, или чтобы гарантировать абсолютно чистую среду при запуске.
    - **Внимание!** Данные, хранящиеся **внутри файловой системы контейнера** (не в `volumes`), будут **безвозвратно утеряны**.

- **`--no-recreate`**: Противоположность предыдущему флагу. Он **никогда не будет пересоздавать** контейнеры, даже если их конфигурация изменилась. Он просто запустит существующие остановленные контейнеры.

- **`--build`**: Принудительно выполняет сборку образов перед запуском сервисов. Полезно, когда вы внесли изменения в `Dockerfile`, но не в `compose.yml`.

## Продвинутые темы

### Продвинутый пример: HA-кластер PostgreSQL с Patroni

Docker Compose отлично подходит для моделирования сложных систем, таких как отказоустойчивый кластер PostgreSQL на базе [Patroni](../PostgreSQL/scaling.md#высокая-доступность-high-availability-с-patroni).

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
  *   `labels`: **Ключевой механизм для интеграции с другими системами**, такими как реверс-прокси [Traefik](../WebServers/Traefik/traefik_overview.md).

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

---

## Использование Docker Compose для тестирования в CI/CD

По умолчанию `docker compose up` запускает сервисы в фоновом режиме и работает бесконечно. Это не подходит для CI/CD, где нужно запустить задачу (например, тесты), дождаться ее завершения и получить результат (успех или провал).

Для этого используется комбинация двух флагов:

-   `--exit-code-from <имя-сервиса>`: Указывает, что `docker compose` должен вернуть **код завершения (exit code)** от указанного сервиса. Если тесты в сервисе `tester` завершились с кодом `1` (ошибка), то и вся команда `docker compose up` завершится с кодом `1`.
-   `--abort-on-container-exit`: Указывает `docker compose` остановить **все** контейнеры, как только **любой** из них остановится. Это гарантирует, что вспомогательные сервисы (вроде базы данных) не останутся работать после завершения тестов.

### Запуск тестов в CI

Представим, что у нас есть сервис `web`, который нужно протестировать, и база данных `db`.

**Файл `docker-compose.yml` (базовый):**

```yaml
services:
  web:
    build: .
    depends_on:
      - db
    environment:
      - DB_HOST=db

  db:
    image: postgres:16.3
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
```

**Файл `docker-compose.test.yml` (переопределение для тестов):**

```yaml
services:
  web:
    # Переопределяем команду по умолчанию на запуск тестов
    command: ["npm", "test"]
```

**Команда для запуска в CI/CD:**

```bash
# 1. Запускаем сервисы, собираем образы, если нужно
#    - Ждем код завершения от сервиса 'web'
#    - Останавливаем все после завершения любого контейнера
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from web
```

Проверяем код завершения:

- Если 0, тесты прошли успешно.
- Если не 0, тесты провалились.

