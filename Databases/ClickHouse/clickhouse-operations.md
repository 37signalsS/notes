# ClickHouse — Эксплуатация и обслуживание

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**RBAC** — управление доступом на основе ролей, где права назначаются ролям, а роли — пользователям, вместо прямой привязки прав к учётным записям.

**Named Collections** — наборы параметров подключения к внешним системам (S3-совместимые хранилища, Kafka), хранимые в XML-конфигурации и используемые через `CREATE NAMED COLLECTION`.

**Mutation** — операция изменения данных в ClickHouse (`UPDATE`, `DELETE`, `MATERIALIZE`), которая перезаписывает целые куски (parts) и выполняется асинхронно.

**External Aggregation** — механизм, при котором промежуточные результаты агрегации (хэш-таблицы) не помещаются в RAM и сбрасываются на диск, что приводит к падению производительности в 10–50 раз.

**TTL** — политика автоматического удаления или перемещения данных по времени, определяемая на уровне таблицы или колонки.

**clickhouse-backup** — сторонний инструмент с открытым исходным кодом для создания резервных копий данных и метаданных ClickHouse с поддержкой локальных и S3-совместимых хранилищ.

---

## Требования и подготовка

### Системные требования

Для обеспечения заявленной производительности ClickHouse требует специфической настройки оборудования:

- **Процессор (CPU):** Минимум 16 ядер (рекомендуется 32+).
    - *Почему:* Требуется поддержка набора инструкций **SSE 4.2** и предпочтительно **AVX-512** для реализации механизмов **векторного выполнения запросов**, которые позволяют обрабатывать блоки данных параллельно на уровне CPU.
- **Память (RAM):** Минимум 128 ГБ (рекомендуется 512+ ГБ).
    - *Почему:* ClickHouse выполняет агрегации и JOIN в оперативной памяти (хэш-таблицы). Недостаток RAM ведет к сбросу промежуточных данных на диск (External Aggregation), что замедляет запросы в 10–50 раз.
- **Диски:** Только SSD/NVMe.
    - *Почему:* Движок `MergeTree` постоянно выполняет фоновые слияния (merges) данных. Высокие задержки (latency) HDD блокируют процессы записи и ведут к ошибке `Too many parts`.
- **Сеть:** 10 Gbps и выше для эффективного шардирования и репликации.

### Подготовка ОС (Linux Tuning)

ClickHouse чувствителен к системным лимитам и поведению планировщика памяти.

**1. Настройка лимитов (limits.conf):**
Установите `nofile` (максимальное количество открытых файлов) не менее 262144. ClickHouse хранит каждую колонку в отдельном файле, поэтому в кластере с множеством таблиц лимит в 1024–4096 быстро исчерпывается.
```bash
# /etc/security/limits.d/clickhouse.conf
clickhouse soft nofile 262144
clickhouse hard nofile 262144
```

**2. Управление виртуальной памятью (sysctl):**
- **Transparent Huge Pages (THP):** Отключите (`madvise` или `never`). THP вызывает непредсказуемые задержки (stalls) при аллокации памяти под хэш-таблицы ClickHouse.
- **vm.max_map_count:** Увеличьте до 262144 или выше. Это ограничение на количество областей отображения памяти (VMA).
- **vm.overcommit_memory:** Установите в `0` или `1` для предотвращения агрессивного убийства процесса OOM Killer при работе с большими блоками памяти.

```bash
# Применение настроек
sysctl -w vm.max_map_count=262144
echo 'never' > /sys/kernel/mm/transparent_hugepage/enabled
```

**3. Планировщик диска:**
Используйте `noop` или `deadline` для SSD/NVMe. Планировщики типа `cfq` ориентированы на минимизацию перемещений головок HDD и только создают лишние задержки для твердотельных накопителей.

**4. Systemd-юниты и автозагрузка:**
Проверьте, что сервис включён в автозагрузку и имеет корректные зависимости:
```bash
# Проверка статуса
systemctl status clickhouse-server
# Включение автозагрузки
systemctl enable --now clickhouse-server
```

**5. Проверка доступных CPU-инструкций:**
Убедитесь, что процессор поддерживает требуемые наборы инструкций:
```bash
grep -E 'sse4_2|avx|avx2' /proc/cpuinfo
# → sse4_2, avx, avx2 должны присутствовать
```

---

## Безопасность и управление доступом

Подробная документация по RBAC, TLS/SSL, LDAP, quotas, аудиту и управлению доступом — в **[Безопасность ClickHouse](./clickhouse-security.md)**. Ниже — краткая сводка и уникальные для операций детали.

### SQL-driven RBAC

Современный ClickHouse управляется через SQL-команды (Role-Based Access Control). Для включения:

```xml
<access_management>1</access_management>
```

Подробности: **[Включение RBAC](./clickhouse-security.md#включение-rbac-предварительная-настройка)**.

**Примеры:**
- **Создание роли и пользователя:**
  ```sql
  CREATE ROLE analyst;
  GRANT SELECT ON reporting.* TO analyst;
  CREATE USER readonly_user IDENTIFIED WITH sha256_password BY 'secure_pass';
  GRANT analyst TO readonly_user;
  ```
- **Row-Level Security (RLS):** Подробности — **[Row-Level Security](./clickhouse-security.md#row-level-security-rls)**.
  ```sql
  CREATE ROW POLICY filter_by_client ON db.table FOR SELECT USING client_id = 101 TO readonly_user;
  ```

### Шифрование и Named Collections
- **TLS/SSL:** Подробности настройки HTTPS (8443), native TLS (9440), cipher suites и `listen_host` — **[TLS/SSL шифрование](./clickhouse-security.md#tlsssl-шифрование-соединений)**.
- **Именованные коллекции (Named Collections):** Позволяют абстрагировать параметры подключения к S3-совместимым хранилищам или Kafka.
  ```xml
  <!-- /etc/clickhouse-server/config.d/s3_collections.xml -->
  <clickhouse>
      <named_collections>
          <s3_prod>
              <endpoint>http://minio.internal:9000/clickhouse-backups/</endpoint>
              <access_key_id>minioadmin</access_key_id>
              <secret_access_key>minioadmin</secret_access_key>
          </s3_prod>
      </named_collections>
  </clickhouse>
  ```
  Использование в SQL: `SELECT * FROM s3(s3_prod, 'data.csv')`.

  **Важно:** Используйте `http://` для S3-совместимых on-prem хранилищ (MinIO, Ceph RGW), если TLS не настроен. Для AWS S3 или аналогичных сервисов указывайте `https://` и соответствующие endpoints.

### Управление учётными записями и аудит

- **Создание пользователей с ограничением по ресурсам:**
  ```sql
  CREATE USER etl_user SETTINGS max_execution_time = 300, max_memory_usage = 10000000000;
  ```
- **Аудит через `system.query_log`:** Конфигурация `query_log` с TTL и `text_log` — **[Аудит запросов](./clickhouse-security.md#аудит-запросов)**.

---

## Резервное копирование и восстановление

Подробная документация по `clickhouse-backup`, нативным `BACKUP/RESTORE`, `FREEZE/FETCH` и retention-политикам — **[Бэкапы и восстановление](./clickhouse-backup.md)**. Ниже — операционная сводка и checklist для SRE.

### Операционный checklist для бэкапа

1. **Перед обновлением:** выполните `clickhouse-backup create pre-upgrade-$(date +%F)` — см. **[Бэкапы](./clickhouse-backup.md#clickhouse-backup-автоматизация)**.
2. **Для кластера:** используйте `BACKUP ALL ON CLUSTER` или `clickhouse-backup` с `--rbac` для согласованности ролей.
3. **Восстановление в DR:** скачайте бэкап и восстановите на кластере с той же или новее версии — см. **[DR-процедуры](./clickhouse-disaster-recovery.md)**.
4. **Проверка целостности:** используйте `clickhouse-backup validate` или `RESTORE ... CHECK` для нативных бэкапов.

## Обновления и обслуживание (Maintenance)

Подробнее о capacity planning, breaking changes и rolling update — **[Capacity Planning и обновления](./clickhouse-capacity-upgrades.md)**. Ключевые правила:

- **Keeper обновляется первым** (обратная совместимость через Raft).
- **Rolling update** по одной реплике: остановить → обновить → дождаться `absolute_delay ≈ 0` → следующая.
- **Между LTS:** проверяйте `system.settings_changes` на breaking changes перед upgrade.

### Очистка системных логов

По умолчанию ClickHouse пишет все запросы, ошибки и трейсы в таблицы `system.query_log`, `system.trace_log` и др. Без настройки **TTL** эти таблицы могут занять сотни гигабайт и переполнить диск.

**Настройка TTL для логов:**
```sql
ALTER TABLE system.query_log MODIFY TTL event_date + INTERVAL 30 DAY;
ALTER TABLE system.trace_log MODIFY TTL event_date + INTERVAL 7 DAY;
ALTER TABLE system.text_log MODIFY TTL event_date + INTERVAL 14 DAY;
```

### Мониторинг мутаций

Мутации (`UPDATE`, `DELETE`) в ClickHouse являются тяжелыми операциями, которые переписывают целые куски данных. Зависшая мутация может блокировать слияния.
```sql
-- Проверка активных мутаций
SELECT database, table, command, is_done, parts_to_do
FROM system.mutations WHERE is_done = 0;
```

**Решение зависших мутаций:**
Если мутация висит больше 24 часов, проверьте `system.mutations` и рассмотрите `SYSTEM STOP MERGES` для временной остановки слияний, затем `SYSTEM RESTART REPLICAS` для перезапуска реплик.

### Очистка старых данных

Используйте `DROP PARTITION` для быстрого удаления устаревших данных:
```sql
-- Удаление партиции старше 90 дней
ALTER TABLE logs DROP PARTITION '2026-07';
```

**Ротация логов через logrotate:**
```bash
# /etc/logrotate.d/clickhouse
/var/log/clickhouse-server/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload clickhouse-server
    endscript
}
```

### Управление слияниями

В период пиковых нагрузок можно приостановить фоновые слияния, чтобы они не конкурировали с запросами:
```sql
-- Остановка слияний
SYSTEM STOP MERGES;
-- Возобновление слияний
SYSTEM START MERGES;
```

---

## Мониторинг и диагностика

Подробнее о системных таблицах, метриках Prometheus, алертах и SLO — **[Мониторинг и системные таблицы](./clickhouse-monitoring.md)**. Здесь приведены практические сценарии использования этих метрик в работе SRE.

### Анализ выполнения запросов (EXPLAIN)

Инструмент `EXPLAIN` позволяет увидеть план выполнения до запуска запроса.
- `EXPLAIN indexes = 1 SELECT ...` — проверка, какие индексы MergeTree сработали.
- `EXPLAIN pipeline SELECT ...` — визуализация многопоточности выполнения.

### Мониторинг здоровья реплик

```sql
SELECT
    database,
    table,
    is_session_expired,
    is_leader,
    absolute_delay
FROM system.replicas
WHERE is_healthy = 0;
```

Подробнее о диагностике реплик и кластерных проблемах — **[Кластерное управление](./clickhouse-cluster.md#диагностика-здоровья-репликации)**.

---

## Устранение неисправностей

### Типичные проблемы и решения

1.  **Too many parts (Code: 252):**
    - *Причина:* Слишком частые вставки мелкими порциями. ClickHouse не успевает объединять (merge) куски данных.
    - *Решение:* Батчинг на клиенте (100k+ строк) или включение `async_insert = 1`.
2.  **Memory limit exceeded (Code: 241):**
    - *Причина:* Запрос превысил `max_memory_usage`.
    - *Решение:* Оптимизация запроса (уменьшение выборки), использование `JOIN_ANY` или включение `max_bytes_before_external_group_by`.
3.  **Replica is in read-only mode (Code: 242):**
    - *Причина:* Потеря сессии в ClickHouse Keeper / ZooKeeper. Узел не может подтвердить право на запись.
    - *Решение:* Проверьте сеть до Keeper и параметры `operation_timeout_ms` в конфиге.
4.  **DNS failure (Code: 198):**
    - *Причина:* ClickHouse не может разрешить имена хостов других реплик.
    - *Решение:* Проверьте `/etc/hosts` или настройте секцию `<dns_cache_update_period>`.
5.  **Mutation зависла на этапе `Merging parts`:**
    - *Причина:* Недостаточно места на диске или слишком высокая нагрузка.
    - *Решение:* Проверьте `system.mutations`, убедитесь в наличии свободного места на диске, временно остановите слияния через `SYSTEM STOP MERGES`.

### Сценарий: Disk Full (Переполнение диска)

Если диск заполнен на 100%, ClickHouse может упасть и не запуститься.
**Процедура восстановления:**
1. Удалите старые логи из `/var/log/clickhouse-server/`.
2. Если места всё еще нет, переместите (не удаляйте!) несколько крупных кусков из `/var/lib/clickhouse/data/database/table/detached/` на другой диск.
3. Запустите сервер.
4. Выполните очистку (удаление старых партиций через `DROP PARTITION`).

### Сценарий: Потеря реплики (Replica lag)

**Диагностика:**
```sql
SELECT
    database, table,
    absolute_delay,
    queue_size,
    inserts_queue_size
FROM system.replicas
WHERE absolute_delay > 0;
```

**Решение:**
1. Проверьте доступность Keeper/ZooKeeper: `system.zk` или `system.clickhouse_cluster`.
2. Проверьте сетевое соединение между узлами (порт 9000, 9009, 22 для SSH).
3. Если реплика отстала значительно, рассмотрите `SYSTEM RESTART REPLICAS`.

---

## Лучшие практики

1.  **Батчинг при вставке:** Минимум 10 000 — 100 000 строк за раз. Частые мелкие вставки приводят к переполнению фоновых процессов слияния данных (`Too many parts`). Если батчинг на стороне клиента невозможен, используйте параметр `async_insert = 1`.
2.  **Настройка лимитов ОС:** Установите `nofile` не менее 262144, отключите THP, используйте `noop`/`deadline` планировщик для SSD/NVMe.
3.  **Использование словарей:** Для ускорения JOIN со справочниками используйте `Dictionaries` с хранением в RAM. Это позволяет избежать дорогостоящих сетевых перемещений данных.
4.  **Типизация:** Используйте `LowCardinality(String)` для строк с небольшим количеством уникальных значений (например, `status`, `country`, `browser`) — это экономит память и ускоряет фильтрацию.
5.  **Мониторинг системных таблиц:** Добавьте в Prometheus/Grafana дашборд по `system.metrics`, `system.events` и `system.asynchronous_metrics`. Для быстрого поиска проблем используйте `system.query_log`.
6.  **Аудит и безопасность:** Включайте RBAC (`<access_management>1</access_management>`), ограничивайте права по принципу наименьших привилегий, настраивайте TLS на портах 8123/8443/9440.
7.  **Автоматизация бэкапов:** Настройте регулярные бэкапы через `clickhouse-backup` с хранением на S3-совместимом on-prem хранилище (MinIO, Ceph RGW) или сетевом диске.
8.  **TTL для очистки:** Настраивайте `TTL` на уровне таблиц для автоматического удаления или перемещения старых данных. Это предотвращает неконтролируемый рост `/var/lib/clickhouse/`.
9.  **Планирование обслуживания:** Проводите рутинные проверки реплик (`system.replicas`), мутаций (`system.mutations`) и дискового пространства (`system.disks`) не реже одного раза в неделю.
10. **Документация изменений:** Ведите changelog конфигурации (в Git или CM-системе), особенно при изменении `config.xml`, `users.xml`, параметров хранения и схемы партиционирования.

---

## Дополнительная информация

### Смежные темы

- Бэкапы, восстановление, retention — **[Бэкапы и восстановление](./clickhouse-backup.md)**.
- Аварийное восстановление и DR-процедуры — **[Отказоустойчивость и DR](./clickhouse-disaster-recovery.md)**.
- Capacity planning, breaking changes, rolling update — **[Capacity Planning и обновления](./clickhouse-capacity-upgrades.md)**.
- Репликация, шардирование, Keeper, HA — **[Кластерное управление](./clickhouse-cluster.md)**.
- Мониторинг и системные таблицы — **[Мониторинг и системные таблицы](./clickhouse-monitoring.md)**.
- Безопасность (RBAC, TLS, RLS, аудит) — **[Безопасность](./clickhouse-security.md)**.
- SQL-операции с партициями и мутациями — **[Операционный SQL](./clickhouse-sql-operations.md)**.
- Производительность и оптимизация запросов — **[Производительность](./clickhouse-performance.md)**.
- Шардирование (общая теория) — **[Шардирование баз данных](../Databases/Concepts/sharding.md)**.

### Проверка здоровья сервиса (health check)

**HTTP health endpoint (8123):**
```bash
# Readiness check
curl -sf http://localhost:8123/ping
# → Ok

# Liveness check (в K8s — readinessProbe/livenessProbe)
curl -sf http://localhost:8123/ping?extended=1
# → {"result": "Ok", "host_name": "...", "version": "26.9.1.1"}
```

**Systemd service management:**
```bash
# Проверка статуса и автозагрузки
systemctl is-active --quiet clickhouse-server && echo "running"
systemctl is-enabled clickhouse-server

# Перезагрузка конфигурации без остановки сервера
systemctl reload clickhouse-server
# или: clickhouse-client --query "SYSTEM RELOAD CONFIG"

# Graceful остановка (дождётся завершения запросов)
systemctl stop clickhouse-server
```

**Проверка подключения к Keeper:**
```bash
# Native Keeper health (порт 9182)
curl -s http://localhost:9182/ready
# → OK

# 4-letter commands (порт 2181)
echo ruok | nc localhost 2181
# → imok
```

---

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

### Ограничения и известные особенности

- **MergeTree не предназначен для частых UPDATE/DELETE:** точечные обновления вызывают мутации, переписывающие целые куски данных. Для сценариев с изменяемыми сущностями используйте `CollapsingMergeTree` или `ReplacingMergeTree`.
- **Транзакции:** отсутствует многострочная ACID-транзакция. Каждая вставка атомарна на уровне отдельной части данных, но согласованность между частями обеспечивается асинхронно.
- **Материализованные представления не обрабатывают UPDATE/DELETE:** MV срабатывают только на новые вставки. Изменения существующих данных через мутации не пересчитывают MV автоматически.
- **Высокая кардинальность индексов:** колонки с миллионами уникальных значений (например, `user_id`, `request_id`) в PRIMARY KEY приводят к росту разреженного индекса и потреблению памяти. Для таких полей используйте `bloom_filter` индексы или предварительную агрегацию.
