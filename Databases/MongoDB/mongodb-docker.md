# MongoDB: Развёртывание в Docker

**Актуально для:** MongoDB 8.0.x, образы `mongodb/mongodb-community-server:8.0`, Docker Compose v2

---

## Определения

*   **`mongodb/mongodb-community-server`:** Официальный Docker-образ MongoDB Community Edition (с 5.0+; старый образ `mongo` также доступен, но `mongodb/mongodb-community-server` — канонический).
*   **Replica Set в Docker:** Минимальная отказоустойчивая конфигурация MongoDB. Даже для dev используется одноузловой RS, потому что Change Streams, транзакции и большинство production-фич требуют replica set.
*   **`rs.initiate()`:** Команда инициализации Replica Set. В Docker требует корректных hostname'ов контейнеров (не `localhost`).
*   **Docker Compose:** Инструмент оркестрации multi-container приложений (файл `docker-compose.yml`).
*   **Healthcheck:** Проверка готовности контейнера (`mongosh -u root -p example --authenticationDatabase admin --eval "db.adminCommand('ping')" --quiet`), используемая Docker'ом для управления жизненным циклом. **Важно:** после инициализации root-пользователя healthcheck должен включать учётные данные.
*   **`--bind_ip_all`:** Флаг mongod, заставляющий слушать на всех интерфейсах (0.0.0.0), необходимый для связи между контейнерами.
*   **Named volumes:** Docker volumes с явным именем (например, `mongo-data:/data/db`), сохраняющие данные после удаления контейнера.

---

## Предварительные требования (Prerequisites)

| Требование | Минимальное значение | Рекомендуемое | Примечание |
| :--- | :--- | :--- | :--- |
| **Docker Engine** | 20.10+ | 24.0+ | С поддержкой BuildKit |
| **Docker Compose** | v2.0+ (plugin) | v2.24+ | `docker compose` (не `docker-compose`) |
| **CPU** | 2 vCPU | 4+ vCPU | MongoDB 8.0 требует AVX (современные x86); ARM64 поддерживается с 6.0+ |
| **RAM** | 2 GB | 4+ GB | WiredTiger cache по умолчанию 50% RAM; задавайте лимиты |
| **Диск** | 10 GB | 50+ GB (SSD) | Named volumes на быстром хранилище; для production — отдельные диски на узел |
| **Сеть** | Bridge (default) | Custom bridge / overlay | Контейнеры должны резолвить имена друг друга |
| **Порты** | 27017 (внутренний) | 27017 + экспорт только при необходимости | Не пробрасывать наружу без TLS/firewall |

---

## Базовые концепции

### Зачем RS даже в dev

*   **Change Streams** (CDC, коннекторы Kafka) работают только на RS/sharded cluster.
*   **Транзакции** (multi-document) требуют RS.
*   **Time-series, resharding, queryable encryption** — частично требуют RS.
*   Standalone `mongod` подходит только для локального прототипирования CRUD.

### Архитектура compose-файла

```
docker-compose.yml
   ├─ mongo1 (primary candidate)  ─┐
   ├─ mongo2 (secondary)          ─┤ replicaSet: rs0
   └─ mongo3 (secondary)          ─┘
   └─ mongo-init (одноразовый контейнер: rs.initiate())
```

Ключевые требования:
1.  **Общая сеть** (`mongo-net`) — контейнеры резолвят друг друга по имени сервиса.
2.  **`replSetName`** одинаков во всех контейнерах.
3.  **Инициализация** — `rs.initiate()` выполняется один раз после старта всех узлов (через init-контейнер с `depends_on: condition: service_healthy`).
4.  **Volumes** — данные переживают перезапуск контейнеров.
5.  **Healthcheck с auth** — после создания root-пользователя healthcheck должен использовать учётные данные.
6.  **Hostname** — явное указание `hostname` для каждого узла, чтобы члены RS могли находить друг друга.

## Практические сценарии

### 1. Одноузловой Replica Set (dev/test)

```yaml
# docker-compose.yml
services:
  mongo:
    image: mongodb/mongodb-community-server:8.0
    container_name: mongo-rs
    ports:
      - "27017:27017"
    environment:
      MONGO_INITDB_ROOT_USERNAME: root
      MONGO_INITDB_ROOT_PASSWORD: example
    command: ["--replSet", "rs0", "--bind_ip_all"]
    volumes:
      - mongo-data:/data/db
    healthcheck:
      test: mongosh -u root -p example --authenticationDatabase admin --eval "db.adminCommand('ping')" --quiet
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  mongo-init:
    image: mongodb/mongodb-community-server:8.0
    depends_on:
      mongo:
        condition: service_healthy
    entrypoint: >
      bash -c "
      until mongosh --host mongo:27017 -u root -p example --authenticationDatabase admin --eval 'db.adminCommand(\"ping\")' --quiet; do sleep 2; done;
      mongosh --host mongo:27017 -u root -p example --authenticationDatabase admin --eval '
        try {
          rs.initiate({
            _id: \"rs0\",
            members: [ { _id: 0, host: \"mongo:27017\" } ]
          })
        } catch (e) {
          if (e.codeName !== \"AlreadyInitialized\") throw e;
        }
      '
      "

volumes:
  mongo-data:
```

**Запуск и валидация:**
```bash
docker compose up -d
# # → ✔ Container mongo-rs  Started
# # → ✔ Container mongo-init  Started

docker compose exec mongo mongosh -u root -p example --authenticationDatabase admin --eval "rs.status().members.map(m => m.name + ':' + m.stateStr)"
# # → [ 'mongo:27017:PRIMARY' ]
```

### 2. Трёхузловой Replica Set (стенд, приближенный к production)

```yaml
# docker-compose.yml
services:
  mongo1:
    image: mongodb/mongodb-community-server:8.0
    hostname: mongo1
    command: ["--replSet", "rs0", "--bind_ip_all"]
    environment:
      MONGO_INITDB_ROOT_USERNAME: root
      MONGO_INITDB_ROOT_PASSWORD: example
    volumes:
      - mongo1-data:/data/db
    healthcheck:
      test: mongosh -u root -p example --authenticationDatabase admin --eval "db.adminCommand('ping')" --quiet
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  mongo2:
    image: mongodb/mongodb-community-server:8.0
    hostname: mongo2
    command: ["--replSet", "rs0", "--bind_ip_all"]
    environment:
      MONGO_INITDB_ROOT_USERNAME: root
      MONGO_INITDB_ROOT_PASSWORD: example
    volumes:
      - mongo2-data:/data/db
    healthcheck:
      test: mongosh -u root -p example --authenticationDatabase admin --eval "db.adminCommand('ping')" --quiet
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  mongo3:
    image: mongodb/mongodb-community-server:8.0
    hostname: mongo3
    command: ["--replSet", "rs0", "--bind_ip_all"]
    environment:
      MONGO_INITDB_ROOT_USERNAME: root
      MONGO_INITDB_ROOT_PASSWORD: example
    volumes:
      - mongo3-data:/data/db
    healthcheck:
      test: mongosh -u root -p example --authenticationDatabase admin --eval "db.adminCommand('ping')" --quiet
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  mongo-init:
    image: mongodb/mongodb-community-server:8.0
    depends_on:
      mongo1:
        condition: service_healthy
      mongo2:
        condition: service_healthy
      mongo3:
        condition: service_healthy
    entrypoint: >
      bash -c "
      mongosh --host mongo1:27017 -u root -p example --authenticationDatabase admin --eval '
        try {
          rs.initiate({
            _id: \"rs0\",
            members: [
              { _id: 0, host: \"mongo1:27017\" },
              { _id: 1, host: \"mongo2:27017\" },
              { _id: 2, host: \"mongo3:27017\" }
            ]
          })
        } catch (e) {
          if (e.codeName !== \"AlreadyInitialized\") throw e;
        }
      '
      "

volumes:
  mongo1-data:
  mongo2-data:
  mongo3-data:
```

**Проверка:**
```bash
docker compose exec mongo1 mongosh --eval "rs.status()"
# # → members: mongo1:27017 (PRIMARY), mongo2:27017 (SECONDARY), mongo3:27017 (SECONDARY)

# Подключение приложения
mongosh "mongodb://root:example@mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0&authSource=admin"
```

### 3. Подключение из приложения (Python)

```python
from pymongo import MongoClient

client = MongoClient(
    "mongodb://root:example@mongo1:27017,mongo2:27017,mongo3:27017/"
    "?replicaSet=rs0&authSource=admin&retryWrites=true&w=majority"
)
print(client.admin.command("ping"))
# # → {'ok': 1.0}
```

### 4. Полезные операции

```bash
# Логи контейнера
docker compose logs -f mongo1

# Выполнение команды в контейнере
docker compose exec mongo1 mongosh -u root -p example --authenticationDatabase admin \
  --eval "db.getSiblingDB('sales_db').orders.countDocuments({})"

# Остановка с сохранением данных (volumes сохраняются)
docker compose down

# Полная очистка включая данные
docker compose down -v

# Создание пользователя для приложения
docker compose exec mongo1 mongosh -u root -p example --authenticationDatabase admin \
  --eval 'db.getSiblingDB("sales_db").createUser({user:"app", pwd:"apppass", roles:[{role:"readWrite", db:"sales_db"}]})'
```

### 5. Валидация развёртывания

```bash
# 1. Проверить статус контейнеров
docker compose ps
# # → NAME      STATUS
# # → mongo1    Up (healthy)
# # → mongo2    Up (healthy)
# # → mongo3    Up (healthy)
# # → mongo-init  Exited (0)

# 2. Проверить статус Replica Set
docker compose exec mongo1 mongosh -u root -p example --authenticationDatabase admin --eval "rs.status()"
# # → members: mongo1:27017 (PRIMARY), mongo2:27017 (SECONDARY), mongo3:27017 (SECONDARY)

# 3. Проверить oplog window
docker compose exec mongo1 mongosh -u root -p example --authenticationDatabase admin --eval "rs.printReplicationInfo()"
# # → oplog window: ~24h (зависит от нагрузки)

# 4. Тест записи и чтения
docker compose exec mongo1 mongosh -u root -p example --authenticationDatabase admin --eval 'db.getSiblingDB("test").test.insertOne({x:1})'
docker compose exec mongo2 mongosh -u root -p example --authenticationDatabase admin --eval 'db.getSiblingDB("test").test.findOne()'
# # → { _id: ObjectId("..."), x: 1 }

# 5. Проверить healthcheck
docker inspect --format='{{.State.Health.Status}}' mongo1
# # → healthy
```

### 6. Очистка и сброс окружения

```bash
# Мягкая остановка (данные сохраняются в volumes)
docker compose down

# Полная очистка (удаляются volumes и networks)
docker compose down -v --remove-orphans

# Принудительное удаление с очисткой кэша сборки
docker compose down -v --rmi all --remove-orphans

# Удаление конкретных volumes
docker volume rm mongo1-data mongo2-data mongo3-data

# Проверка, что volumes удалены
docker volume ls
```

---

## Операции и команды (Reference)

| Операция | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| **Запуск стека** | `docker compose up -d` | Все контейнеры `Up (healthy)` |
| **Статус контейнеров** | `docker compose ps` | Список сервисов с состоянием |
| **Статус Replica Set** | `docker compose exec mongo1 mongosh -u root -p <pwd> --authenticationDatabase admin --eval "rs.status()"` | PRIMARY + SECONDARY members |
| **Healthcheck статус** | `docker inspect --format='{{.State.Health.Status}}' mongo1` | `healthy` |
| **Логи контейнера** | `docker compose logs -f mongo1` | Поток логов mongod |
| **Подключение mongosh** | `docker compose exec mongo1 mongosh -u root -p <pwd> --authenticationDatabase admin` | Интерактивная оболочка |
| **Создание пользователя** | `mongosh ... --eval 'db.createUser({user:"app", pwd:"...", roles:[{role:"readWrite", db:"mydb"}]})'` | Пользователь создан |
| **Остановка с сохранением данных** | `docker compose down` | Контейнеры остановлены, volumes остались |
| **Полная очистка** | `docker compose down -v` | Контейнеры, volumes, networks удалены |
| **Пересоздание с нуля** | `docker compose down -v && docker compose up -d` | Чистое развёртывание |
| **Обновление образа** | `docker compose pull && docker compose up -d` | Новые образы загружены и применены |
| **Просмотр ресурсов** | `docker stats mongo1 mongo2 mongo3` | CPU, RAM, Network, Block I/O |

---

## Устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`rs.initiate()` зависает / `no primary found`** | Инициализация запущена до старта всех узлов или hostname не резолвится. | `docker compose ps`, `docker compose exec mongo1 getent hosts mongo2`. | Использовать `depends_on: condition: service_healthy`; указывать `hostname` и имена сервисов в `members[].host`. |
| **`AlreadyInitialized` при перезапуске** | RS уже инициализирован в volume. | `rs.status()`. | Ловить ошибку в init-скрипте (`catch` + `codeName !== "AlreadyInitialized"`). |
| **`MongoNetworkError: failed to connect`** | Приложение использует `localhost` вместо имени контейнера, или нет `replicaSet` в URI. | `docker compose exec <app> getent hosts mongo1`. | URI должен содержать имена сервисов и `?replicaSet=rs0`. |
| **Данные теряются после `docker compose down`** | Нет volume — данные в ephemeral layer контейнера. | `docker volume ls`. | Объявить named volumes (`mongo-data:/data/db`). |
| **`Authentication failed`** | `MONGO_INITDB_ROOT_*` срабатывает только при первом создании volume; при смене пароля volume нужно удалять. | `docker compose logs mongo1 \| grep "INITDB"`. | `docker compose down -v` и пересоздать; или менять пароль через `db.updateUser`. |
| **Контейнер падает с `IllegalInstruction`** | Образ MongoDB 8.0 требует CPU с поддержкой AVX (современные x86). | `docker inspect`, логи. | Использовать хост с AVX или более старый образ (4.4) для legacy CPU. |
| **Healthcheck всегда unhealthy** | `mongosh` недоступен без авторизации после создания root-пользователя. | `docker compose exec mongo mongosh -u root -p example --authenticationDatabase admin --eval "db.adminCommand('ping')"`. | В healthcheck указать учётные данные: `mongosh -u root -p example --authenticationDatabase admin --eval "db.adminCommand('ping')"`. Добавьте `start_period: 30s`. |
| **Init-контейнер не может подключиться** | Healthcheck проходит, но mongod ещё не готов к авторизации. | Логи init-контейнера: `mongosh: error connecting`. | Добавьте `start_period` в healthcheck; в init-скрипте используйте цикл `until` с повторными попытками подключения с auth. |
| **Oplog Window слишком мал** | Высокая нагрузка на запись при малом размере oplog. | `rs.printReplicationInfo()` — window < 1h. | Увеличить `replication.oplogSizeMB` в `additionalMongodConfig` или `--oplogSize` в command. |
| **Secondary не синхронизируется** | Сетевые проблемы или несовпадение версий. | `rs.status()` — stateStr не SECONDARY, optime lag растёт. | Проверить `docker compose exec mongo1 getent hosts mongo2`; логи mongod на secondary. |

---

## Ограничения и Edge Cases

*   **Docker ≠ production:** Docker Compose не обеспечивает автомасштабирование, live resharding, автоматический failover-хостинг и мониторинг. Для production используйте Kubernetes ([Operator](./mongodb_operator.md)) или Ansible-развёртывание на VM ([пример](../../Ansible/examples/mongodb_setup.md)).
*   **Один узел = один процесс:** В одном контейнере — один `mongod`. Не запускайте несколько `mongod` в одном контейнере.
*   **`localhost` в RS:** Члены RS должны обращаться друг к другу по имени, видимому извне контейнера (`hostname` + имя сервиса). `localhost` внутри контейнера — это сам контейнер.
*   **Порты:** Пробрасывать наружу только `mongo1` (или все — для dev). В production MongoDB не должна быть доступна извне без TLS и firewall.
*   **ARM (Apple Silicon):** Образы `mongodb/mongodb-community-server` поддерживают `linux/arm64` с 6.0+.
*   **Нет автоматического failover для init-контейнера:** Если `mongo-init` упал после частичной инициализации, при следующем запуске он корректно обработает `AlreadyInitialized`, но не переконфигурирует RS при изменении топологии.
*   **WiredTiger cache без лимитов:** Без `memory` limit в compose MongoDB займёт 50% RAM хоста. Всегда задавайте `deploy: resources: limits: memory` или используйте `--wiredTigerCacheSizeGB`.
*   **Файловые дескрипторы:** В контейнере дефолтный ulimit может быть низким (1024). Для нагрузки задайте `ulimits: nofile: 64000:64000` в compose.
*   **Timezone и locale:** Контейнер наследует TZ хоста. Для воспроизводимости задайте `environment: TZ: UTC`.
*   **Смена версии MongoDB:** Обновление `image` tag требует совместимость данных (major version upgrade — только через `docker compose down -v` и миграцию). Minor/patch — rolling restart.
*   **Backup в Docker:** `mongodump` из контейнера работает, но для консистентных бэкапов нужен `fsyncLock` или secondary. См. **[Бэкап и DR](./mongodb-backup-dr.md)**.

---

## Лучшие практики (Best Practices)

### Архитектура и проектирование
1. **Всегда используйте Replica Set** — даже для dev. Standalone не поддерживает Change Streams, транзакции, CDC.
2. **Явные hostname** — указывайте `hostname` в compose для каждого узла RS. Это гарантирует корректное разрешение имён внутри кластера.
3. **Named volumes на каждом узле** — отдельные volumes (`mongo1-data`, `mongo2-data`, `mongo3-data`) изолируют данные и упрощают восстановление.
4. **Healthcheck с авторизацией** — после создания root-пользователя healthcheck должен использовать `-u root -p <pwd> --authenticationDatabase admin`. Добавьте `start_period: 30s` для учета времени инициализации.
5. **Init-контейнер с retry** — используйте цикл `until` с auth в entrypoint, чтобы дождаться готовности PRIMARY.

### Безопасность
6. **Секреты не в compose-файле** — используйте `.env` файл или Docker secrets для паролей. Не коммитьте пароли в git.
7. **Не пробрасывайте 27017 наружу без TLS** — для dev используйте SSH-туннель или VPN. В production — только внутренняя сеть + TLS.
8. **Создавайте приложений пользователей** — не используйте root в приложениях. Создавайте пользователей с минимальными правами (`readWrite` на конкретную БД).
9. **Keyfile для внутренней аутентификации** — для production RS используйте shared keyfile вместо SCRAM между узлами (см. [Operator](./mongodb_operator.md) для K8s, для Docker — смонтируйте keyfile в `/data/keyfile` и добавьте `--keyFile`).

### Ресурсы и производительность
10. **Лимиты памяти** — всегда задавайте `deploy: resources: limits: memory: 4g` (или через `mem_limit` в старом формате) и соответствующий `storage.wiredTiger.engineConfig.cacheSizeGB: 2` (50% от лимита).
11. **File descriptors** — добавьте `ulimits: nofile: 64000:64000` в каждый сервис mongod.
12. **Oplog size** — для активной записи увеличьте `replication.oplogSizeMB: 2048` (или больше) через `command` или `additionalMongodConfig` (в K8s Operator).
13. **Compression** — включите `net.compression.compressors: zstd` для экономии трафика между узлами.

### Операционная стабильность
14. **Валидация после деплоя** — всегда выполняйте проверку: `rs.status()`, `rs.printReplicationInfo()`, тест записи/чтения с secondary.
15. **Мониторинг** — подключите `mongodb_exporter` (см. [Мониторинг](./mongodb-monitoring.md)) даже для dev-стендов.
16. **Backup strategy** — регулярные `mongodump` из secondary (чтобы не нагружать primary) + тестирование восстановления.
17. **Версионирование образов** — закрепляйте конкретные теги (`8.0.5`), не используйте `latest`. Обновляйте планово с тестированием.
18. **Network isolation** — используйте custom bridge network (`driver: bridge`), не default bridge, для изоляции от других стеков.

### CI/CD и разработка
19. **Ephemeral тестовые среды** — в CI поднимайте чистый RS на каждый запуск тестов (`docker compose up -d && run-tests && docker compose down -v`).
20. **Schema validation** — включайте `validationLevel: strict` и JSON Schema в коллекциях на уровне приложения, не в Docker.
21. **Документируйте порты и URI** — в README проекта указывайте connection string с `replicaSet=rs0&authSource=admin`.

---

## Дополнительная информация

*   **[Обзор MongoDB](./mongodb.md)** — архитектура и WiredTiger.
*   **[Репликация](./mongodb-replication.md)** — Replica Set, кворум, failover.
*   **[Change Streams](./mongodb-change-streams.md)** — требуют RS, работают в Docker RS.
*   **[Kafka/CDC](./mongodb-kafka-cdc.md)** — коннекторы к Docker RS.
*   **[Мониторинг](./mongodb-monitoring.md)** — mongodb_exporter, Prometheus, алерты.
*   **[Бэкап и DR](./mongodb-backup-dr.md)** — mongodump, PBM, Velero.
*   **[Operator для Kubernetes](./mongodb_operator.md)** — production-развёртывание в K8s.
*   **[Ansible: setup MongoDB](../../Ansible/examples/mongodb_setup.md)** — развёртывание на VM.
*   **[Capacity Planning](./mongodb-capacity-planning.md)** — расчёт ресурсов для Docker/VM/K8s.
*   **[Высокая доступность](./high_availability.md)** — failover, Oplog Window, топологии.
