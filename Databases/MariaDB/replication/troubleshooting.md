# Диагностика и Troubleshooting репликации MariaDB

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Replication Lag (Лаг репликации)** — временная задержка между фиксацией транзакции на источнике и её применением на реплике. Измеряется в секундах (`Seconds_Behind_Source`) или в позиции GTID. Критичен для кластеров: лаг > 60 секунд требует вмешательства.
*   **`Seconds_Behind_Source`** — показатель лага, вычисляемый как разница между временем текущего события в SQL Thread и временем его записи на источнике. Может быть неточным при длительных транзакциях, параллельной репликации или разрыве сети.
*   **Relay Log Corruption (Повреждение Relay Log)** — повреждение файла relay log на реплике, приводящее к остановке SQL Thread.
*   **GTID Skip (Пропуск GTID)** — механизм пропуска битой транзакции в GTID-репликации путем записи пустой транзакции с тем же GTID на реплике.
*   **`performance_schema.replication_applier_status_by_worker`** — Performance Schema таблица, показывающая состояние каждого параллельного рабочего потока репликации и транзакцию, которую он currently применяет.
*   **`pt-heartbeat`** — утилита из Percona Toolkit для измерения реального лага репликации на уровне приложения, не зависящая от `Seconds_Behind_Source`.
*   **Runbook (Ранбук)** — пошаговая инструкция для SRE/оператора по устранению конкретного сбоя репликации.

## Базовые концепции

### Диагностическая методология

При остановке репликации следуйте последовательности:

1.  **Сбор данных:** `SHOW REPLICA STATUS\G`, проверка логов MariaDB (`error.log`, `slow.log`), `SHOW PROCESSLIST`.
2.  **Классификация:** Определите, какой поток остановлен — I/O (связь с источником) или SQL (применение данных).
3.  **Анализ причины:** Проверьте сеть, диск, permissions, конфликты данных.
4.  **Восстановление:** Выберите минимально разрушающий способ: пропуск транзакции, повторная инициализация (re-seeding), или переключение на другой источник.

### Почему `Seconds_Behind_Source` может быть неточным?

Этот показатель часто вводит в заблуждение в следующих случаях:

1.  **Длительная транзакция:** Если запрос выполняется 3600 секунд, то в течение всего часа счетчик будет показывать 0, а по завершении — мгновенно прыгнет до 3600.
2.  **Параллельная репликация:** При использовании `slave_parallel_threads > 1` транзакции могут применяться не в строгом порядке записи. MariaDB вычисляет лаг на основе "самой старой" активной транзакции, что может приводить к ложным скачкам метрики.
3.  **Разрыв сети:** Если I/O Thread остановлен, значение будет `NULL` или 0, что не означает отсутствие лага. В этом случае используйте `pt-heartbeat` для истинного измерения.

### Parallel Replication (Параллельная репликация)

В MariaDB уникальные режимы параллелизма (`slave_parallel_mode`) описаны в [Обзор репликации](./overview.md). Для troubleshooting важно знать:

*   **`optimistic`** — при конфликте транзакция откатывается и выполняется последовательно. В `SHOW REPLICA STATUS` проверяйте `Last_SQL_Error` на наличие ошибок `Deadlock` или `Lock wait timeout`.
*   **`conservative`** — параллелизм только для явно сгруппированных транзакций (Group Commit). Подходит для сред с высокой контенцией.
*   **`aggressive`** — максимальный параллелизм, игнорирующий потенциальные конфликты. Рискованен при наличии триггеров Conflict Detection and Resolution в MariaDB Enterprise Server 12.3+.

---

## Практические сценарии

### Сценарий 1: Устранение критического лага

Если `Seconds_Behind_Source` растет непрерывно:

1.  **Проверьте состояние дисков и CPU:**
    ```bash
    # На реплике
    iostat -x 1 5
    vmstat 1 5
    ```

2.  **Определите узкое место:**
    ```sql
    SHOW REPLICA STATUS\G
    -- Обратите внимание на:
    -- Replica_IO_Running: Yes/No
    -- Replica_SQL_Running: Yes/No
    -- Relay_Log_Space: размер не применяемых данных
    ```

3.  **Если SQL Thread отстает — включите параллельную репликацию:**
    ```sql
    STOP REPLICA;
    SET GLOBAL slave_parallel_threads = 8;
    SET GLOBAL slave_parallel_mode = 'optimistic';
    START REPLICA;
    ```

4.  **Анализ блокировок:**
    ```sql
    SHOW PROCESSLIST;
    -- Ищите состояния: System lock, Waiting for table metadata lock, Locked
    ```

### Сценарий 2: Пропуск ошибок (Skip Error) в GTID-репликации

**Предупреждение:** Пропуск транзакций приводит к расхождению данных между источником и репликой. Используйте только после анализа причины и при отсутствии альтернатив.

**Для GTID-репликации (MariaDB 10.5+):**

```sql
-- 1. Остановите репликацию
STOP REPLICA;

-- 2. Определите проблемный GTID из SHOW REPLICA STATUS или performance_schema
SELECT * FROM performance_schema.replication_applier_status_by_worker;

-- 3. Запишите пустую транзакцию с тем же GTID
SET GTID_NEXT='0-1-12345';
BEGIN;
COMMIT;
SET GTID_NEXT='AUTOMATIC';

-- 4. Запустите репликацию
START REPLICA;
```

**Безопасная альтернатива (если ошибка не критична):**

```sql
-- В my.cnf на реплике (временно!)
slave_skip_errors = 1032,1062
-- После восстановления удалите параметр и перезапустите репликацию
```

### Сценарий 3: Восстановление после повреждения Relay Log

```sql
-- 1. Остановите репликацию
STOP REPLICA;

-- 2. Сбросьте relay log (реплика перекачает заново)
RESET REPLICA;

-- 3. Запустите репликацию
START REPLICA;
```

**Примечание:** `RESET REPLICA` сбрасывает `relay_log_info_repository` и `gtid_slave_pos`. Убедитесь, что `SOURCE_USE_GTID=slave_pos` настроен, чтобы реплика автоматически нашла правильную позицию.

### Сценарий 4: Ошибка `Error 1236` — источник удалил нужные binlog-файлы

```sql
-- На источнике: проверьте текущий binlog
SHOW MASTER STATUS;

-- На реплике: проверьте требуемую позицию
SHOW REPLICA STATUS\G
-- Last_IO_Errno: 1236
-- Last_IO_Error: Got fatal error 1236 from master ...
```

**Решение:**

1.  Увеличьте `binlog_expire_logs_seconds` на источнике (больше максимального лага реплики).
2.  Пересоздайте реплику с текущим дампом (re-seeding).

### Сценарий 5: Сетевая проблема `Error 2003`

```sql
-- На реплике: проверка соединения
mysql -h source_host -P 3306 -u repl_user -p
```

**Решение:**

1.  Проверьте firewall на источнике: `iptables -L -n` или `firewall-cmd --list-all`.
2.  Проверьте `bind-address` на источнике: должен быть `0.0.0.0` или конкретный IP, а не `127.0.0.1`.
3.  Проверьте `skip_name_resolve = ON` на источнике (если используется IP в `GRANT`).

### Сценарий 6: Ошибка `Error 1045` — доступ запрещен

```sql
-- На источнике: проверка пользователя
SELECT user, host FROM mysql.user WHERE user='repl_user';

-- Проверка grants
SHOW GRANTS FOR 'repl_user'@'192.168.1.%';
```

**Решение:**

1.  Убедитесь, что хост в `GRANT` совпадает с IP реплики.
2.  Проверьте, что пользователь создан с `IDENTIFIED BY` и не истек пароль.
3.  При использовании `caching_sha2_password` убедитесь, что клиентская библиотека поддерживает его.

---

## Глубокая диагностика (SRE Toolset)

### Анализ Relay Log

```bash
# Декодирование событий в human-readable виде
mariadb-binlog --base64-output=DECODE-ROWS -v /var/log/mysql/relay-bin.000001 | less

# Поиск конкретного времени
mariadb-binlog --start-datetime="2025-01-01 10:00:00" \
               --stop-datetime="2025-01-01 11:00:00" \
               /var/log/mysql/relay-bin.000001
```

### Анализ Performance Schema

```sql
-- Статус соединения репликации
SELECT * FROM performance_schema.replication_connection_status\G

-- Статус каждого воркера (параллельная репликация)
SELECT * FROM performance_schema.replication_applier_status_by_worker\G

-- Координатор параллельной репликации
SELECT * FROM performance_schema.replication_applier_status_by_coordinator\G
```

### Мониторинг GTID Lag

```sql
-- На источнике
SELECT @@GLOBAL.gtid_binlog_pos;

-- На реплике
SELECT @@GLOBAL.gtid_slave_pos;

-- Разница дает точный объем не примененных данных
```

### pt-heartbeat для истинного лага

```bash
# На источнике: создание heartbeat таблицы и демон
pt-heartbeat --update --database heartbeat --create-table --daemonize \
    --user=monitor --password=secret

# На мониторинге: проверка лага
pt-heartbeat --monitor --database heartbeat --master-server-id=1 \
    --user=monitor --password=secret
```

### Проверка консистентности данных

```bash
# Безопасная проверка на реплике (не влияет на источник)
pt-table-checksum --replicate=percona.checksums \
    --host=source_ip \
    --user=monitor_user \
    --password=monitor_password
```

---

## Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Error 1236: master has purged binary logs` | Реплика слишком долго была отключена; источник удалил binlog-файлы, нужные реплике. | Пересоздание снимка данных (re-seeding). Увеличьте `binlog_expire_logs_seconds`. |
| `Error 2003: Can't connect to MySQL server` | Сетевая проблема или неправильный хост. | Проверьте firewall, порт 3306, `bind-address` на источнике, `skip_name_resolve`. |
| `Error 1045: Access denied for user` | Неправильный логин/пароль или хост. | Проверьте учетные данные, IP в `GRANT`, поддержку `caching_sha2_password`. |
| `Error 1062: Duplicate entry` | Попытка записать данные, которые уже есть (ручная запись на реплику или дублирование GTID). | Удалите строку на реплике или пропустите транзакцию через GTID skip. |
| `Error 1032: Can't find record` | На источнике удалили/обновили строку, которой нет на реплике. | Восстановите строку на реплике или используйте `slave_skip_errors = 1032` (рискованно). |
| `Relay log read failure` | Повреждение файла Relay Log на диске. | `STOP REPLICA; RESET REPLICA; START REPLICA;` — реплика перекачает логи заново. |
| `Replica_SQL_Running: No` | Ошибка при применении транзакции. | Проверьте `Last_SQL_Error`; возможно, потребуется пропуск или исправление данных. |
| `Replica_IO_Running: No` | Проблема с соединением с источником. | Проверьте сеть, пользователя, SSL, `Last_IO_Error`. |
| `Seconds_Behind_Source: NULL` | I/O Thread остановлен или не запущен. | Проверьте `Replica_IO_Running`, сетевую доступность источника. |

### Типовые ограничения и Edge Cases

1.  **Несоответствие версий:** Источник должен быть такой же или более новой версии, чем реплика. При репликации с MySQL на MariaDB убедитесь в совместимости формата binlog и GTID (прямая репликация невозможна; требуется логическая миграция через `mariadb-dump`).
2.  **Смена `binlog_format`:** Переключение с SBR на RBR требует перезапуска репликации или сброса позиции. GTID-репликация чувствительна к формату binlog на источнике.
3.  **Параллельная репликация и триггеры:** Режим `aggressive` несовместим с триггерами Conflict Detection and Resolution в MariaDB Enterprise Server 12.3+.
4.  **Полусинхронная репликация:** При недоступности реплик источник через таймаут переходит в асинхронный режим. Убедитесь, что `rpl_semi_sync_master_timeout` настроен адекватно вашим SLA.
5.  **Multi-source и уникальные `server_id`:** Все источники в топологии multi-source должны иметь уникальные `server_id`. Дублирование приведет к непредсказуемому поведению GTID.
6.  **Диссинхронизация времени:** NTP-сдвиг между источником и репликой > 1 секунды может вызывать ложные срабатывания таймаутов и искажать `Seconds_Behind_Source`. Настройте chrony или systemd-timesyncd на всех узлах.
7.  **Заполнение диска:** Полное заполнение диска на реплике останавливает SQL Thread. Мониторьте свободное место и настройте `binlog_expire_logs_seconds` на источнике.
8.  **Фильтрация репликации и Error 1032:** При использовании `replicate-ignore-db` или `replicate-wild-ignore-table` на реплике удаление строк на источнике для игнорируемой базы может вызывать `Error 1032`. Подробнее см. [Фильтрация репликации](./filtering.md).

---

## Best Practices

1.  **Всегда проверяйте `SHOW REPLICA STATUS\G`** при проблемах. Это первая и главная команда диагностики.
2.  **Не полагайтесь только на `Seconds_Behind_Source`.** Используйте `pt-heartbeat` или GTID-позиции для точного измерения лага.
3.  **Настраивайте алерты на `Replica_IO_Running: No` и `Replica_SQL_Running: No`** — это признаки остановки репликации.
4.  **Используйте GTID** — он упрощает диагностику и восстановление. С MariaDB 10.10 GTID включен по умолчанию для новых инсталляций.
5.  **Включайте `gtid_strict_mode = ON`** для защиты от дублирования транзакций при пропуске ошибок.
6.  **Настройте crash-safe replication** (`relay_log_recovery = ON`, `relay_log_info_repository = TABLE`) для автоматического восстановления после сбоев.
7.  **Регулярно проверяйте консистентность данных** с помощью `pt-table-checksum` из Percona Toolkit.
8.  **Ведите runbook** для типовых сценариев: Error 1236, Error 2003, Error 1062, relay log corruption.
9.  **Мониторьте disk space и NTP** на всех узлах репликации.
10. **Для пропуска транзакций используйте GTID-метод** (`SET GTID_NEXT`), а не `sql_slave_skip_counter` — он deprecated и не работает с GTID.

---

## Дополнительная информация

### См. также

- **[Обзор репликации](./overview.md)** — архитектура потоков и журналов.
- **[Настройка репликации](./setup_guide.md)** — параметры параллелизма и crash-safe replication в `my.cnf`.
- **[Фильтрация в репликации](./filtering.md)** — влияние фильтров на ошибки 1032 и 1062.
- **[Отложенная репликация](./delayed_replication.md)** — `SOURCE_DELAY`, откат ошибочных изменений.
- **[Топологии](./topologies.md)** — каскадная, кольцевая, multi-master.
- **[Split-brain и fencing](./split_brain_fencing.md)** — защита от двойной записи.
- **[Управление Relay Log](./relay_log_management.md)** — `relay_log_space_limit`, повреждение relay log.
- **[Проверка консистентности](./data_consistency.md)** — `pt-table-checksum` / `pt-table-sync`.
- **[Ручной Switchover](./switchover.md)** — плановое переключение.
- **[Мониторинг репликации](./monitoring.md)** — Prometheus, алерты, измерение лага.
- **[Привилегии](./replication_privileges.md)** — `REPLICATION SLAVE ADMIN`.
- **[Capacity Planning](./capacity_planning.md)** — sizing ресурсов.
- **[Операционные сценарии](./operational_scenarios.md)** — большие транзакции, DDL, WAN.
- **[Собеседование](./interview_questions.md)** — вопросы и ответы.
- **[Сценарии использования](./replication_use_cases.md)** — read scaling, бэкап, DR.
- **[Бинарное логирование](../security/binary-logging.md)** — `Error 1236`, настройка `binlog_expire_logs_seconds`.
- **[Percona Toolkit Documentation](https://www.percona.com/software/database-tools/percona-toolkit)** — `pt-table-checksum`, `pt-heartbeat`, `pt-query-digest`.
