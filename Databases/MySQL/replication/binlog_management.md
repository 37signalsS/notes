# Управление бинарными и ретрансляционными логами в MySQL

**Актуально для:** MySQL 5.1+ / 5.7 / 8.0+ / 8.4 LTS

## Определения

**Бинарный лог (Binary Log)** — последовательность файлов, содержащих события, изменяющие данные (DML) или структуру базы данных (DDL). Необходим для репликации и восстановления данных на определенный момент времени (**Point-in-Time Recovery — PITR**).

**Индексный файл (.index)** — текстовый файл, содержащий список всех актуальных бинарных (или ретрансляционных) логов. MySQL использует его для отслеживания цепочки файлов.

**Ретрансляционный лог (Relay Log)** — временный журнал на стороне реплики, содержащий события, полученные от источника, но еще не примененные к локальным данным. Служит буфером между сетью и диском.

**Point-in-Time Recovery (PITR)** — процедура восстановления базы данных до конкретного момента в прошлом путем наката транзакций из бинарных логов поверх восстановленного полного бэкапа.

## Предварительные требования

### Версии MySQL

- **Минимальная версия:** MySQL 5.1+ (включена поддержка binlog).
- **Рекомендуемая версия:** MySQL 8.0+ (надежность, `binlog_space_limit`, `binlog_transaction_compression`, `binlog_encryption`).
- **Совместимость:** Источник и реплика могут работать на разных минорных версиях в рамках одной major-версии. Для PITR убедитесь, что целевая версия может читать binlog-формат источника.

### Привилегии

- **`REPLICATION SLAVE`** — на реплике, для подключения к источнику и чтения binlog.
- **`REPLICATION CLIENT`** — для выполнения `SHOW BINARY LOGS`, `SHOW BINARY LOG STATUS` (в MySQL 5.7 и 8.0 — `SHOW MASTER STATUS`), `SHOW REPLICA STATUS`.
- **`FILE`** — для использования `mysqlbinlog` на хосте, где хранятся binlog-файлы.
- **`SUPER` / `SYSTEM_VARIABLES_ADMIN`** — для динамического изменения параметров binlog.
- **`RELOAD`** — для выполнения `FLUSH BINARY LOGS` и `PURGE BINARY LOGS`.

### Конфигурационные требования

- **Выделенный диск для binlog:** На источнике binlog должен размещаться на отдельном физическом устройстве или LVM-томе от данных и ОС.
- **Дисковое пространство:** Резервируйте место под 2–3 цикла ротации binlog сверх объема активных логов. Для PITR требуется место под все binlog за период хранения.
- **Сеть:** Для удаленного архивирования (`mysqlbinlog --read-from-remote-server`) обеспечьте стабильный канал между источником и хранилищем.
- **NTP:** Синхронизируйте время на всех узлах. Некорректные временные метки binlog ломают PITR и сравнение логов.

### Зависимости

- **Percona Toolkit** — `pt-table-checksum` для проверки консистентности данных, связанной с binlog.
- **Performance Schema** — для мониторинга compression stats и метрик репликации.
- **mysqlbinlog** — утилита входит в дистрибутив MySQL, требуется для PITR и анализа.

## Основные концепции

### Жизненный цикл бинарных логов (Source)

MySQL 8.0+ предоставляет автоматизированные механизмы контроля объема журналов:

- **Механизм ротации:** Новый файл создается при:
  - Достижении `max_binlog_size`.
  - Выполнении команды `FLUSH BINARY LOGS`.
  - Перезапуске сервера.
- **binlog_expire_logs_seconds:** Современный параметр (заменил `expire_logs_days`) для определения времени хранения файлов. По умолчанию 30 дней (2592000 сек). Очистка происходит при ротации файла.
- **binlog_space_limit:** (MySQL 8.0.21+) Жесткий лимит на суммарный объем всех файлов. Позволяет избежать переполнения диска путем принудительного удаления старых файлов даже если срок их хранения еще не истек.

### Жизненный цикл ретрансляционных логов (Replica)

Настройка хранения Relay Log критична для стабильности реплики:

- **relay_log_purge = ON:** (По умолчанию) Автоматическое удаление файлов Relay Log сразу после их успешного применения SQL-потоком. Если выключить, файлы будут копиться до заполнения диска.
- **relay_log_space_limit:** Общий лимит места для Relay Log. Если место заканчивается, I/O-поток останавливается до тех пор, пока SQL-поток не освободит пространство. Это защитный механизм, предотвращающий падение системы из-за лага.
- **relay_log_recovery = ON:** (Рекомендуется) Гарантирует целостность репликации после аварийного завершения. При запуске реплика отбрасывает существующие Relay Logs (так как они могли быть повреждены) и скачивает их заново с источника, ориентируясь на последнюю подтвержденную позицию в базе данных.

### Целостность и надежность

- **binlog_checksum = CRC32:** Добавление контрольной суммы к каждому событию. Позволяет обнаружить повреждение данных при чтении с диска или передаче по сети.
- **sync_binlog = 1:** Гарантирует сброс (fsync) лога на диск после каждой транзакции. Значение `0` позволяет ОС управлять буферизацией (выше скорость, ниже надежность). Значение `N > 1` сбрасывает данные раз в N транзакций.
- **binlog_encryption = ON:** (MySQL 8.0.14+) Прозрачное шифрование логов на диске. Требует настроенного Keyring.
- **binlog_transaction_compression = ON:** (MySQL 8.0.20+) Сжатие транзакций по алгоритму ZSTD. Сжимаются только данные в формате ROW, что дает колоссальную экономию места (до 90%).

## Практические сценарии

### 1. Мониторинг состояния и места

Для оценки объема логов и эффективности сжатия используйте следующие запросы:

```sql
-- Общий размер всех бинарных логов
SHOW BINARY LOGS;
-- → Всего файлов: N, Общий размер: X байт

-- Эффективность сжатия транзакций (MySQL 8.0.20+).
-- Группировка по LOG_TYPE и COMPRESSION_TYPE обязательна: строки различаются
-- типом лога (binlog или relay log) и способом сжатия, NONE означает "не сжималось".
SELECT 
    LOG_TYPE, 
    COMPRESSION_TYPE,
    TRANSACTION_COUNTER, 
    COMPRESSED_BYTES, 
    UNCOMPRESSED_BYTES, 
    COMPRESSION_PERCENTAGE 
FROM performance_schema.binary_log_transaction_compression_stats;
```

### 2. Удаленное резервное копирование (Binary Log Archiving)

Утилита `mysqlbinlog` может работать в режиме фонового процесса для непрерывного скачивания логов. Это защищает от потери данных при полном уничтожении диска на источнике.

```bash
# Запуск в режиме "демона" (stop-never)
mysqlbinlog --read-from-remote-server \
            --host=source_db \
            --user=backup_user \
            --raw \
            --stop-never \
            --result-file=/var/lib/mysql-backups/binlog \
            mysql-bin.000001 &
```
*Совет: Для `backup_user` достаточно прав `REPLICATION SLAVE`.*

### 3. Продвинутая процедура PITR

Если база данных была повреждена (например, в 10:05 был выполнен `DROP DATABASE`), следуйте алгоритму:

1.  **Поиск точки восстановления:**
    ```bash
    mysqlbinlog -v --base64-output=DECODE-ROWS /var/lib/mysql/binlog.000124 | grep -B 5 "DROP DATABASE"
    ```
2.  **Восстановление из бэкапа:** Подготовьте чистый инстанс MySQL и разверните последний полный физический или логический бэкап.
3.  **Накат логов (Roll-forward):**
    ```bash
    # Объединение нескольких логов и применение до временной метки
    mysqlbinlog --stop-datetime="2024-08-03 10:04:55" \
        /backup/binlogs/binlog.000120 \
        /backup/binlogs/binlog.000121 \
        /backup/binlogs/binlog.000122 \
        /backup/binlogs/binlog.000123 \
        /backup/binlogs/binlog.000124 | mysql -u root -p
    ```

### 4. Решение проблемы переполнения диска (Disk Full)

**Ситуация:** Диск на источнике заполнен бинарными логами на 100%, MySQL не принимает запись.

**Действия:**
1.  Увеличьте место (LVM resize) или временно подключите сетевой диск.
2.  Если расширение невозможно — **удалите старые логи правильно**:
    - Проверьте текущий `binlog_expire_logs_seconds`. Уменьшите его временно: `SET GLOBAL binlog_expire_logs_seconds = 86400;` (1 день).
    - Выполните `FLUSH BINARY LOGS;` — это спровоцирует автоматическую очистку.
3.  Если автоматика не помогла — очистите вручную до определенного файла:
    `PURGE BINARY LOGS TO 'mysql-bin.000050';`
    *Внимание: убедитесь, что реплики уже скачали эти файлы!*

## Валидация

### Статус и конфигурация binlog

```sql
-- Проверка включения binlog и пути
SHOW VARIABLES LIKE 'log_bin';
SHOW VARIABLES LIKE 'log_bin_basename';
SHOW VARIABLES LIKE 'binlog_format';
SHOW VARIABLES LIKE 'binlog_expire_logs_seconds';
SHOW VARIABLES LIKE 'max_binlog_size';
SHOW VARIABLES LIKE 'binlog_space_limit';

-- Список активных бинарных логов
SHOW BINARY LOGS;
```

### Проверка целостности binlog

```bash
# Проверка контрольных sums всех событий в файле
mysqlbinlog --verify-binlog-checksum /var/lib/mysql/binlog.000001

# Декодирование событий ROW-формата для ручной инспекции
mysqlbinlog -v --base64-output=DECODE-ROWS /var/lib/mysql/binlog.000001 | less
```

### Мониторинг места и роста

```sql
-- Список binlog-файлов и их размеров
SHOW BINARY LOGS;
-- Поля вывода: Log_name, File_size, Encrypted

-- Почему нельзя через information_schema.files:
--   * столбца file_size у этой таблицы нет — размер файла считается как
--     TOTAL_EXTENTS * EXTENT_SIZE, то есть речь об extents InnoDB/NDB, а не о binlog;
--   * file_type для InnoDB принимает только значения TABLESPACE, TEMPORARY, UNDO LOG,
--     а для NDB — UNDO LOG или DATAFILE. Значения 'BINARY LOG' в ней не бывает,
--     поэтому фильтр WHERE file_type = 'BINARY LOG' всегда вернёт пустой результат.

-- Мониторинг через Performance Schema (MySQL 8.0.20+).
-- Строки сгруппированы по типу лога (LOG_TYPE) и способу сжатия (COMPRESSION_TYPE);
-- при COMPRESSION_TYPE = NONE сжатых транзакций нет, а отношение считается некорректно.
SELECT 
    LOG_TYPE,
    COMPRESSION_TYPE,
    TRANSACTION_COUNTER,
    COMPRESSED_BYTES,
    UNCOMPRESSED_BYTES,
    COMPRESSION_PERCENTAGE
FROM performance_schema.binary_log_transaction_compression_stats;
```

### Проверка консистентности между источником и репликой

```bash
# Сравнение checksum на источнике и реплике (Percona Toolkit)
pt-table-checksum --databases=prod_db --replicate=percona.checksums h=source_host

# Проверка расхождений на реплике
pt-table-sync --replicate=percona.checksums h=replica_host --print
```

## Устранение неисправностей

### Отказ в записи из-за заполнения диска (No space left on device)

- **Симптом:** `ERROR 31 (HY000): Can't create/write to file ... (Errcode: 28 - No space left on device)`.
- **Причина:** `binlog_space_limit` или файловая система достигла лимита.
- **Решение:**
  1. Проверьте место: `df -h /var/lib/mysql`.
  2. Временно уменьшите `binlog_expire_logs_seconds`: `SET GLOBAL binlog_expire_logs_seconds = 86400;`.
  3. Принудительно завершите ротацию: `FLUSH BINARY LOGS;`.
  4. Для экстренного освобождения: `PURGE BINARY LOGS TO 'mysql-bin.0000XX';` (убедитесь, что реплики получили файлы).

### Повреждение binlog (Checksum failure)

- **Симптом:** `mysqlbinlog --verify-binlog-checksum` завершается с ошибкой, или реплика падает с ошибкой 1236.
- **Причина:** Аварийное завершение сервера, сбой диска, бит-рот.
- **Решение:**
  1. На источнике: `mysqlbinlog --verify-binlog-checksum /path/to/binlog.XXXXX`.
  2. Если файл поврежден — пропустите его: `PURGE BINARY LOGS TO 'mysql-bin.0000XX';` (если реплики не требуют этот файл).
  3. Проверьте файловую систему: `fsck` или `smartctl`.
  4. Включите `binlog_checksum = CRC32` для предотвращения будущих проблем.

### Ошибка прав доступа при создании binlog

- **Симптом:** `Can't create/write to file ... (Errcode: 13 - Permission denied)`.
- **Причина:** MySQL не имеет прав на запись в директорию binlog.
- **Решение:**
  1. Проверьте ownership: `ls -la /var/lib/mysql-binlog/`.
  2. Исправьте права: `chown -R mysql:mysql /var/lib/mysql-binlog && chmod 700 /var/lib/mysql-binlog`.
  3. Убедитесь, что `log_bin_basename` указывает на существующую директорию.

### Ротация не происходит автоматически

- **Симптом:** Binlog-файлы растут, несмотря на настроенный `binlog_expire_logs_seconds`.
- **Причина:** Нет активных транзакций для запуска ротации; `FLUSH BINARY LOGS` не вызывался.
- **Решение:**
  1. Выполните `FLUSH BINARY LOGS;` для принудительной ротации.
  2. Проверьте `binlog_space_limit`: если достигнут, старые файлы удаляются при следующей ротации.
  3. Убедитесь, что `log_bin` включен: `SHOW VARIABLES LIKE 'log_bin';`.

### Резкий рост binlog после включения compression

- **Симптом:** После включения `binlog_transaction_compression = ON` размер binlog не уменьшается.
- **Причина:** Сжатие работает только для формата `ROW`. В режиме `STATEMENT` или `MIXED` события не сжимаются.
- **Решение:**
  1. Проверьте формат: `SHOW VARIABLES LIKE 'binlog_format';`.
  2. Переключитесь на `ROW`: `SET GLOBAL binlog_format = 'ROW';` (требуется перезапуск приложения для новых подключений).
  3. Проверьте статистику сжатия: `SELECT * FROM performance_schema.binary_log_transaction_compression_stats;`.

### Проблемы с шифрованием binlog

- **Симптом:** `binlog_encryption` включен, но сервер не стартует или реплика не может читать binlog.
- **Причина:** Keyring не настроен или ключ недоступен.
- **Решение:**
  1. Проверьте статус keyring: `SHOW STATUS LIKE 'Keyring_%';`.
  2. Убедитесь, что `early-plugin-load` загружает `keyring_file` или `keyring_encrypted_file`.
  3. Для существующих незашифрованных binlog: отключите encryption, выполните ротацию, затем включите заново.

## Рекомендации

### Мониторинг и алертинг

- **Ключевые метрики:**
  - Размер директории binlog: `du -sh /var/lib/mysql-binlog/`.
  - Количество файлов: `SHOW BINARY LOGS;` + `wc -l`.
  - Скорость роста: мониторьте изменение размера за час.
  - `binlog_space_usage` — заполнение диска binlog на источнике.
- **Частота проверок:** Ежедневно для production, ежечасно для high-throughput систем.
- **Инструменты:** Prometheus node_exporter (дисковое место), Percona Monitoring and Management (PMM), собственные скрипты на bash/python.

### Жесткое обеспечение безопасности

- **Изоляция диска:** Всегда выносите binlog на отдельный раздел (например, `/var/lib/mysql-binlog`). Это гарантирует, что переполнение логов не заблокирует работу ОС или системного раздела БД.
- **Relay Log Space:** На репликах с высокой нагрузкой всегда ограничивайте `relay_log_space_limit` (например, 10–20 ГБ), чтобы SQL-лаг не привел к "смерти" диска реплики.
- **Шифрование:** Включите `binlog_encryption = ON` для чувствительных данных. Убедитесь, что keyring backup производится регулярно.
- **Права доступа:** Директория binlog должна принадлежать `mysql:mysql` с правами `700`. Пользователь `backup_user` должен иметь только `REPLICATION SLAVE`.

### Процедурные рекомендации

- **Ротация:** Настраивайте `binlog_expire_logs_seconds` не менее чем на 72 часа (259200 сек) для поддержки PITR. Для систем с долгими простоями реплик увеличивайте до 7 дней.
- **Компрессия:** Включите `binlog_transaction_compression = ON` на высоконагруженных инстансах с форматом `ROW`. Экономия места достигает 90%.
- **Резервное копирование:** Настройте удаленное архивирование через `mysqlbinlog --read-from-remote-server --stop-never` для критичных систем.
- **Тестирование PITR:** Регулярно проводите drills восстановления на тестовом инстансе. Документируйте среднее время восстановления (RTO).
- **Инвалидация кэша:** После выполнения PITR не забудьте сбросить кэши приложений и прогреть буферный пул (`buffer_pool`), так как производительность будет временно снижена.

### Автоматизация

```bash
# Пример скрипта проверки места под binlog
#!/bin/bash
THRESHOLD=90
CURRENT=$(df -h /var/lib/mysql-binlog | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$CURRENT" -gt "$THRESHOLD" ]; then
    echo "ALERT: Binlog disk usage at ${CURRENT}%"
    mysql -e "SET GLOBAL binlog_expire_logs_seconds = 86400; FLUSH BINARY LOGS;"
    # Уведомление в monitoring system
fi
```

### Настройка для production

- **`binlog_format = ROW`** — повсеместно. `STATEMENT` допустим только в изолированных read-only сценариях без репликации.
- **`binlog_checksum = CRC32`** — обязательно для detecting corruption.
- **`sync_binlog = 1`** — для максимальной надежности на источнике. На репликах можно установить `0` или `N > 1` для производительности.
- **`binlog_space_limit`** — включите на инстансах с ограниченным диском.
- **`relay_log_purge = ON`** — не отключайте на репликах.
- **`relay_log_recovery = ON`** — обязательно для crash-safety.

## Граничные случаи

### Очень большой объем binlog (> 1 ТБ)

- **Проблема:** Полная ротация или проверка `SHOW BINARY LOGS` занимает много времени.
- **Решение:**
  1. Используйте `PURGE BINARY LOGS BEFORE (NOW() - INTERVAL 7 DAY);` вместо удаления по имени файла.
  2. Увеличьте `max_binlog_size` до 1G для уменьшения количества файлов.
  3. Включите `binlog_transaction_compression = ON`.
  4. Рассмотрите разделение binlog на несколько директорий (MySQL 8.0.14+ поддерживает `log_bin_basename` с путями).

### PITR с репликами в отставании

- **Проблема:** Источник потерял binlog, а реплика еще не применила все транзакции.
- **Решение:**
  1. Проверьте `SHOW REPLICA STATUS` — `Relay_Master_Log_File` и `Exec_Master_Log_Pos`.
  2. Если binlog на источнике удален — восстановите реплику с полного бэкапа + binlog до точки сбоя.
  3. Для предотвращения: настройте `binlog_expire_logs_seconds` с запасом относительно максимального отставания реплик.

### Сжатый и зашифрованный binlog

- **Проблема:** `mysqlbinlog` не может декодировать события.
- **Решение:**
  1. Убедитесь, что `binlog_transaction_compression` выключен для старых файлов (они декодируются автоматически).
  2. Для зашифрованных файлов используйте тот же keyring, что и сервер: `mysqlbinlog --keyring-path=/var/lib/mysql-keyring/ ...`.
  3. Проверьте версию `mysqlbinlog` — она должна совпадать с версией сервера.

### Мультисорсная репликация и binlog

- **Проблема:** На реплике с несколькими каналами `SHOW BINARY LOGS` показывает только логи источника по умолчанию.
- **Решение:**
  1. Используйте `SHOW ALL BINARY LOGS` (MySQL 8.0.2+) для просмотра всех каналов.
  2. Для каждого канала настройте отдельный `relay_log_basename` для избежания конфликтов.

### Восстановление после потери всего binlog на источнике

- **Ситуация:** Диск на источнике уничтожен, полный бэкап есть, но binlog утеряны.
- **Решение:**
  1. Восстановите полный бэкап на новом инстансе.
  2. Если есть удаленный архив `mysqlbinlog --stop-never` — примените его.
  3. Если реплики доступны — используйте их binlog для продолжения PITR: `CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='...', SOURCE_LOG_POS=...;`.

## Очистка и откат

### Безопасная очистка старых binlog

```sql
-- Вариант 1: по времени (рекомендуется)
PURGE BINARY LOGS BEFORE (NOW() - INTERVAL 7 DAY);

-- Вариант 2: по имени файла (точный контроль)
PURGE BINARY LOGS TO 'mysql-bin.000050';

-- Проверка перед удалением
SHOW BINARY LOGS LIKE 'mysql-bin.0000%';
```

*Важно: Перед `PURGE` убедитесь, что все реплики получили эти файлы. Проверьте `SHOW REPLICA STATUS` → `Relay_Master_Log_File`.*

### Экстренное освобождение диска

```bash
# 1. Проверка места
df -h /var/lib/mysql

# 2. Временное уменьшение срока хранения
mysql -e "SET GLOBAL binlog_expire_logs_seconds = 86400;"

# 3. Принудительная ротация
mysql -e "FLUSH BINARY LOGS;"

# 4. Если не помогло — ручной purge (осторожно!)
mysql -e "PURGE BINARY LOGS TO 'mysql-bin.0000XX';"
```

### Откат конфигурации

Если изменение параметров binlog вызвало проблемы:

```sql
-- Откат binlog_format
SET GLOBAL binlog_format = 'ROW';

-- Откат binlog_checksum (если реплики не поддерживают CRC32)
SET GLOBAL binlog_checksum = 'OFF';

-- Откат сжатия
SET GLOBAL binlog_transaction_compression = OFF;

-- Откат шифрования (требует ротации)
SET GLOBAL binlog_encryption = OFF;
FLUSH BINARY LOGS;
```

### Полное удаление binlog

```bash
# Остановите MySQL
systemctl stop mysql

# Переименуйте директорию binlog
mv /var/lib/mysql-binlog /var/lib/mysql-binlog.bak

# Создайте новую пустую директорию
mkdir -p /var/lib/mysql-binlog
chown mysql:mysql /var/lib/mysql-binlog

# Запустите MySQL (создаст новый binlog с нуля)
systemctl start mysql

# Если нужно удалить старые файлы полностью
rm -rf /var/lib/mysql-binlog.bak
```

## Дополнительная информация

### Рекомендации по безопасности и эксплуатации

- **Изоляция диска:** Всегда выносите бинлоги на отдельный раздел (например, `/var/lib/mysql-binlog`). Это гарантирует, что переполнение логов не заблокирует работу ОС или системного раздела БД.
- **Relay Log Space:** На репликах с высокой нагрузкой всегда ограничивайте `relay_log_space_limit` (например, 10–20 ГБ), чтобы SQL-лаг не привел к "смерти" диска реплики.
- **Инвалидация кэша:** После выполнения PITR не забудьте сбросить кэши приложений и прогреть буферный пул (`buffer_pool`), так как производительность будет временно снижена.

### См. также

- **[Обзор репликации MySQL](./overview.md)** — архитектура, топологии и выбор формата binlog.
- **[Настройка репликации MySQL](./setup_guide.md)** — пошаговое руководство по развертыванию с параметрами binlog.
- **[Механизм работы репликации](./master_slave_mechanism.md)** — детальное описание Binlog Dump, сетевой передачи и применения событий.
- **[Форматы бинарного лога](./binlog_formats.md)** — влияние ROW/STATEMENT/MIXED на размер, надежность и PITR.
- **[GTID-репликация](./gtid.md)** — взаимодействие GTID с binlog, ошибка 1236, продвинутый PITR.
- **[Управление и отладка репликации](./management_debug.md)** — диагностика поврежденных Relay логов, мониторинг лага, сетевые ошибки.
