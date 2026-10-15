# ClickHouse

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения и базовая теория

**ClickHouse** — это колоночная (столбцовая) система управления базами данных (СУБД) для онлайн-обработки аналитических запросов (OLAP — Online Analytical Processing). Изначально разработана в Яндексе для сервиса Яндекс.Метрика.

**MPP (Massively Parallel Processing)** — архитектура массово-параллельной обработки, при которой запрос разделяется на множество независимых подзадач, выполняемых параллельно на разных ядрах или узлах.

**Shared-Nothing** — принцип построения распределенных систем, где каждый узел обладает собственным CPU, памятью и дисками без общих ресурсов с другими узлами, обеспечивая линейную масштабируемость.

**MergeTree** — семейство движков таблиц ClickHouse, являющееся фундаментом хранения данных; основано на LSM-дереве с фоновым слиянием мелких частей в крупные.

**Текущие версии:** ClickHouse 26.9.x (Stable, сентябрь 2026) / 26.8.x (LTS, август 2026).

### Архитектурные принципы: почему ClickHouse работает быстро

В отличие от традиционных строковых СУБД (PostgreSQL, MySQL), ClickHouse спроектирован для максимально эффективного использования ресурсов процессора и дисковой подсистемы при выполнении агрегационных запросов.

1.  **Колоночное хранение (Columnar Storage):** В строковых БД данные одной строки хранятся вместе. Если запрос обращается только к одной колонке из 100, СУБД всё равно считывает с диска всю строку, создавая избыточную нагрузку на I/O. В ClickHouse данные каждой колонки хранятся в отдельных файлах. Запрос читает только необходимые данные, что кратно ускоряет выполнение.
2.  **Векторное выполнение запросов:** ClickHouse обрабатывает данные не по одной строке, а блоками (векторами). Это позволяет эффективно использовать кэши процессора и современные наборы инструкций **SIMD** (SSE 4.2, AVX-512) для параллельной обработки множества значений за один такт процессора.
3.  **Сжатие данных:** Благодаря тому, что в одной колонке лежат данные одного типа, ClickHouse достигает колоссальной степени сжатия (до 10–100 раз) с использованием специализированных кодеков (LZ4, ZSTD, Delta, DoubleDelta). Сжатые данные быстрее считываются с диска и занимают меньше места.
4.  **Разреженные индексы:** Вместо B-Tree индексов для каждой строки, ClickHouse использует разреженные индексы на основе движка `MergeTree`, которые указывают на границы блоков данных (гранулы), позволяя быстро отсекать ненужные части данных при чтении.

### Сравнение OLAP и OLTP

| Характеристика | OLTP (PostgreSQL) | OLAP (ClickHouse) |
| :--- | :--- | :--- |
| **Назначение** | Транзакции (заказы, профили) | Аналитика (отчёты, агрегации) |
| **Структура хранения** | Строковая | Колоночная |
| **Операции** | Частые вставки/обновления/удаления | Массовые вставки, редкие изменения |
| **Данные** | Нормализованные | Денормализованные |
| **Масштабирование** | Вертикальное / репликация чтения | Горизонтальное (MPP, шардирование) |
| **Гарантии** | ACID | BASE (скорость важнее согласованности) |

---

## Роль в экосистеме Observability 2.0

ClickHouse стал де-факто стандартом для хранения телеметрии высокой кардинальности (High Cardinality) благодаря способности обрабатывать петабайты логов, метрик и трейсов с минимальными затратами.

-   **Централизованное логирование:** Альтернатива стеку ELK и Grafana Loki для сценариев с огромным объемом данных. Агент **Vector** обеспечивает сверхвысокую скорость доставки через `clickhouse` sink с поддержкой бинарного формата **Apache Arrow**.
-   **Распределенная трассировка:** В **Jaeger v2** ClickHouse доступен как нативный экспериментальный бэкенд хранения (feature gate `storage.clickhouse`, с v2.18.0, поддерживает ClickHouse 26.x). Детали — **[Наблюдаемость](./clickhouse-observability.md)**.
-   **Метрики:** **Zabbix 8.0** (на момент сверки — предрелиз) вводит ClickHouse как аналитический бэкенд для хранения исторических данных и JSON. Prometheus может записывать данные в ClickHouse через адаптеры `remote_write` для долгосрочного хранения (Long-term storage).
-   **Сетевой мониторинг:** Идеальное хранилище для терабайтов NetFlow/IPFIX-логов, позволяющее строить отчеты по трафику в реальном времени.

---

## Навигация по разделам

Для детального изучения конкретных аспектов ClickHouse выберите соответствующий раздел:

1.  **[Архитектура и внутреннее устройство](./clickhouse-architecture.md):** Ключевые особенности, семейство MergeTree, разреженный индекс, жизненный цикл запроса.
2.  **[Кластерное управление](./clickhouse-cluster.md):** Репликация, шардирование, ClickHouse Keeper, кворум (`insert_quorum`), решардинг, clickhouse-copier, Distributed-настройки.
3.  **[Производительность и оптимизация](./clickhouse-performance.md):** Тюнинг настроек, кодеки сжатия, механизмы JOIN, MV (включая refreshable MV), Tiered Storage, продвинутый TTL, EXPLAIN.
4.  **[Эксплуатация и обслуживание](./clickhouse-operations.md):** Системные требования, безопасность, бэкапы, мониторинг и диагностика.
5.  **[Операционный SQL и SYSTEM-команды](./clickhouse-sql-operations.md):** OPTIMIZE FINAL, lightweight DELETE, мутации, KILL QUERY, FREEZE/FETCH, DETACH/ATTACH, LIMIT BY, SAMPLE, ARRAY JOIN, GLOBAL IN.
6.  **[Словари (Dictionaries)](./clickhouse-dictionaries.md):** Layouts, источники, `dictGet()`, LIFETIME, мониторинг `system.dictionaries`.
7.  **[Моделирование данных](./clickhouse-data-modeling.md):** Паттерны time-series, сессии, воронки, высококардинальные теги, приближённые и оконные функции, SAMPLE, LIMIT BY, downsampling, CHECK constraints.
8.  **[Клиентский инструментарий](./clickhouse-client-tools.md):** clickhouse-client, clickhouse-local, clickhouse-benchmark, clickhouse-format, HTTP-интерфейс, мосты, методология нагрузочного тестирования.
9.  **[Безопасность](./clickhouse-security.md):** RBAC, quotas, LDAP, allow_networks, RLS, TOTP, хеширование паролей.
10.  **[Мониторинг и системные таблицы](./clickhouse-monitoring.md):** Порты, каталог `system.*`, metric_log, query_thread_log, Prometheus, алерты.
11.  **[Бэкапы и восстановление](./clickhouse-backup.md):** BACKUP/RESTORE, FREEZE/FETCH, инкрементальные бэкапы, RPO/RTO, бэкап Keeper, retention, мониторинг бэкапов.
12.  **[Capacity Planning, обновления и HA](./clickhouse-capacity-upgrades.md):** Sizing, rolling upgrade, HAProxy, connection pooling.
13.  **[ClickHouse в Kubernetes](./clickhouse-kubernetes.md):** Развертывание через оператор, манифесты и HA-конфигурации.
14.  **[Интеграция Kafka](./clickhouse_kafka_integration.md):** Движок Kafka, хранение offsets в Keeper, конвейеры, DLQ, Avro/Protobuf.
15.  **[Интеграция S3](./clickhouse_s3_integration.md):** Tiered Storage, S3Queue, zero-copy, Iceberg.
16.  **[Эволюция схемы и ALTER TABLE](./clickhouse-schema-evolution.md):** ADD/DROP/MODIFY COLUMN, DEFAULT/MATERIALIZED/EPHEMERAL/ALIAS, CHECK/ASSUME constraints, MODIFY SETTING.
17.  **[Полнотекстовый поиск](./clickhouse-full-text-search.md):** text-индекс (inverted), токенизаторы, hasToken/hasPhrase, миграция с ngrambf_v1.
18.  **[Наблюдаемость (логи, метрики, трейсы)](./clickhouse-observability.md):** Prometheus remote_write, OTLP, Vector, Jaeger, downsampling.
19.  **[Высокая конкурентность](./clickhouse-high-concurrency.md):** Query Cache, Parallel Replicas, connection pooling.
20.  **[Пользовательские функции (UDF)](./clickhouse-udf.md):** CREATE FUNCTION, executable UDF, system.functions.
21.  **[Файловая система и хранение](./clickhouse-filesystem-storage.md):** XFS vs ext4, опции монтирования, RAID, swap, I/O scheduler.
22.  **[Отказоустойчивость и DR](./clickhouse-disaster-recovery.md):** RPO/RTO, cross-DC, multi-cluster, DR runbook.
23.  **[Коды ошибок](./clickhouse-error-codes.md):** Справочник кодов, system.errors, error_log, retryable-ошибки.
24.  **[Вопросы на собеседовании](./clickhouse-interview-qa.md):** Архитектура, индексы, движки, репликация, производительность.
25.  **[Альтернативы и сравнение](./clickhouse-alternatives.md):** Druid, Pinot, StarRocks, Doris, Greenplum, Elasticsearch, TimescaleDB.

---

## Практические сценарии

### Быстрый старт: запуск и первая проверка

Для запуска ClickHouse в минимальной конфигурации достаточно Docker.

**Предварительные требования:**
- Docker / Docker Compose.
- Настройка лимитов ОС (для Production): `nofile` не менее 262144 (подробнее в [Эксплуатации](./clickhouse-operations.md)).

**1. Запуск сервера:**
```bash
docker run -d \
    --name clickhouse-server \
    --ulimit nofile=262144:262144 \
    -p 8123:8123 \
    -p 9000:9000 \
    clickhouse/clickhouse-server
```

**2. Подключение и создание базы данных:**
```bash
docker exec -it clickhouse-server clickhouse-client

-- Внутри клиента:
CREATE DATABASE IF NOT EXISTS devops;
USE devops;
```

**3. Создание таблицы и вставка данных:**
```sql
CREATE TABLE logs (
    timestamp DateTime,
    service_name String,
    message String,
    severity LowCardinality(String)
) ENGINE = MergeTree()
ORDER BY (timestamp, service_name);

-- Вставка демонстрационного батча
INSERT INTO logs VALUES 
    (now(), 'api-gateway', 'Request processed', 'INFO'),
    (now() - 60, 'auth-service', 'Invalid token', 'WARN'),
    (now() - 120, 'db-proxy', 'Connection timeout', 'ERROR');
```

**4. Выполнение аналитического запроса:**
```sql
SELECT 
    severity, 
    count() AS total 
FROM logs 
GROUP BY severity 
ORDER BY total DESC;
```

**5. Очистка (Cleanup):**
```sql
DROP DATABASE devops;
-- Выход из клиента: exit
-- Остановка контейнера: docker stop clickhouse-server && docker rm clickhouse-server
```

### Установка на bare metal (Linux)

Для эксплуатации на физическом сервере или виртуальной машине используйте официальный установщик или пакеты deb/rpm.

**1. Установка через официальный скрипт (любая версия):**
```bash
curl https://clickhouse.com/ | sh
# → Устанавливает последнюю стабильную версию, создает пользователя clickhouse,
#   systemd-сервис clickhouse-server и каталог /var/lib/clickhouse/
```

**2. Запуск и включение автозапуска:**
```bash
sudo systemctl enable --now clickhouse-server
# → Active: active (running) с момента запуска
```

**3. Проверка работоспособности:**
```bash
clickhouse-client --query "SELECT version()"
# → 26.9.4.3 (или текущий стабильный релиз)
```

**4. Основные каталоги:**
- Данные: `/var/lib/clickhouse/`
- Логи: `/var/log/clickhouse-server/`
- Конфигурация: `/etc/clickhouse-server/` (`config.xml`, `users.xml`, каталоги `config.d/` и `users.d/` для кастомных настроек)

### Когда переходить на ClickHouse

**Сигналы о том, что PostgreSQL не справляется:**

1. **Медленные агрегаты:** запросы `COUNT`, `SUM`, `GROUP BY` на таблицах более 10–50 млн строк занимают десятки секунд.
2. **Нагрузка от аналитики:** тяжелые отчетные запросы замедляют работу продуктового трафика.
3. **Проблемы с объемами:** таблицы превышают 1–10 ТБ, и вертикальное масштабирование становится нецелесообразным.
4. **Медленные материализованные представления:** обновление данных в PostgreSQL происходит дольше, чем интервал их актуальности.

**Правило 80/20:** если 20% запросов (аналитических) потребляют 80% ресурсов процессора — пора выделять аналитику в отдельную СУБД.

### Когда НЕ использовать ClickHouse

- Требуется полная поддержка транзакций (ACID).
- Объем данных менее 1 ТБ (PostgreSQL обычно справляется).
- Требуются частые точечные обновления или удаления данных (движок `MergeTree` не предназначен для частых `UPDATE/DELETE`).
- В запросах преобладают выборки всех полей строки (`SELECT *`).

### Расширенные примеры настройки

**Создание распределенной таблицы (Distributed):**
Используется для горизонтального масштабирования на кластер.
```sql
CREATE TABLE events_all AS events
ENGINE = Distributed(cluster_name, default, events, rand());
```

**Работа с JSON (v24.8+):**
ClickHouse автоматически выводит схему и оптимизирует хранение JSON-объектов в отдельных подколонках.
```sql
CREATE TABLE app_logs (
    timestamp DateTime,
    data JSON
) ENGINE = MergeTree() ORDER BY timestamp;

-- Запрос по динамическому полю без изменения схемы
SELECT data.user.id, count() FROM app_logs WHERE data.status = 'error' GROUP BY data.user.id;
```

---

## Troubleshooting (типичные проблемы)

Краткий справочник для быстрой диагностики. Детальные сценарии и команды — в **[Эксплуатации](./clickhouse-operations.md)** и **[Кластерном управлении](./clickhouse-cluster.md)**.

| Проблема | Причина | Быстрое решение |
| :--- | :--- | :--- |
| **Too many parts (Code: 252)** | Слишком частые мелкие вставки; фоновые слияния не успевают обрабатывать новые части. | Включить `async_insert = 1` или батчинг от 10 000 строк на клиенте. |
| **Memory limit exceeded (Code: 241)** | Запрос превысил `max_memory_usage`. | Уменьшить выборку, добавить `PREWHERE`, включить `max_bytes_before_external_group_by`. |
| **Replica in read-only (Code: 242)** | Потеря связи с ClickHouse Keeper / ZooKeeper. | Проверить сеть до Keeper, `operation_timeout_ms`, состояние `system.replicas`. |
| **Connection refused (порт 9000/8123)** | Сервер не запущен или прослушивает только localhost. | `sudo systemctl status clickhouse-server`; проверить `<listen_host>` в `config.xml`. |
| **Disk full** | Накопитель заполнен данными или логами. | Удалить старые партиции (`DROP PARTITION`), очистить лог-таблицы через TTL, проверить `system.disks`. |

### Диагностика медленных запросов

```sql
SELECT query, query_duration_ms, read_rows, formatReadableSize(memory_usage) as mem
FROM system.query_log
WHERE type = 'QueryFinish'
ORDER BY query_duration_ms DESC
LIMIT 10;
```

Подробнее: **[Эксплуатация](./clickhouse-operations.md#диагностика-медленных-запросов)**.

## Интеграция с BI-системами

- **Apache Superset:** нативная поддержка, рекомендуется использовать SQLAlchemy-коннектор.
- **Grafana:** через официальный плагин ClickHouse Data Source. Идеально для построения дашбордов по логам и метрикам.
- **Metabase / Redash:** поддержка через плагины сообщества.
- **Tabix:** встроенный легковесный open-source веб-интерфейс для SQL-запросов.

## Лучшие практики

1.  **Батчинг при вставке:** Минимум 10 000 — 100 000 строк за раз. Частые мелкие вставки приводят к переполнению фоновых процессов слияния данных (`Too many parts`). Если батчинг на стороне клиента невозможен, используйте параметр `async_insert = 1`.
2.  **Правильный выбор ORDER BY:** Ключ сортировки должен соответствовать наиболее частым фильтрам в `WHERE`. Первым в ключе должен стоять столбец с наименьшей мощностью (cardinality), который часто используется в фильтрах.
3.  **Использование словарей:** Для ускорения JOIN со справочниками используйте `Dictionaries` с хранением в RAM. Это позволяет избежать дорогостоящих сетевых перемещений данных.
4.  **Денормализация:** ClickHouse работает быстрее с плоскими широкими таблицами, чем со сложными схемами «звезда» или «снежинка».
5.  **Типизация:** Используйте `LowCardinality(String)` для строк с небольшим количеством уникальных значений (например, `status`, `country`, `browser`) — это экономит память и ускоряет фильтрацию.
6.  **TTL для очистки и Tiered Storage:** Настраивайте `TTL` на уровне таблиц для автоматического удаления или перемещения старых данных на холодные диски/S3. Это предотвращает неконтролируемый рост `/var/lib/clickhouse/`.
7.  **Мониторинг системных таблиц:** Добавьте в Prometheus/Grafana дашборд по `system.metrics`, `system.events` и `system.asynchronous_metrics`. Для быстрого поиска проблем используйте `system.query_log`.
8.  **Безопасность:** Включайте RBAC (`<access_management>1</access_management>`), ограничивайте права по принципу наименьших привилегий, настраивайте TLS на портах 8123/8443/9440. Детали: **[Эксплуатация](./clickhouse-operations.md)**.

## Дополнительная информация

### Ограничения и известные особенности

- **MergeTree не предназначен для частых UPDATE/DELETE:** точечные обновления вызывают мутации, переписывающие целые куски данных. Для сценариев с изменяемыми сущностями используйте `CollapsingMergeTree` или `ReplacingMergeTree`.
- **SELECT * неэффективен:** колоночная модель подразумевает выбор только нужных колонок. `SELECT *` считывает все колонки таблицы и лишает преимущества колоночного хранения.
- **Транзакции:** отсутствует многострочная ACID-транзакция. Каждая вставка атомарна на уровне отдельной части данных, но согласованность между частями обеспечивается асинхронно.
- **Материализованные представления не обрабатывают UPDATE/DELETE:** MV срабатывают только на новые вставки. Изменения существующих данных через мутации не пересчитывают MV автоматически.
- **Высокая кардинальность индексов:** колонки с миллионами уникальных значений (например, `user_id`, `request_id`) в PRIMARY KEY приводят к росту разреженного индекса и потреблению памяти. Для таких полей используйте `bloom_filter` индексы или предварительную агрегацию.

### Типы данных

- **Числовые:** `Int8`–`Int256`, `UInt8`–`UInt256`, `Float64`, `Decimal`.
- **Дата и время:** `Date`, `DateTime`, `DateTime64`.
- **Сложные:** `Array(T)`, `Tuple(...)`, `Map(K, V)`.
- **Специализированные:** `IPv4`, `IPv6`, `UUID`.
- **JSON:** специализированный тип для эффективного хранения полуструктурированных данных.

### Интеграция и экосистема

- **PostgreSQL:** использование движков `PostgreSQL` или `clickhouse_fdw`. Детально: **[Интеграция PostgreSQL и ClickHouse](../PostgreSQL/Integrations/clickhouse.md)**.
- **Kafka:** потоковая обработка данных в реальном времени через движок `Kafka`. Детально: **[Интеграция ClickHouse и Kafka](./clickhouse_kafka_integration.md)**.
- **S3:** объектные хранилища и многоуровневое хранение (Tiered Storage). Детально: **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)**.
- **Материализованные представления (Materialized Views):** работают как триггеры на вставку, позволяя агрегировать данные "на лету" без пересчета всей таблицы.
- **ClickHouse Keeper:** высокопроизводительная замена ZooKeeper, встроенная в ClickHouse.

### Сравнение с другими системами

Детальное сравнение ClickHouse с альтернативами — в **[Альтернативы ClickHouse](./clickhouse-alternatives.md)**.

### Смежные темы

- Общая теория шардирования — **[Шардирование](../Concepts/sharding.md)**.
- Масштабирование PostgreSQL — **[PostgreSQL Scaling](../PostgreSQL/Concepts/scaling.md)**.
- Работа с Foreign Data Wrappers — **[FDW в PostgreSQL](../PostgreSQL/Integrations/fdw.md)**.

### Системные пути и файлы (Linux)

При on-prem установке через официальный скрипт или пакеты:

- **Данные:** `/var/lib/clickhouse/` (разделы `data/`, `system/`, `format_schemas/`, `dictionaries/`)
- **Логи:** `/var/log/clickhouse-server/` (`clickhouse-server.log`, `clickhouse-client.log`, `stderr.log`)
- **Конфигурация сервера:** `/etc/clickhouse-server/`
  - Основные файлы: `config.xml`, `users.xml`
  - Кастомные настройки: `config.d/*.xml`, `users.d/*.xml`
- **Секреты и ключи:** `/etc/clickhouse-server/ssl/` (сертификаты TLS), `/etc/clickhouse-server/certs/`
- **Systemd unit:** `clickhouse-server.service` (работает от пользователя `clickhouse`)

**Важно:** не редактируйте `config.xml` напрямую — используйте файлы в `config.d/` для переопределения параметров. Это упрощает обновления и откат настроек.
