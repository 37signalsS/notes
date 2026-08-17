# ClickHouse — Эксплуатация и обслуживание

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

---

## Безопасность и управление доступом

### SQL-driven RBAC
Современный ClickHouse перешел от конфигурации пользователей в `users.xml` к управлению через SQL-команды (Role-Based Access Control).

**Включение RBAC:**
Для возможности создания пользователей через SQL убедитесь, что в профиле пользователя (обычно `default`) в `users.xml` включен флаг:
```xml
<access_management>1</access_management>
```

**Примеры управления:**
- **Создание роли и пользователя:**
  ```sql
  CREATE ROLE analyst;
  GRANT SELECT ON reporting.* TO analyst;
  CREATE USER readonly_user IDENTIFIED WITH sha256_password BY 'secure_pass';
  GRANT analyst TO readonly_user;
  ```
- **Row-Level Security (RLS):** Позволяет ограничить доступ к строкам на основе значений.
  ```sql
  CREATE ROW POLICY filter_by_client ON db.table FOR SELECT USING client_id = 101 TO readonly_user;
  ```

### Шифрование и Named Collections
- **TLS/SSL:** Всегда настраивайте HTTPS (порт 8443) и защищенный нативный протокол (9440). Пути к сертификатам прописываются в `config.d/ssl.xml`.
- **Именованные коллекции (Named Collections):** Позволяют абстрагировать параметры подключения к S3/Kafka.
  ```xml
  <!-- /etc/clickhouse-server/config.d/s3_collections.xml -->
  <clickhouse>
      <named_collections>
          <s3_prod>
              <endpoint>https://s3.amazonaws.com/bucket/folder/</endpoint>
              <access_key_id>AKIA...</access_key_id>
              <secret_access_key>...</secret_access_key>
          </s3_prod>
      </named_collections>
  </clickhouse>
  ```
  Использование в SQL: `SELECT * FROM s3(s3_prod, 'data.csv')`.

---

## Резервное копирование и восстановление

### clickhouse-backup
Стандартный инструмент с открытым исходным кодом для автоматизации бэкапов.

**Создание бэкапа (Step-by-Step):**
1. Настройте `config.yml` (адрес сервера, параметры S3).
2. Создайте локальный снимок: `clickhouse-backup create full_backup_$(date +%F)`.
3. Загрузите в облако: `clickhouse-backup upload full_backup_$(date +%F)`.

**Восстановление:**
1. Скачайте бэкап: `clickhouse-backup download backup_name`.
2. Восстановите схему и данные: `clickhouse-backup restore backup_name`.
   *Внимание:* Рекомендуется восстанавливать данные на кластер с той же версией ClickHouse.

---

## Регулярное обслуживание (Maintenance)

### Очистка системных логов
По умолчанию ClickHouse пишет все запросы, ошибки и трейсы в таблицы `system.query_log`, `system.trace_log` и др. Без настройки **TTL** эти таблицы могут занять сотни гигабайт и переполнить диск.

**Настройка TTL для логов:**
```sql
ALTER TABLE system.query_log MODIFY TTL event_date + INTERVAL 30 DAY;
ALTER TABLE system.trace_log MODIFY TTL event_date + INTERVAL 7 DAY;
```

### Мониторинг мутаций
Мутации (`UPDATE`, `DELETE`) в ClickHouse являются тяжелыми операциями, которые переписывают целые куски данных. Зависшая мутация может блокировать слияния.
```sql
-- Проверка активных мутаций
SELECT database, table, command, is_done, parts_to_do 
FROM system.mutations WHERE is_done = 0;
```

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

### Сценарий: Disk Full (Переполнение диска)
Если диск заполнен на 100%, ClickHouse может упасть и не запуститься.
**Процедура восстановления:**
1. Удалите старые логи из `/var/log/clickhouse-server/`.
2. Если места всё еще нет, переместите (не удаляйте!) несколько крупных кусков из `/var/lib/clickhouse/data/database/table/detached/` на другой диск.
3. Запустите сервер.
4. Выполните очистку (удаление старых партиций через `DROP PARTITION`).

---

## Мониторинг и диагностика

### Ключевые таблицы для Prometheus
- **`system.metrics`:** Мгновенные значения (количество активных запросов, соединений).
- **`system.events`:** Кумулятивные счетчики (общее количество слияний, вставок).
- **`system.asynchronous_metrics`:** Значения, обновляемые в фоне (использование CPU, RAM, диска).

### Диагностика медленных запросов
```sql
SELECT 
    query, 
    query_duration_ms, 
    read_rows, 
    formatReadableSize(memory_usage) as mem
FROM system.query_log 
WHERE type = 'QueryFinish' 
ORDER BY query_duration_ms DESC 
LIMIT 10;
```

### Анализ выполнения запросов (EXPLAIN)
Инструмент `EXPLAIN` позволяет увидеть план выполнения до запуска запроса.
- `EXPLAIN indexes = 1 SELECT ...` — проверка, какие индексы MergeTree сработали.
- `EXPLAIN pipeline SELECT ...` — визуализация многопоточности выполнения.
