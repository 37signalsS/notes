# Резервное копирование и восстановление в MariaDB

Специфичные для MariaDB инструменты и стратегии. Общие теоретические основы (логические/физические, горячие/холодные бэкапы) описаны в руководстве **[Стратегии резервного копирования баз данных](../Concepts/backups.md)**.

## Определения

**`mariadb-backup`** — основной инструмент для создания «горячих» **физических** бэкапов. Является форком Percona XtraBackup, полностью адаптированным под архитектуру MariaDB (включая MyRocks, Aria и новые бинарные логи InnoDB).

**`mariadb-dump`** — стандартная утилита для создания **логических** резервных копий (SQL-дампов). Подходит для небольших БД или когда требуется перенос данных между разными версиями/форками.

**`mydumper` / `myloader`** — высокопроизводительный инструмент для многопоточного логического бэкапа. Позволяет значительно ускорить процесс за счет параллельного выполнения запросов к разным таблицам.

## Основные концепции

### Новое в 12.3 LTS: Бинарные логи в InnoDB

В версии MariaDB 12.3 введена возможность хранения бинарных логов непосредственно внутри движка InnoDB (`binlog_storage_engine=innodb`).
- **Надежность:** Исключает рассинхрон между данными и логом (атомарные транзакции).
- **Формат:** Логи имеют расширение `.ibb`.
- **PITR:** Восстановление на точку времени теперь полностью базируется на **GTID** (Global Transaction ID). Старый метод позиционирования по файлу и смещению (offset) в этом режиме не поддерживается.

### Стратегии физического бэкапа

1. **Full Backup:** Полная копия всех файлов данных.
2. **Incremental Backup:** Содержит только измененные страницы данных с момента предыдущего бэкапа (Full или Incremental).
3. **Partial Backup:** Копирование только определенных баз данных или таблиц (требует включенного `innodb_file_per_table`).

## Практические сценарии

### Сценарий 1: Многопоточный логический бэкап (mydumper)

Рекомендуется для БД объемом от 100 ГБ, где `mariadb-dump` становится слишком медленным.

```bash
# Бэкап в 8 потоков с компрессией
mydumper --user=root --password=pass --threads=8 --compress --build-empty-files \
         --outputdir=/data/backups/logical_$(date +%F)

# Восстановление (автоматически определяет количество потоков)
myloader --user=root --password=pass --directory=/data/backups/logical_2026-08-03
```

### Сценарий 2: Физический инкрементальный бэкап (mariadb-backup)

**1. Создание базового (Full) бэкапа:**
```bash
mariadb-backup --backup --target-dir=/data/backups/full \
               --user=backup_user --password=pass
```

**2. Создание первого инкрементального бэкапа:**
```bash
mariadb-backup --backup --target-dir=/data/backups/inc1 \
               --incremental-basedir=/data/backups/full
```

**3. Подготовка (Prepare) для восстановления:**
Сначала нужно «накатить» инкременты на базу.
```bash
# Подготовка базы (не завершаем транзакции, так как будут еще инкременты)
mariadb-backup --prepare --apply-log-only --target-dir=/data/backups/full

# Накат первого инкремента
mariadb-backup --prepare --apply-log-only --target-dir=/data/backups/full \
               --incremental-dir=/data/backups/inc1

# Финальная подготовка (завершаем транзакции)
mariadb-backup --prepare --target-dir=/data/backups/full
```

### Сценарий 3: Шифрование и сжатие бэкапов

Для экономии места и защиты данных в хранилище (например, S3):

```bash
# Бэкап со сжатием и шифрованием на лету
mariadb-backup --backup --stream=xbstream --compress \
               --encrypt=AES256 --encrypt-key-file=/etc/mysql/backup.key \
               --target-dir=/data/backups/secure_backup > backup.xbs
```

### Сценарий 4: Интеграция с S3 (Cloud Native)

Прямая передача бэкапа в облачное хранилище через конвейер (pipe):

```bash
mariadb-backup --backup --stream=xbstream | \
aws s3 cp - s3://my-db-backups/mariadb/$(date +%F)/backup.xbs
```

## Дополнительная информация

### Валидация и проверка целостности

Бэкап считается существующим только после успешной проверки:
1. **Prepare test:** Успешное выполнение фазы `--prepare` гарантирует, что redo-логи применимы.
2. **Checksum validation:** `mariadb-backup` автоматически проверяет контрольные суммы страниц при чтении.
3. **Restoration test:** Минимум раз в квартал рекомендуется восстанавливать бэкап на тестовый инстанс и запускать `mariadb-check`.

### Особенности для Galera Cluster

- Использование `mariadb-backup` является стандартом для метода **SST (State Snapshot Transfer)**.
- При создании бэкапа на узле Galera утилита сохраняет информацию о состоянии кластера в файл `xtrabackup_galera_info`.

### См. также
- **[Движки хранения MariaDB](storage_engines.md)** — особенности бэкапа MyRocks и Aria.
- **[Конфигурация MariaDB](configuration.md)** — настройка параметров логирования для PITR.
- **[Безопасность бэкапов](../Concepts/backup_security.md)** — общие принципы защиты резервных копий.
- **[Валидация бэкапов](../Concepts/backup_validation.md)** — методики автоматизированной проверки.
