# Автоматизация резервного копирования PostgreSQL

**Актуально для:** PostgreSQL 14–18; pgBackRest 2.59.x, Barman 3.20.x

## Определения

**Автоматизация бэкапов** — системный процесс создания, сжатия, шифрования, транспортировки и верификации резервных копий без участия оператора. В PostgreSQL автоматизация реализуется на двух уровнях:

- **Логический уровень:** Генерация SQL-дампов или структурированных архивов (`pg_dump`). Подходит для малых БД (< 100 ГБ), выборочного восстановления и миграций между версиями.
- **Физический уровень:** Прямое копирование файлов данных и архивация журналов транзакций (WAL) с помощью специализированных инструментов (`pgBackRest`, `Barman`, `pg_basebackup`). Поддерживает инкрементальные копии и восстановление на момент времени (PITR).

**Жизненный цикл бэкапа (Automation Lifecycle):**
1. **Триггер:** Запуск по расписанию (Cron, Systemd Timer) или событию.
2. **Выполнение:** Создание консистентной копии.
3. **Обработка:** Сжатие и опциональное шифрование.
4. **Транспортировка:** Копирование в отдельное хранилище (локальный диск, NFS, второй хост — off-site).
5. **Верификация:** Проверка целостности и пробное восстановление.
6. **Ротация (Retention):** Удаление устаревших копий согласно политике хранения.
7. **Оповещение:** Отправка статуса выполнения в систему мониторинга.

## Предпосылки

Для корректной работы автоматизации необходимо подготовить окружение:

1.  **Выделенная роль:** Роль с минимально необходимыми правами.
    - Для `pg_dump`: `pg_read_all_data` (PG 14+).
    - Для физических бэкапов: `pg_monitor` и права на чтение файлов данных в ОС (для `pg_basebackup` достаточно `REPLICATION` + `pg_read_all_data`).
    - См. подробнее: **[Управление ролями и правами доступа (RBAC)](./role_management.md)**.
2.  **Аутентификация:** Файл `~/.pgpass` для исключения передачи пароля в командной строке.
    ```text
    # формат: hostname:port:database:username:password
    db.example.com:5432:*:backup_user:super_secret_password
    ```
    *Права на файл должны быть `0600`.*
3.  **Хранилище:** Выделенное место на диске, NFS-монтирование или отдельный backup-сервер. Объём — минимум 2× размер БД для полного физического бэкапа плюс архив WAL.
4.  **Сетевой доступ:** Разрешение подключений в `pg_hba.conf` для пользователя бэкапа (`hostssl` вместо `host`, где возможно).
5.  **Блокировка наложения:** Механизм `flock` или эквивалент, чтобы новый запуск не начался, пока предыдущий не завершился.

## Основные концепции

### Выбор стратегии автоматизации

| Инструмент | Уровень | Хранилище | Особенности |
| :--- | :--- | :--- | :--- |
| **Shell + Systemd Timer/Cron** | Логический | Локальный диск / NFS | Простота, полный контроль, подходит для небольших изолированных инстансов. |
| **pgBackRest** | Физический | Локальный/NFS-репозиторий, второй хост | **Золотой стандарт**. Параллелизм, инкрементальные/дифференциальные бэкапы, дельта-восстановление, встроенная проверка целостности. |
| **Barman** | Физический | Диск / NFS | Централизованный менеджер для управления множеством серверов БД с одного узла. |

### Архитектура автоматизации

1. **Планировщик (Scheduler):** `Cron` или `Systemd Timers` на стороне сервера БД или отдельного хоста управления. pgBackRest **не имеет встроенного планировщика** — его запускают из cron или systemd timer.
2. **Исполнитель (Runner):** Скрипт или утилита, вызывающая средства копирования.
3. **Хранилище (Storage):** Разделение на «горячее» (локальное для быстрого отката) и «холодное» (off-site, второй хост/здание для DR).
4. **Мониторинг:** Внешний сервис, проверяющий свежесть бэкапа (Dead Man's Snitch).

### Systemd Timer vs Cron

**Таймеры systemd предпочтительнее cron** для бэкапов, потому что:
- Логи попадают в `journald` (`journalctl -u pg-backup.service`) без перенаправления в файл.
- `Persistent=true` догоняет пропущенный запуск после простоя хоста.
- `RandomizedSecs` размазывает нагрузку при множестве таймеров.
- Единая точка управления (`systemctl list-timers`) и зависимости через `After=`/`Requires=`.

**Обязательная защита от наложения:** ни cron, ни timer не гарантируют, что предыдущий запуск завершился. Длинный бэкап + каждые-сутки-расписание = перекрытие. Решение — `flock` на файл-блокировку (см. сценарий 1).

## Практические сценарии

### Сценарий 1: Логический бэкап с шифрованием, предпроверками и ротацией

Подходит для небольших баз, где важна простота восстановления одной таблицы.

**Скрипт `/usr/local/bin/pg_backup_logical.sh`:**
```bash
#!/bin/bash
set -eo pipefail

# Защита от наложения запусков
exec 9>/var/run/pg_backup.lock || exit 1
flock -n 9 || { echo "ERROR: backup already running" >&2; exit 1; }

# Конфигурация
DB_NAME="production_db"
BACKUP_DIR="/mnt/backups/postgres/logical"
KEEP_DAYS=14
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Предпроверки: место (порог 90% занятости) и состояние архивации WAL
df -h "$BACKUP_DIR" | awk 'NR==2 {exit ($5+0 > 90)}'
[ "$(psql -Atqc "SELECT failed_count FROM pg_stat_archiver")" = "0" ]

# Дамп -> шифрование (GPG); set -o pipefail ловит провал любого звена цепочки
pg_dump -U backup_user -d "$DB_NAME" -F c --compress=zstd:3 \
  -f "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"
gpg --batch --yes --encrypt --recipient "backup-key@example.com" \
  -o "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump.gpg" \
  "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"
rm -f "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"

# Глобальные объекты (роли, табличные пространства) — один раз в сутки
pg_dumpall -U backup_user -g | \
  gpg --batch --yes --encrypt --recipient "backup-key@example.com" \
  -o "$BACKUP_DIR/globals_${TIMESTAMP}.sql.gpg"

# Ротация
find "$BACKUP_DIR" -type f -name "*.gpg" -mtime +"$KEEP_DAYS" -delete

echo "Backup completed: ${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.dump.gpg"
# → результат: файл production_db_20260817_020000.dump.gpg создан и зашифрован
```

**Запуск по cron (от пользователя `postgres`):**
```cron
# /etc/cron.d/pg-logical-backup
0 2 * * * postgres /usr/local/bin/pg_backup_logical.sh >> /var/log/pg_backup.log 2>&1
```

**Примечания:**
- `--compress=zstd:3` доступен в `pg_dump` с PostgreSQL 15 (в 14 — только gzip).
- `pg_dumpall -g` выгружает только глобальные объекты; без него дамп не восстановит роли и tablespaces. Подробнее: **[Теория бэкапов и восстановления](../Concepts/backup_and_recovery.md)**.
- Ключ `-F c` (custom format) даёт сжатие и выборочное восстановление через `pg_restore`.

### Сценарий 2: Физическая автоматизация через pgBackRest

Рекомендуется для Production-сред любого масштаба.

**Конфигурация `/etc/pgbackrest/pgbackrest.conf`:**
```ini
[global]
repo1-path=/var/lib/pgbackrest
repo1-retention-full=2          # Хранить 2 полных бэкапа
process-max=4                   # Параллелизм (4 ядра)
log-level-console=info

[main]
pg1-path=/var/lib/postgresql/16/main
```

**Инициализация и проверка конфигурации (однократно):**
```bash
# Создание stanza — обязательно перед первым бэкапом
pgbackrest --stanza=main stanza-create

# Проверка: pgBackRest валидирует archive_command и доступ к репозиторию
pgbackrest --stanza=main check
# → результат: "check repo1: successful" + "check stanza main: successful"
```

**Выполнение бэкапа:**
```bash
# Явный тип: full | incremental | differential
pgbackrest --stanza=main backup --type=incr

# Без --type pgBackRest выбирает тип автоматически:
# full — если нет полной копии, иначе incremental
pgbackrest --stanza=main backup

# Ротация сразу после успешного бэкапа
pgbackrest --stanza=main backup --expire-auto
```

**Автоматизация через Systemd Timer (пара service + timer):**
```ini
# /etc/systemd/system/pgbackrest-backup.service
[Unit]
Description=pgBackRest incremental backup

[Service]
Type=oneshot
User=postgres
ExecStart=/usr/bin/pgbackrest --stanza=main backup --type=incr --expire-auto
```
```ini
# /etc/systemd/system/pgbackrest-backup.timer
[Unit]
Description=Daily pgBackRest Full Backup

[Timer]
OnCalendar=daily
Persistent=true
RandomizedSecs=30m

[Install]
WantedBy=timers.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now pgbackrest-backup.timer
systemctl list-timers pgbackrest-backup.timer
# → результат: timer в списке со следующим запуском
```

**Особенности эксплуатации (важно для sysadmin):**
- **Только команда `restore` по умолчанию может запускаться от root**; для остальных команд от root требуется `--allow-root` (не рекомендуется).
- **Локальная и удалённая (backup/repo host) версии pgBackRest должны совпадать** — иначе возможна несовместимость репозитория.
- С версии 2.58.0 требуется TLS >= 1.2 для хранилищ.
- `--backup-standby` — бэкап со standby-реплики, чтобы не нагружать primary.
- Поддерживает 10 версий PostgreSQL: 5 актуальных + 5 EOL.

### Сценарий 3: Физический бэкап на диск через `pg_basebackup` с верификацией и GFS-ротацией

Минималистичная альтернатива без сторонних пакетов — полный контроль над механикой.

**Скрипт `/usr/local/bin/pg_backup_base.sh`:**
```bash
#!/bin/bash
set -eo pipefail

exec 9>/var/run/pg_basebackup.lock || exit 1
flock -n 9 || { echo "ERROR: backup already running" >&2; exit 1; }

DEST_ROOT="/mnt/backups/base"
DEST="${DEST_ROOT}/$(date +%Y%m%d_%H%M%S)"
KEEP_DAILY=7
KEEP_WEEKLY=4
KEEP_MONTHLY=12

mkdir -p "$DEST"

# -Fp  — plain format (директория с файлами)
# -X stream — WAL потоком: не нужен archive_timeout, бэкап консистентен
# -c fast — быстрый checkpoint в начале
# --compress доступен только с PostgreSQL 18
pg_basebackup -h 127.0.0.1 -U backup_user -D "$DEST" -Fp -X stream -c fast

# Верификация целостности (создаётся автоматически backup_manifest с PG 13)
pg_verifybackup -e "$DEST"

echo "Base backup verified: $DEST"
```

**GFS-ротация (день/неделя/месяц):**
```bash
# Дневные: последние 7
find "$DEST_ROOT" -maxdepth 1 -type d -mtime +"$KEEP_DAILY" -exec rm -rf {} +

# Воскресные снимки сохраняем неделю, первое воскресенье месяца — месяц
# (реализуется через жёсткие ссылки: копия без удвоения места)
cp -al "$DEST" "${DEST_ROOT}/weekly_$(date +%G-W%V)" 2>/dev/null || true
```

**Запуск по timer:** ежедневно в 02:00 (`OnCalendar=*-*-* 02:00:00`).

**Примечания:**
- `pg_verifybackup` проверяет манифест, контрольные суммы файлов и наличие нужных WAL-записей — **без полного восстановления**.
- Проверка WAL-части **версионно-специфична**: используйте `pg_verifybackup` той же мажорной версии, что и проверяемый бэкап (проверка файлов данных работает на любой версии).
- `-X stream` делает архивацию WAL (`archive_mode`) необязательной для консистентности бэкапа, но PITR всё равно требует WAL-архив — см. **[Журнал предзаписи (WAL)](../../Concepts/write_ahead_log.md)**.

### Сценарий 4: Централизованное управление через Barman

Используется, если нужно управлять десятками серверов с одного узла.

**Конфигурация сервера в Barman (`/etc/barman.d/db-server.conf`):**
```ini
[db-server]
description = "Main Production DB"
conninfo = host=10.0.0.5 user=barman dbname=postgres
backup_method = postgres
archiver = on
retention_policy = RECOVERY WINDOW OF 4 WEEKS
```

**Типовой цикл эксплуатации:**
```bash
# Диагностика конфигурации до первого бэкапа
barman check db-server
# → результат: все проверки "OK" (ssh, conninfo, WAL archiving, retention)

# Запуск бэкапа
barman backup db-server

# Каталог и детали
barman list-backup db-server
barman show-backup db-server latest

# Тестовое восстановление в отдельный каталог
barman recover db-server latest /var/lib/pgsql/restore-test

# Архивная копия вне политики retention (перед опасными изменениями)
barman keep db-server <BACKUP_ID> --target full
```

**Примечания:**
- Barman 3.20.x (GPL-3, поддерживается EnterpriseDB): `backup_method = postgres` использует low-level backup API, `archiver = on` включает WAL-стриминг с primary.
- `retention_policy = RECOVERY WINDOW OF 4 WEEKS` — гарантирует возможность PITR на любую точку внутри окна.
- `barman recover ... --target-time "2026-08-17 10:00:00"` — восстановление на момент времени.

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `pg_dump` | Логический дамп одной БД | `pg_dump -Fc --compress=zstd:3 -f /backups/mydb.dump mydb` |
| `pg_dumpall` | Весь кластер / только глобальные объекты | `pg_dumpall -g > globals.sql` |
| `pg_basebackup` | Физический бэкап кластера | `pg_basebackup -D /backups/base -Fp -X stream` |
| `pg_verifybackup` | Проверка base backup без восстановления | `pg_verifybackup -e /backups/base/20260817` |
| `pg_receivewal` | Стриминг WAL в реальном времени (альтернатива `archive_command`) | Подробнее: **[Теория бэкапов](../Concepts/backup_and_recovery.md)** |
| `pg_archivecleanup` | Ротация WAL-архива (удаление сегментов старше заданного) | `pg_archivecleanup /mnt/wal_archive 000000010000000000000001` |
| `pgbackrest` | Бэкап/восстановление/проверка репозитория | `pgbackrest --stanza=main backup --type=incr` |
| `barman` | Централизованное управление бэкапами | `barman backup db-server` |
| `flock` | Защита от наложения запусков | `flock -n 9` (в скрипте) |

## Валидация и мониторинг

### Верификация целостности

**Для бэкапов `pg_basebackup` — `pg_verifybackup` (PostgreSQL 13+):**

Проверка проходит в четыре стадии: (1) чтение и верификация `backup_manifest` против `pg_control`; (2) сверка файлов данных на диске с манифестом; (3) поиск лишних/недостающих файлов; (4) проверка наличия и читаемости нужных WAL-записей.

```bash
pg_verifybackup -e /mnt/backups/base/20260817_020000
# → код 0 при успехе; -e — прерваться на первой же проблеме
```

**Для репозиториев pgBackRest:**
```bash
# Валидация конфигурации и архивации
pgbackrest --stanza=main check

# Проверка содержимого репозитория (целостность хранимых копий)
pgbackrest --stanza=main verify
```

> **Важно:** `pg_verifybackup` **не применим** к репозиториям pgBackRest/Barman — он читает `backup_manifest` в формате `pg_basebackup`. Для pgBackRest/Barman используйте их собственные команды (`verify`, `check`, `barman check`).

### Автоматическое тестовое восстановление

Лучшая практика — автоматический разворот последнего бэкапа на изолированном инстансе (Stage/Test) раз в неделю:
- **Скрипт:** Создаёт временный каталог, восстанавливает (`pgbackrest restore`, `barman recover` или `pg_basebackup`-каталог), запускает кластер на нестандартном порту и выполняет `SELECT 1`.
- **Результат:** Гарантия того, что бэкап не просто «лежит на диске», но и работоспособен. Методика детально: **[Проверка целостности и тестовое восстановление](../../Concepts/backup_validation.md)**.

### Мониторинг бэкапов

Необходимо отслеживать следующие метрики через Prometheus или Zabbix:
1.  **Time since last backup:** Время с момента последней успешной копии.
2.  **Backup size trend:** Резкое уменьшение размера бэкапа может сигнализировать об удалении данных.
3.  **WAL archiving status:** `SELECT * FROM pg_stat_archiver;` — `failed_count` должен быть 0, `last_archived_wal` обновляться; очередь в `pg_wal/archive_status`.
4.  **Exit code:** Код завершения скриптов автоматизации (с `set -eo pipefail` любая ошибка прерывает скрипт).
5.  **Heartbeat:** Dead Man's Snitch — сигнал «скрипт отработал» в мониторинг.

См. подробнее: **[Наблюдаемость PostgreSQL](./observability.md)** и **[Мета-мониторинг: Dead Man's Switch для бэкапов](../../../Concepts/Observability_and_Monitoring/meta-monitoring.md)**.

## Поиск и устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **pg_dump: Access Denied** | Недостаточно прав у роли. | Выдайте `pg_read_all_data` или проверьте `pg_hba.conf`. |
| **Backup fails: No space left** | Не настроена ротация (retention). | Уменьшите глубину хранения (`--expire-auto`, `retention_policy`) или увеличьте хранилище. |
| **Archive command failed** | Недоступен каталог/диск архива, нет прав на запись. | Проверьте `pg_stat_archiver.failed_count`, `last_failed_wal`, монтирование и права для пользователя `postgres`. |
| **Exclusive lock timeout** | Бэкап конфликтует с DDL (например, `TRUNCATE`). | Запускайте бэкап в часы минимальной нагрузки; используйте pgBackRest (`--backup-standby` — со реплики). |
| **pg_verifybackup: manifest mismatch** | Несовпадение версий инструмента и бэкапа или повреждение. | Используйте `pg_verifybackup` той же мажорной версии, что и бэкап; WAL-проверка версионно-специфична. |
| **pgBackRest: version mismatch** | Разные версии pgBackRest на local и repo host. | Выровняйте версии на всех узлах. |
| **Таймер не запускается** | Юнит не перечитан или нет service-юнита. | `systemctl daemon-reload`; `systemctl list-timers`; `journalctl -u <unit>`; timer без одноимённого `.service` не сработает. |
| **Бэкапы накладываются друг на друга** | Долгий запуск + частое расписание. | Добавьте `flock` в скрипт (см. сценарий 1). |

## Лучшие практики

- **Правило 3-2-1:** 3 копии данных, на 2 разных носителях, 1 копия — off-site (второй хост/здание, физически отдельно).
- **Защита от ransomware:** репозиторий — на отдельном хосте или под отдельным пользователем, у которого нет прав на изменение/удаление, кроме операций записи новых копий; Barman-сервер и repo-хост pgBackRest изолируют бэкапы от скомпрометированного сервера БД.
- **Шифрование:** шифруйте бэкапы при хранении на съёмных/выделенных носителях (GPG для логических, `--encrypt`/repo-encryption в pgBackRest).
- **Тестовое восстановление** — раз в неделю на изолированном инстансе; без него бэкап считается непроверенным.
- **GFS-ротация:** дневные (7) + недельные (4) + месячные (12) вместо плоского `-mtime` — защита от поздно обнаруженной потери данных.
- **Мониторинг свежести:** алерт, если последний успешный бэкап старше окна + Dead Man's Snitch на сам скрипт.
- **Pre-checks в скрипте:** `df -h`, `pg_stat_archiver.failed_count = 0`, `flock` — дешевле, чем разбирать неконсистентный результат.

## Очистка и откат

**Отключение автоматизации:**
```bash
# Systemd timer
sudo systemctl disable --now pgbackrest-backup.timer
sudo rm /etc/systemd/system/pgbackrest-backup.{timer,service}
sudo systemctl daemon-reload

# Cron
sudo rm /etc/cron.d/pg-logical-backup

# Удаление репозитория pgBackRest (осторожно — необратимо)
pgbackrest --stanza=main stanza-delete
sudo rm -rf /var/lib/pgbackrest

# Barman: удаление конфигурации сервера
sudo rm /etc/barman.d/db-server.conf
barman delete db-server <BACKUP_ID>   # перед удалением конфига
```

**Откат конфигурации PostgreSQL:** если автоматизация включала `archive_mode`/`archive_command` — верните значения `off`/пустая строка и перезагрузите (`pg_reload_conf()` или `systemctl reload postgresql`). Проверьте, что каталог архива WAL больше не заполняется.

## Дополнительная информация

### Связанные документы

- **[Теория бэкапов и восстановления](../Concepts/backup_and_recovery.md)** — концептуальный SSoT: RPO/RTO, PITR и уровни копирования; `pg_dump`/`pg_basebackup`/`pg_receivewal` подробно.
- **[Проверка целостности и тестовое восстановление](../../Concepts/backup_validation.md)** — методика валидации PITR и бэкапов.
- **[Управление ролями и правами доступа (RBAC)](./role_management.md)** — настройка прав для сервисного пользователя бэкапа.
- **[Наблюдаемость PostgreSQL](./observability.md)** — интеграция бэкапов в общую панель мониторинга.
- **[Мета-мониторинг: Dead Man's Switch для бэкапов](../../../Concepts/Observability_and_Monitoring/meta-monitoring.md)** — heartbeat-мониторинг выполнения резервного копирования.
- **[Журнал предзаписи (WAL)](../../Concepts/write_ahead_log.md)** — механизм архивации WAL и `pg_archivecleanup`.
- **[Стратегии отката](../../Concepts/rollback_strategies.md)** — где бэкапы вписываются в стратегии отката изменений.
