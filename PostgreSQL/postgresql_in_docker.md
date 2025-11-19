# PostgreSQL в Docker: Руководство по развертыванию

Запуск PostgreSQL в Docker — популярная практика как для разработки, так и для production-окружений. Это обеспечивает изоляцию, переносимость и простоту управления.

## 1. Как работает Docker: Краткий обзор

Прежде чем погружаться в детали, важно понимать ключевые технологии Docker, которые делают возможной контейнеризацию в Linux:

- **Namespaces (Пространства имен)**: Обеспечивают изоляцию. Процесс в контейнере "видит" только свою собственную файловую систему, сеть, пользователей и процессы, как будто он один в системе.
- **Control Groups (cgroups)**: Ограничивают ресурсы, которые может потреблять контейнер: CPU, RAM, дисковый I/O. Это позволяет нескольким контейнерам работать на одном хосте, не мешая друг другу.
- **Union File Systems (UnionFS)**: Создают слоеную файловую систему. Образ Docker состоит из нескольких слоев "только для чтения". Когда контейнер запускается, поверх них добавляется тонкий слой "для записи". Это позволяет эффективно хранить образы и быстро запускать контейнеры.

## 2. Мифы и реальность

1.  **"Docker медленнее, чем bare-metal"**:
    -   **Реальность:** Накладные расходы Docker на Linux минимальны. Основные потери производительности (обычно 3-5%, в редких случаях до 15%) связаны с сетевой виртуализацией (bridge network) и операциями ввода-вывода через storage drivers. Для большинства приложений разница незаметна.

2.  **"Это ненадежно для production"**:
    -   **Реальность:** Это миф. При правильной настройке Docker является надежной средой. Ключевые аспекты — это корректное управление данными (использование `volumes`), настройка безопасности и мониторинг.

---

## 3. Запуск и управление контейнером PostgreSQL

### 3.1. Предварительная загрузка образа (docker pull)

Хотя команда `docker run` автоматически загрузит образ, если его нет локально, хорошей практикой является предварительная загрузка с помощью `docker pull`. Это позволяет контролировать процесс и экономить время при запуске.

```bash
docker pull postgres:16.3
```

### 3.2. Базовый запуск

Для запуска контейнера используется `docker run`. Обязательным параметром для официального образа является пароль суперпользователя.

```bash
# Запускаем контейнер с именем pg-server, задаем пароль и запускаем в фоне
docker run --name pg-server -e POSTGRES_PASSWORD=mysecretpassword -d postgres:16.3
```

-   `--name pg-server`: Задает имя контейнера для удобства обращения.
-   `-e POSTGRES_PASSWORD=...`: Устанавливает переменную окружения.
-   `-d`: Запускает контейнер в фоновом режиме (detached).
-   `postgres:16.3`: Указывает образ и его версию. **Всегда закрепляйте (pin) версию**, избегая тега `latest`, чтобы предотвратить неожиданные обновления.

### 3.3. Сохранение данных (Volumes)

**Критически важно:** Данные внутри контейнера эфемерны. При `docker rm` (удалении контейнера) все данные теряются. При `docker stop/start` данные сохраняются, но этот подход не для production. Для надежного хранения используйте **тома (volumes)**.

```bash
# Создаем именованный том pg-data и монтируем его
docker run --name pg-server \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -v pg-data:/var/lib/postgresql/data \
  -d postgres:16.3
```

-   `-v pg-data:/var/lib/postgresql/data`: Создает том `pg-data` и монтирует его в директорию `/var/lib/postgresql/data` внутри контейнера. Теперь данные переживут удаление контейнера.

### 3.4. Сеть и доступ к базе данных

По умолчанию Docker использует сеть `bridge`. Для изоляции и удобства обращения по именам лучше создавать пользовательские сети.

```bash
# 1. Создаем сеть
docker network create pg-net

# 2. Запускаем контейнер в этой сети и пробрасываем порт
docker run --name pg-server \
  --network pg-net \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -p 5432:5432 \
  -v pg-data:/var/lib/postgresql/data \
  -d postgres:16.3
```

-   `--network pg-net`: Подключает контейнер к созданной сети. Контейнеры в одной сети могут обращаться друг к другу по именам.
-   `-p 5432:5432`: Пробрасывает порт `5432` с хоста на порт `5432` в контейнере для внешнего доступа.

### 3.5. Подключение и управление

**Подключение через `docker exec`**:

```bash
# 1. Запустить интерактивную сессию psql от имени пользователя postgres
docker exec -it pg-server psql -U postgres

# 2. Или сначала запустить shell в контейнере, а затем psql
docker exec -it pg-server bash
# > su - postgres
# > psql
```

**Использование временного клиент-контейнера (удобный паттерн)**:

```bash
# Запускаем временный контейнер, который подключится к pg-server по сети pg-net
# --rm - автоматически удалит контейнер после выхода
docker run --rm -it --network=pg-net postgres:16.3 psql -h pg-server -U postgres
```

**Инспекция контейнера**:

```bash
# Показывает всю информацию о контейнере, включая IP-адрес в сети Docker
docker inspect pg-server
```

---

## 4. Безопасность

### 4.1. Доверенные и минимальные образы
Используйте только официальные образы (`postgres`) или образы из доверенного внутреннего registry. Образы из неизвестных источников могут содержать уязвимости или вредоносный код.

**Рекомендации:**
*   **Минимальные образы:** Отдавайте предпочтение минимальным образам (например, на базе Alpine), чтобы уменьшить поверхность атаки, так как они содержат меньше предустановленных пакетов и утилит.
*   **Закрепление версий:** Всегда используйте конкретные теги версий (например, `postgres:16.3`) вместо `latest`, чтобы обеспечить воспроизводимость и избежать неожиданных обновлений с потенциальными уязвимостями.

### 4.2. Ограничение сетевого доступа
Порты базы данных **никогда не должны быть напрямую доступны из интернета**. Доступ к PostgreSQL должен осуществляться через:
*   **Внутреннюю сеть Docker:** Для взаимодействия между сервисами в Docker Compose.
*   **Прокси/Балансировщик:** Например, PgBouncer, который может выступать в роли шлюза.
*   **Фаервол:** Ограничивайте доступ только с доверенных IP-адресов или подсетей.
*   **VPN/SSH-туннели:** Для административного доступа.

При использовании `docker-compose.yml` тщательно контролируйте секцию `ports`, пробрасывая только необходимые порты и только для внутренних нужд, если это возможно.

### 4.3. `pg_hba.conf`: Аутентификация `trust` и другие настройки

По умолчанию официальный образ использует метод аутентификации `trust` для всех подключений. Это означает, что **любой может подключиться к базе данных без пароля**.

Для production это необходимо исправить.

1.  **Создайте свой `pg_hba.conf` на хосте:**
    ```conf
    # my_pg_hba.conf
    local   all             all                                     md5
    host    all             all             0.0.0.0/0               md5
    ```

2.  **Смонтируйте его в контейнер:**
    ```bash
    docker run --name pg-server \
      -e POSTGRES_PASSWORD=mysecretpassword \
      -v pg-data:/var/lib/postgresql/data \
      -v ./my_pg_hba.conf:/var/lib/postgresql/data/pg_hba.conf \
      -d postgres:16.3
    ```

### 4.4. Запуск от имени непривилегированного пользователя (Non-root)
По умолчанию многие образы Docker запускают процессы от имени пользователя `root` внутри контейнера. Это может быть небезопасно. Если контейнер будет скомпрометирован, злоумышленник получит root-доступ внутри контейнера, что может привести к эскалации привилегий на хост-системе.

**Рекомендации:**
*   Используйте образы, которые по умолчанию запускаются от имени непривилегированного пользователя (например, многие образы Bitnami).
*   В `Dockerfile` явно указывайте пользователя с помощью директивы `USER`.
*   Убедитесь, что монтируемые тома имеют правильные права доступа для непривилегированного пользователя.

### 4.5. Управление конфигурацией
Конфигурационные файлы, содержащие чувствительные данные или специфические настройки, следует монтировать в контейнер как тома (`-v`) или использовать Docker Secrets/Config, а не встраивать их непосредственно в образ. Это позволяет легко обновлять конфигурацию без пересборки образа и предотвращает утечку чувствительных данных.

---

## 5. Расширенные сценарии

### 5.1. Инициализация базы данных скриптами

Официальный образ PostgreSQL позволяет автоматически выполнять SQL и shell-скрипты при первом запуске контейнера. Для этого их нужно поместить в директорию `/docker-entrypoint-initdb.d`.

```bash
# Пример: монтируем директорию с init-скриптами
docker run --name pg-server \
    -e POSTGRES_PASSWORD=mysecretpassword \
    -v pg-data:/var/lib/postgresql/data \
    -v ./init-scripts:/docker-entrypoint-initdb.d \
    -d postgres:16.3
```

-   Скрипты (`.sh`, `.sql`) будут выполнены в алфавитном порядке. Это отличный способ для создания пользователей, баз данных, схем и т.д.

### 5.2. Использование с Docker Compose

Для управления многоконтейнерными приложениями используйте [**Docker Compose**](../Docker/docker_compose.md). Это позволяет декларативно описать все сервисы, сети и тома в одном `docker-compose.yml` файле.

**Пример `docker-compose.yml`:**
```yaml
version: '3.8'

services:
  db:
    image: postgres:16.3
    restart: always
    networks:
      - app-net
    environment:
      - POSTGRES_USER=myuser
      - POSTGRES_PASSWORD=mysecretpassword
      - POSTGRES_DB=myapp
    ports:
      - "5432:5432" # В production-среде рекомендуется не пробрасывать порт напрямую.
    volumes:
      - db-data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d # монтируем init-скрипты
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myuser -d myapp"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    networks:
      - app-net
    ports:
      - "8080:80"
    depends_on:
      db:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql://myuser:mysecretpassword@db:5432/myapp

volumes:
  db-data:
    # Этот том будет управляться Docker

networks:
  app-net:
    driver: bridge
```
**Важные аспекты межсервисного взаимодействия:**

*   **Имена сервисов как DNS-имена:** В рамках одной Docker-сети сервисы могут обращаться друг к другу по их именам (`db` для базы данных). Docker автоматически предоставляет DNS-разрешение.
*   **Внутренние и внешние порты:** При обращении из одного сервиса к другому внутри той же сети всегда используйте внутренний порт контейнера (`db:5432`), а не внешний порт хоста.
*   **`healthcheck` и `depends_on`:** `healthcheck` позволяет Docker'у проверять, что PostgreSQL внутри контейнера действительно готов принимать соединения. `depends_on` с условием `service_healthy` гарантирует, что сервис `app` запустится только после того, как `db` пройдет проверку здоровья.

### 5.3. Мониторинг PostgreSQL в Docker Compose

Для полноценного мониторинга можно развернуть стек, включающий Prometheus, Grafana и Postgres Exporter.

**Пример `docker-compose.monitoring.yml`:**
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16.3
    restart: always
    environment:
      POSTGRES_USER: myuser
      POSTGRES_PASSWORD: mysecretpassword
      POSTGRES_DB: myapp
    volumes:
      - pg_data:/var/lib/postgresql/data
    networks:
      - monitor-net

  pg_exporter:
    image: prometheuscommunity/postgres-exporter:v0.15.0
    restart: always
    environment:
      DATA_SOURCE_NAME: "postgresql://myuser:mysecretpassword@postgres:5432/myapp?sslmode=disable"
    networks:
      - monitor-net
    depends_on:
      - postgres

  prometheus:
    image: prom/prometheus:v2.51.2
    restart: always
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    networks:
      - monitor-net
    depends_on:
      - pg_exporter

  grafana:
    image: grafana/grafana:10.4.2
    restart: always
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning/:/etc/grafana/provisioning/
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
    ports:
      - "3000:3000"
    networks:
      - monitor-net
    depends_on:
      - prometheus

volumes:
  pg_data:
  prometheus_data:
  grafana_data:

networks:
  monitor-net:
```
Для этого примера также потребуются файлы конфигурации для `prometheus.yml` и `grafana/provisioning/` для автоматической настройки источника данных и дашбордов.

### 5.4. Инструменты управления: PgAdmin и PgBouncer

**Пример `docker-compose.tools.yml`:**
```yaml
version: '3.8'

services:
  postgres:
    # ... (конфигурация как в примере выше) ...
    networks:
      - app-net

  pgbouncer:
    image: edoburu/pgbouncer:1.22.1
    restart: always
    environment:
      DB_HOST: postgres
      DB_USER: myuser
      DB_PASSWORD: mysecretpassword
      DB_NAME: myapp
      POOL_MODE: session
    ports:
      - "6432:6432" # Порт для подключения через pgbouncer
    networks:
      - app-net
    depends_on:
      - postgres

  pgadmin:
    image: dpage/pgadmin4:8.5
    restart: always
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@example.com
      PGADMIN_DEFAULT_PASSWORD: admin
    ports:
      - "8080:80"
    volumes:
      - pgadmin_data:/var/lib/pgadmin
      - ./pgadmin_servers.json:/pgadmin4/servers.json # Автоматическая настройка серверов
    networks:
      - app-net
    depends_on:
      - postgres

volumes:
  pg_data:
  pgadmin_data:

networks:
  app-net:
```

### 5.5. Репликация с Bitnami RepManager

Образы Bitnami с `repmgr` упрощают настройку кластера с физической репликацией.

**Преимущества образов Bitnami:**
*   **Non-root контейнеры:** Повышают безопасность.
*   **Регулярные обновления:** Оперативно включают исправления уязвимостей.
*   **Удобство для кластеров:** Значительно упрощают настройку репликации и HA.

**Пример `docker-compose.replication.yml`:**
```yaml
version: '3.8'

services:
  postgresql-primary:
    image: bitnami/postgresql-repmgr:15
    restart: always
    environment:
      - POSTGRESQL_USERNAME=postgres
      - POSTGRESQL_PASSWORD=mysecretpassword
      - POSTGRESQL_DATABASE=myapp
      - REPMGR_PASSWORD=repmgrpassword
      - REPMGR_PRIMARY_HOST=postgresql-primary
      - REPMGR_PARTNER_NODES=postgresql-primary,postgresql-replica
      - REPMGR_NODE_NAME=postgresql-primary
    volumes:
      - pg_primary_data:/bitnami/postgresql
    networks:
      - repl-net

  postgresql-replica:
    image: bitnami/postgresql-repmgr:15
    restart: always
    environment:
      - POSTGRESQL_USERNAME=postgres
      - POSTGRESQL_PASSWORD=mysecretpassword
      - POSTGRESQL_DATABASE=myapp
      - REPMGR_PASSWORD=repmgrpassword
      - REPMGR_PRIMARY_HOST=postgresql-primary
      - REPMGR_PARTNER_NODES=postgresql-primary,postgresql-replica
      - REPMGR_NODE_NAME=postgresql-replica
    volumes:
      - pg_replica_data:/bitnami/postgresql
    networks:
      - repl-net
    depends_on:
      - postgresql-primary

volumes:
  pg_primary_data:
  pg_replica_data:

networks:
  repl-net:
```
В этом примере `repmgr` автоматически настраивает `postgresql-replica` как реплику `postgresql-primary` и обеспечивает автоматическое переключение при сбое.

### 5.6. Отказоустойчивый кластер с Patroni

Patroni — это более продвинутый инструмент для создания HA-кластеров.

**Пример `docker-compose.patroni.yml`:**
```yaml
version: '3.8'

services:
  etcd:
    image: bitnami/etcd:3.5
    environment:
      - ALLOW_NONE_AUTHENTICATION=yes
      - ETCD_ADVERTISE_CLIENT_URLS=http://etcd:2379
    networks:
      - patroni-net

  haproxy:
    image: haproxy:2.9
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    ports:
      - '5000:5000' # Порт для записи (мастер)
      - '5001:5001' # Порт для чтения (реплики)
      - '8008:8008' # Статистика HAProxy
    networks:
      - patroni-net
    depends_on:
      - patroni1
      - patroni2

  patroni1:
    image: bitnami/postgresql:15 # Используйте совместимую с Patroni версию
    restart: always
    environment:
      - PATRONI_NAME=patroni1
      - PATRONI_SCOPE=my-cluster
      - PATRONI_ETCD_HOST=etcd
      - POSTGRESQL_USERNAME=postgres
      - POSTGRESQL_PASSWORD=mysecretpassword
    volumes:
      - patroni1_data:/bitnami/postgresql
    networks:
      - patroni-net
    depends_on:
      - etcd

  patroni2:
    image: bitnami/postgresql:15
    restart: always
    environment:
      - PATRONI_NAME=patroni2
      - PATRONI_SCOPE=my-cluster
      - PATRONI_ETCD_HOST=etcd
      - POSTGRESQL_USERNAME=postgres
      - POSTGRESQL_PASSWORD=mysecretpassword
    volumes:
      - patroni2_data:/bitnami/postgresql
    networks:
      - patroni-net
    depends_on:
      - etcd

volumes:
  patroni1_data:
  patroni2_data:
  
networks:
  patroni-net:
```
*В данном примере `etcd` используется как распределенное хранилище для управления состоянием кластера, а `HAProxy` выступает в роли балансировщика, направляя запросы на текущий мастер-узел.*
