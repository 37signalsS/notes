# Диагностика распределённой системы Kafka + PostgreSQL

Эта заметка описывает практический сценарий (кейс) по диагностике распределённой системы, а также общий алгоритм и типичные проблемы при взаимодействии Kafka с базой данных. Теоретические основы и инструменты диагностики описаны в: **[Диагностика файловых систем и Inodes](../../Linux/Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md)**, **[Ссылки, Inode и Dentry](../../Linux/FileSystems/links_inodes_dentries.md)**, **[Общая методология диагностики](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md)**, **[Kafka Connect в Production](../../Kafka/kafka_connect_production.md)**, **[Архитектурные паттерны CDC](../../Databases/Concepts/cdc_architectural_patterns.md)**.

## Определения

- **Inodes (Индексные дескрипторы)** — фундаментальные структуры данных в файловой системе **ОС (Operating System — операционная система)**, хранящие метаданные о файлах и директориях (права, владелец, ссылки на блоки данных), кроме имени файла. Количество дескрипторов фиксируется при создании в `ext4` или выделяется динамически в `XFS`. Подробнее см. **[Индексный дескриптор (Inode)](../../Linux/FileSystems/links_inodes_dentries.md#индексный-дескриптор-inode)**.
- **Producer Kafka (Продюсер)** — клиентское приложение, отправляющее сообщения в топик Kafka. См. **[Обзор Kafka](../../Kafka/kafka_overview.md)**.
- **Consumer Kafka (Консьюмер)** — клиентское приложение, читающее и обрабатывающее сообщения из топиков.
- **Offset в Kafka (Смещение)** — уникальный последовательный идентификатор сообщения в пределах партиции, используемый для отслеживания позиции чтения консьюмером.
- **Healthcheck (Проверка здоровья)** — механизм внешней проверки работоспособности контейнера/сервиса.
- **Consumer Lag** — разница между последним записанным offset в партиции и текущим committed offset консьюмера. Хранится в внутреннем топике `__consumer_offsets`.
- **Auto-commit** — автоматическое подтверждение обработанных offsets консьюмером по интервалу (по умолчанию 5 сек). Ненадежно при сбоях: консьюмер может закоммитить offset до фактической записи данных в БД.
- **Transactional ID** — стабильный идентификатор продюсера для exactly-once семантики. Обеспечивает «zombie fencing»: при перезапуске продюсера с тем же transactional.id старый экземпляр блокируется.
- **DLQ (Dead Letter Queue)** — топик для сообщений, которые не удалось обработать за N попыток. Позволяет изолировать «плохие» сообщения и обрабатывать их отдельно.

## Предварительные требования

### Необходимые инструменты

| Инструмент | Назначение | Установка |
| :--- | :--- | :--- |
| `kafka-consumer-groups` | Управление_offsets, проверка Consumer Lag | Входит в дистрибутив Kafka |
| `kafka-topics` | Управление топиками, проверка партиций | Входит в дистрибутив Kafka |
| `kafka-console-producer/consumer` | Тестовая отправка/чтение сообщений | Входит в дистрибутив Kafka |
| `df`, `du` | Диагностика дискового пространства и Inodes | Встроены в Linux |
| `docker` / `kubectl` | Управление контейнерами / подами | Docker / kubectl CLI |
| `curl` / `httpie` | Проверка HTTP-эндпоинтов | `apt install curl` / `pip install httpie` |
| `nc` (netcat) | Проверка TCP-связности | `apt install netcat-openbsd` |
| `ss` | Просмотр активных соединений | Встроен в ядро |
| `ps`, `top`, `htop` | Мониторинг процессов | Встроены в Linux |
| `journalctl` / `systemctl` | Логи systemd-сервисов | Встроен в systemd |
| Grafana + Prometheus | Мониторинг метрик Kafka и БД | отдельная установка |

### Требования к среде

- Доступ к брокеру Kafka (bootstrap-server) с правами на чтение метрик и управление offsets.
- Доступ к серверу PostgreSQL (SSH или kubectl exec) для диагностики.
- Мониторинг (Grafana/Prometheus) с метриками: Consumer Lag, CPU, Disk I/O, Inodes.
- Логи приложений доступны в централизованной системе (ELK, Loki) или через `docker logs`/`kubectl logs`.

### Права доступа

| Операция | Минимальные права |
| :--- | :--- |
| Чтение Consumer Lag | Kafka ACL: `Read` на `__consumer_offsets`, `Describe` на целевой топик |
| Сброс offsets | Kafka ACL: `Read` + `Write` на `__consumer_offsets` |
| Просмотр логов контейнера | Docker: доступ к Docker daemon, или K8s RBAC: `get`, `list` на `pods/log` |
| Проверка Inodes | SSH root, или `CAP_SYS_ADMIN` в контейнере |
| Запуск/остановка контейнера | Docker: доступ к Docker daemon, или K8s RBAC: `create` на `pods/exec` |

## Основные концепции

### Типичная архитектура Kafka + PostgreSQL

```
[Producer] --> [Kafka Broker] --> [Consumer/Store Service] --> [PostgreSQL]
                                    |
                              (Auto-commit offsets)
```

В этой архитектуре есть несколько точек отказа:

1. **Producer** — не может отправить сообщение (ошибка сети, auth,quota).
2. **Kafka Broker** — переполнение диска, ISR shrinking, unavailable partitions.
3. **Consumer** — не может обработать сообщение (ошибка БД, таймаут, падение).
4. **PostgreSQL** — недоступен, переполнен, исчерпаны Inodes, заблокирован.
5. **Сеть** — cross-zone latency, DNS, firewall.

### Consumer Lag: ключевая метрика

Consumer Lag показывает, сколько сообщений еще не обработано. В норме Lag должен быть стабилен или уменьшаться. Рост Lag означает, что Consumer не справляется (медленная БД, network issues, crash loop).

```bash
# Проверка Consumer Lag
kafka-consumer-groups --bootstrap-server kafka:9092 \
  --describe --group store-group
# → GROUP           TOPIC      PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG    CONSUMER-ID
# → store-group     orders     0          45021           45021           0      consumer-1
```

### Auto-commit vs Manual Commit: проблема потери данных

При **Auto-commit** Kafka коммитит offsets каждые 5 секунд (по умолчанию). Если Consumer упал между коммитами, он перечитает уже обработанные сообщения (at-least-once). Но если Consumer закоммитил offset, а запись в БД не прошла — сообщение потеряно навсегда.

**Решение:** Использовать **Manual Commit** (commitSync/commitAfter) после успешной записи в БД.

### Inodes: скрытый убийца

Исчерпание Inodes — частая причина сбоев PostgreSQL в Docker-средах. Типичные виновники:
- Ротация логов Docker без `max-size`/`max-file`.
- Temp-файлы PostgreSQL (`/tmp`).
- Healthcheck-файлы контейнеров.
- PID-файлы и socket-файлы.

## Алгоритм диагностики (Bottom-up)

При проблемах «данные не доходят до БД» следуйте алгоритму снизу вверх:

1. **PostgreSQL доступен?** — `pg_isready -h host -p 5432`, проверка статуса контейнера.
2. **Есть ли место на диске?** — `df -h` (данные) и `df -i` (Inodes).
3. **Consumer подключен к Kafka?** — `ss -tnp | grep :9092`, Consumer Lag.
4. **Producer отправляет сообщения?** — Логи продюсера, Grafana: `kafka_producer_records_sent_total`.
5. **Сеть между компонентами?** — `nc -zv kafka 9092`, `mtr` до БД.
6. **Есть ли ошибки в логах?** — `docker logs`/`kubectl logs`, ELK/Loki.

## Основные концепции (детали)

В распределённых системах стабильность зависит от доступности ресурсов на каждом узле цепочки. Критическим, но часто игнорируемым ресурсом являются **Inodes**. Их исчерпание блокирует создание новых объектов файловой системы (логов, временных файлов, сокетов, PID-файлов), даже если на диске доступны десятки гигабайт свободного места.

Типичный признак проблемы — ошибка `No space left on device` при наличии свободного места в выводе `df -h`. Это приводит к каскадным сбоям: СУБД не могут создать файл блокировки (`.pid`), логирование обрывается, а транзакции завершаются с ошибками ввода-вывода.

## Практические сценарии

### Сценарий 1: Заказ не доходит до склада из-за исчерпания Inodes

**Проблема:** Пользователи успешно создают заказы (получают **HTTP (HyperText Transfer Protocol)** 200), но данные не отображаются в системе управления складом.

**Архитектура:** Frontend → Nginx → App (Python) → Kafka → Store Service (Consumer) → **PostgreSQL (Database)**.

#### Шаг 1: Проверка на стороне клиента

Анализ сетевых запросов в браузере подтвердил, что `POST /orders` возвращает статус 200. Данные уходят с клиента.

```bash
# Проверка из контейнера приложения (или curl)
curl -s -o /dev/null -w "%{http_code}" -X POST http://app:8000/orders
# → 200
```

**Валидация:** HTTP 200 подтверждает, что запрос дошёл до приложения и был принят.

#### Шаг 2: Анализ Nginx

Подключение по **SSH (Secure Shell)** к балансировщику. Логи Nginx (`/var/log/nginx/access.log`) показывают успешные ответы. Запросы передаются на `upstream` без ошибок.

```bash
# Проверка последних записей access.log
tail -20 /var/log/nginx/access.log | grep orders
# → 10.0.1.5 - - [06/Jun/2026:10:01:23 +0000] "POST /orders HTTP/1.1" 200 ...
```

**Валидация:** Код ответа `200` и отсутствие `5xx` ошибок в upstream подтверждают, что Nginx проксирует запросы корректно.

#### Шаг 3: Проверка сервера приложения

Приложение-продюсер работает стабильно. Проверка Docker-контейнеров: `Up`. Логи подтверждают отправку сообщений в Kafka с подтверждением `Acks=all`.

```bash
docker ps --filter name=app
# → CONTAINER ID   IMAGE     STATUS          PORTS                  NAMES
# → abc123         app:v1    Up 2 hours      0.0.0.0:8000->8000     app_producer

# Проверка логов продюсера на подтверждение отправки
docker logs app_producer --tail 10 | grep -i "kafka\|sent\|ack"
# → [INFO] Message sent to topic 'orders' partition 3 offset 45021, acks=all
```

**Валидация:** Подтверждение `acks=all` означает, что сообщение реплицировано во все ISR-ноды Kafka.

#### Шаг 4: Анализ Kafka

С помощью Grafana и CLI установлено:

```bash
# Consumer Lag в топике orders
kafka-consumer-groups --bootstrap-server kafka:9092 \
  --describe --group store-group

# → GROUP           TOPIC      PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID
# → store-group     orders     0          45021           45021           0    consumer-1
# → store-group     orders     1          32100           32100           0    consumer-2
```

- **Consumer Lag** = 0 — сообщения вычитываются.
- Группа `store-group` активна.

Это означает, что проблема лежит **за пределами** брокера сообщений — консьюмер читает, но не может записать в БД.

#### Шаг 5: Проверка консьюмера (Store Service)

Анализ логов сервиса в Elasticsearch/Kibana выявил критическую ошибку:

```bash
# Проверка логов консьюмера
docker logs store_service --tail 20
# → ERROR: FATAL: could not connect to server: Connection refused
# → ERROR: Is the server running on host "postgres_db" (172.17.0.3) and accepting
# →        TCP/IP connections on port 5432?
```

**Валидация:** Ошибка `Connection refused` на TCP-уровне означает, что PostgreSQL не слушает на порту 5432 — либо процесс не запущен, либо контейнер остановлен.

#### Шаг 6: Диагностика сервера базы данных

PostgreSQL запущен в Docker. Проверка статуса:

```bash
docker ps -a --filter name=postgres
# → CONTAINER ID   IMAGE       STATUS                    NAMES
# → def456         postgres:15 Exited (1) 5 minutes ago   postgres_db
```

Логи контейнера:

```bash
docker logs postgres_db --tail 20
# → FATAL: could not create lock file "postmaster.pid": No space left on device
```

**Ключевой момент:** Ошибка `No space left on device` при наличии свободного места — типичный признак исчерпания Inodes.

#### Шаг 7: Проверка Inodes (критический шаг)

```bash
df -h
# → /dev/sda1 50G 20G 30G 40% /  # Место ЕСТЬ

df -i
# → /dev/sda1 3.2M 3.2M 0 100% / # Inodes ИСЧЕРПАНЫ (100%)
```

**Валидация:** `df -i` показывает 100% использование Inodes. Это подтверждает диагноз.

#### Шаг 8: Поиск причины исчерпания Inodes

```bash
# Поиск директорий с максимальным количеством Inodes
du --inodes -S /var/lib/docker/containers | sort -rh | head -n 5
# → 2800000 /var/lib/docker/containers/<id>/checkpoints
# →   12000 /var/lib/docker/containers/<postgres-id>/diff/var/lib/postgresql/data/pg_wal
# →    8000 /var/lib/docker/containers/<app-id>/diff/var/log
```

**Корень проблемы:** Тестовый контейнер со слишком агрессивным **Healthcheck** (интервал 1с) генерировал миллионы мелких артефактов в директории `checkpoints` из-за специфического драйвера хранения. Это забило таблицу дескрипторов всей ФС. PostgreSQL не смог создать `.pid` файл при запуске и аварийно завершился.

#### Шаг 9: Решение

```bash
# 1. Удаление проблемного контейнера
docker rm -f <problematic-container-id>

# 2. Очистка директории с артефактами
rm -rf /var/lib/docker/containers/<id>/checkpoints/*

# 3. Проверка восстановления Inodes
df -i
# → /dev/sda1 3.2M 120K 3.08M 4% /  # Inodes ВОССТАНОВЛЕНЫ

# 4. Запуск PostgreSQL
docker start postgres_db

# 5. Проверка статуса
docker ps --filter name=postgres
# → STATUS: Up (healthy)
```

**Валидация:** PostgreSQL запускается без ошибок, `df -i` показывает <10% использование Inodes.

#### Шаг 10: Восстановление данных (Kafka Offset Management)

Так как консьюмер работал с **Auto-commit**, он успел закоммитить смещения (Offsets) в Kafka, но фактически не записал данные в БД из-за ошибки подключения. Требуется сброс смещений для повторной обработки.

```bash
# 1. Остановка консьюмера (обязательно!)
docker stop store_service

# 2. Проверка текущих offsets и timestamp сообщений
kafka-consumer-groups --bootstrap-server kafka:9092 \
  --describe --group store-group --offsets

# 3. Определение нужного момента времени через deserialization
kafka-console-consumer --bootstrap-server kafka:9092 \
  --topic orders --from-beginning --max-messages 5 \
  --property print.timestamp=true \
  --property print.key=true
# → CreateTime:1749194400000   order-1234
# → CreateTime:1749194401000   order-1235

# 4. Сброс offsets на конкретный момент времени
kafka-consumer-groups --bootstrap-server kafka:9092 \
  --group store-group \
  --topic orders \
  --reset-offsets \
  --to-datetime 2026-06-06T10:00:00.000 \
  --execute
# → GROUP           TOPIC      PARTITION  NEW-OFFSET
# → store-group     orders     0          45021
# → store-group     orders     1          32100

# 5. Запуск консьюмера
docker start store_service

# 6. Проверка повторной обработки
docker logs store_service --tail 10 | grep -i "processed\|insert"
# → [INFO] Processed order-1234 → INSERT INTO orders VALUES (...)
```

*Примечание: флаг `--execute` применяет изменения. Без него команда выполняется в режиме `--dry-run`.*

### Сценарий 2: Рост Consumer Lag из-за медленной БД (медленные запросы)

**Проблема:** Consumer Lag в топике `orders` стабильно растёт (от 0 до 100k за 1 час), хотя брокер и продюсер работают нормально. БД не падает, но обработка замедляется.

**Архитектура:** Kafka → Consumer (Java) → PostgreSQL ( запросы INSERT через JDBC).

**Диагностика:**

```bash
# 1. Проверка Lag в динамике (повторить через 60 сек)
kafka-consumer-groups --bootstrap-server kafka:9092 \
  --describe --group store-group | awk '{print $2, $5, $6}'
# → orders 45021 55021   (LAG растёт!)

# 2. Проверка времени обработки одного сообщения в логах consumer
docker logs store_service --tail 100 | grep "processing time"
# → [INFO] Processed order-1234 in 2340ms  ← 2.3 сек на одно сообщение!

# 3. Проверка负载 на PostgreSQL
docker exec postgres_db psql -U postgres -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"
# → 47  ← много активных запросов!

# 4. Проверка lock contention
docker exec postgres_db psql -U postgres -c "SELECT relation::regclass, mode, granted FROM pg_locks WHERE NOT granted;"
# → orders_pkey | ExclusiveLock | false  ← заблокированные запросы!
```

**Причина:** Consumer выполняет INSERT без батчинга, каждое сообщение — отдельная транзакция. При высоком QPS возникает lock contention на индексе `orders_pkey`.

**Решение:**
1. Батчинг: накапливать 100-500 сообщений и выполнять bulk INSERT.
2. Параллелизм: увеличить `max.poll.records` и количество воркеров Consumer.
3. Оптимизация индексов: `REINDEX CONCURRENTLY` на горячих таблицах.

---

### Сценарий 3: Потеря сообщений из-за auto-commit и сбоя Consumer

**Проблема:** После перезапуска Consumer часть заказов «исчезла» — заказы создавались (HTTP 200), Kafka получала сообщения, но Consumer не обрабатывал часть из них.

**Диагностика:**

```bash
# 1. Проверка committed offsets
kafka-consumer-groups --bootstrap-server kafka:9092 \
  --describe --group store-group --offsets
# → PARTITION  CURRENT-OFFSET  LOG-END-OFFSET
# → 0          45100           45100   ← Lag=0, но заказ 45050 не в БД

# 2. Проверка в БД
docker exec postgres_db psql -U postgres -c \
  "SELECT order_id FROM orders WHERE order_id BETWEEN 45040 AND 45060;"
# → 45040, 45041, ..., 45049, 45051, ...  ← 45050 ОТСУТСТВУЕТ

# 3. Проверка логов Consumer на ошибки в момент 45050
docker logs store_service | grep -A2 -B2 "45050"
# → [WARN] Failed to insert order-45050: deadlock detected
# → [INFO] Skipping offset 45050 (auto-committed)
```

**Причина:** Auto-commit закоммитил offset 45050 до завершения записи в БД. При deadlock Consumer получил исключение, но Kafka уже зафиксировала позицию.

**Решение:**
1. Переключение на **Manual Commit** (`enable.auto.commit=false`, `consumer.commitSync()`).
2. Обработка ошибок: retry + DLQ для безнадёжных сообщений.

---

## Диагностика типичных проблем

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `No space left on device` при наличии места | Исчерпание Inodes | `df -i` → 100% | Найти виновника: `du --inodes -S / \| sort -rh`; настроить лимиты логов |
| Consumer Lag растёт стабильно | Медленная БД или lock contention | Проверить время обработки в логах; `pg_stat_activity` | Батчинг, оптимизация запросов, увеличение параллелизма |
| Consumer Lag = 0, но данные отсутствуют в БД | Auto-commit до записи в БД | Сравнить offsets с данными в БД | Manual Commit + retry + DLQ |
| `Connection refused` к PostgreSQL | PostgreSQL остановлен или не слушает | `docker ps`, `pg_isready`, `ss -tlnp \| grep 5432` | Запустить контейнер; проверить `listen_addresses` |
| `FATAL: could not create lock file` | Исчерпание Inodes или прав | `df -i`, `ls -la /var/lib/postgresql/data/` | Очистить Inodes; проверить права доступа |
| Kafka `NOT_ENOUGH_REPLICAS` | ISR уменьшился ниже min.insync.replicas | `kafka-topics --describe`, Grafana ISR metrics | Восстановить ноды; увеличить replication.factor |
| Consumer `CommitFailedException` | Consumer перезапущен с тем же group.id | Логи Consumer: rebalance events | Увеличить `session.timeout.ms`; добавить graceful shutdown |
| `DeadlockDetected` в PostgreSQL | Конкуренция за индексы при параллельных INSERT | `pg_stat_activity`, `pg_locks` | Батчинг; оптимизация индексов; `REINDEX CONCURRENTLY` |
| Consumer падает с `OffsetOutOfRangeException` | Offset сброшен, но сообщение удалено (retention) | Проверить `retention.ms` в топике | Пересоздать Consumer Group; уменьшить retention |
| Высокий P99 латентности��신의 처리 | Сетевые задержки (cross-zone) или GC паузы | `mtr` до БД; GC логи JVM Consumer | Topology Aware Routing; оптимизация GC |

---

## Граничные случаи и особенности

### Consumer Group Rebalancing при масштабировании

При добавлении/удалении инстансов Consumer происходит rebalancing —短暂ное (секунды) приостановка обработки. During rebalance, offsets не коммитятся, и возможна повторная обработка сообщений (at-least-once).

```bash
# Мониторинг rebalance events
docker logs store_service | grep -i "rebalance\|revoked\|assigned"
# → [INFO] Revoked partitions: [orders-0, orders-1]
# → [INFO] Assigned partitions: [orders-0, orders-1, orders-2]
```

**Рекомендация:** Использовать `CooperativeStickyAssignor` для minimal rebalancing (только перераспределение затронутых партиций).

### Топик с retention.ms = -1 (бесконечное хранение)

Если retention не настроен, сообщения хранятся бесконечно, и reset-offsets может вернуть Consumer на очень старые сообщения, что приведёт к повторной обработке тысяч уже записанных заказов.

```bash
# Проверка retention
kafka-topics --bootstrap-server kafka:9092 --describe --topic orders | grep -i retention
# → retention.ms=604800000 (7 дней)
```

**Рекомендация:** Всегда устанавливать `retention.ms` и мониторить размер топиков.

### PostgreSQL replication lag при CDC

Если используется Debezium/CDC для репликации данных из PostgreSQL в Kafka, задержка репликации (replication lag) может привести к пропуску изменений.

```bash
# Проверка replication lag
docker exec postgres_db psql -U postgres -c \
  "SELECT client_addr, state, sent_lsn, write_lsn, replay_lsn,
   (sent_lsn - replay_lsn) AS replication_lag_bytes
   FROM pg_stat_replication;"
```

**Рекомендация:** Мониторить replication lag; алерт при >1MB.

### Одновременный доступ нескольких Consumer Groups

Если несколько Consumer Groups читают один топик, каждая группа имеет свои offsets. Проблема одной группы (падение, Lag) не влияет на другие. Это полезно для izolirovанных сред (dev/staging).

### Автоматическое создание топиков

Если `auto.create.topics.enable=true` в Kafka, продюсер может создать топик с некорректными параметрами (1 partition, replication.factor=1). Это критично для production.

```bash
# Проверка конфигурации брокера
kafka-configs --bootstrap-server kafka:9092 --describe --all | grep auto.create
# → auto.create.topics.enable=false  ← правильная настройка
```

---

## Практические рекомендации

### По мониторингу

1. **Consumer Lag** — основная метрика. Настройте алерт в Prometheus: `sum(kafka_consumergroup_lag) > 1000` в течение 5 минут.
2. **Inodes** — `node_filesystem_files_free / node_filesystem_files < 0.2` (менее 20% свободных Inodes).
3. **Disk I/O** — `node_disk_io_time_seconds_total` — время занятости диска >80%.
4. **PostgreSQL connections** — `pg_stat_activity` count > 80% от `max_connections`.

### По Consumer Design

1. **Всегда используйте Manual Commit** для критичных данных (заказы, платежи).
2. **Батчинг:** Оптимальный размер батча — 100-500 сообщений для INSERT.
3. **Idempotent Consumer:** Используйте `INSERT ... ON CONFLICT` для защиты от повторной обработки.
4. **DLQ:** Настройте Dead Letter Queue для сообщений, которые не удалось обработать за 3 попытки.
5. **Graceful Shutdown:** Обрабатывайте `SIGTERM`, коммитьте offsets перед завершением.

### По PostgreSQL

1. **connection_pooling:** Используйте PgBouncer для управления пулом соединений.
2. **Index Tuning:** Регулярно выполняйте `ANALYZE` и `REINDEX` на горячих таблицах.
3. **WAL Monitoring:** Мониторите `pg_wal` size для предотвращения переполнения.
4. **Lock Monitoring:** Настройте алерт на `pg_locks WHERE NOT granted`.

### По Kafka

1. **replication.factor ≥ 3** для production топиков.
2. **min.insync.replicas ≥ 2** для garantии данных.
3. **acks=all** для продюсеров, отправляющих критичные данные.
4. **retention.ms** — всегда устанавливайте, не оставляйте -1.
5. **Тестирование:** Регулярно выполняйте `kafka-consumer-groups --describe` для контроля Lag.

---

## Безопасность

- **Шифрование Kafka:** Используйте SSL/TLS для соединений между продюсером/консьюмером и брокером (`security.protocol=SSL`).
- **Аутентификация Kafka:** SASL/SCRAM или mTLS. Не используйте plaintext в production.
- **PostgreSQL:** Настройте `pg_hba.conf` для ограничения доступа по IP. Не используйте `trust` для remote connections.
- **Docker secrets:** Храните пароли БД и Kafka credentials в Docker Secrets или K8s Secrets, а не в переменных окружения.
- **Network Policies:** В K8s ограничьте трафик между подами: разрешите Consumer → PostgreSQL только на порту 5432.

## Дополнительная информация

### Рекомендации по предотвращению

1. **Мониторинг ресурсов:** Настройка алертов в Prometheus на метрику `node_filesystem_files_free`. Порог — 80%. См. **[Диагностика нехватки Inodes](../../Linux/Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md#диагностика-нехватки-inodes)**.
2. **Лимиты Docker-логов:** Использование `json-file` с параметрами `max-size` и `max-file`. См. **[Управление ротацией логов Docker](../../Docker/Docker_logs/docker_log_rotation.md)**.
3. **Изоляция томов:** Хранение данных БД (`Volumes`) на выделенных дисках или LVM-томах. Это предотвратит остановку БД при переполнении системного раздела.
4. **Тюнинг Healthcheck:** Использование специализированных утилит (например, `pg_isready` для Postgres) с разумным интервалом (15-30 сек).
5. **Inodes capacity planning:** При массовом создании контейнеров проверяйте `df -i` регулярно. Для `ext4` зарезервируйте 20% Inodes.

### См. также

- **[Диагностика дискового пространства](../../Linux/FileSystems/disk_space_troubleshooting.md)** — причины расхождения `df` и `du`.
- **[Анализ сокетов (ss)](../../Linux/Diagnostics/Networking/ss.md)** — проверка «слушающих» портов.
- **[Логирование в Docker](../../Docker/Docker_logs/docker_logging_drivers_overview.md)** — обзор драйверов вывода.
- **[Методология диагностики](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md)** — системный подход (USE/RED).
- **[Kafka Connect в Production](../../Kafka/kafka_connect_production.md)** — DLQ, SMT, Exactly-once для Sink Connectors.
- **[Архитектурные паттерны CDC](../../Databases/Concepts/cdc_architectural_patterns.md)** — Debezium, Log-based CDC, Schema Registry.
- **[Обзор Kafka](../../Kafka/kafka_overview.md)** — общая архитектура, партиционирование, репликация.
- **[Сетевая связность K8s и PostgreSQL](../../Databases/PostgreSQL/Operations/kubernetes_connectivity.md)** — Topology Aware Routing, cross-zone latency для БД.
