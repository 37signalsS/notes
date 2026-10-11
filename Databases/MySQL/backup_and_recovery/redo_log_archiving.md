# InnoDB Redo Log Archiving

**Актуально для:** MySQL 8.0.17+ / 8.4, Percona XtraBackup 8.0.34-29+ / 8.4

> **Статус:** механизм InnoDB, встроенный в сервер. Не путать с архивированием **бинарного лога** — это разные подсистемы с разными целями: binlog архивируется для PITR, redo log archive — чтобы физический бэкап не потерял записи при копировании.

## Определения

**Redo log** — журнал изменений InnoDB. Каждая изменённая страница данных сначала записывается в redo log как физическая операция, и только затем применяется к файлам данных. Redo log обеспечивает две вещи: откат незакоммиченных транзакций при старте и повторное применение изменений после аварийного сбоя (crash recovery).

**Redo log archive** — дополнительный файл, в который сервер **последовательно** пишет те же записи redo log, что и в основные файлы. Введён в MySQL 8.0.17. Смысл: backup-утилита может копировать этот архив медленно, не рискуя потерять записи, перезаписанные в основном redo log.

**`innodb_redo_log_archive_dirs`** — глобальная переменная, задающая список именованных каталогов для redo log archive в формате `label:path`, разделённых точкой с запятой. Значение по умолчанию `NULL`, что запрещает активацию архивирования.

**`innodb_redo_log_archive_start()` / `innodb_redo_log_archive_stop()`** — функции активации и деактивации архивирования. Требуют привилегию `INNODB_REDO_LOG_ARCHIVE`.

**`--redo-log-arch-dir`** — опция Percona XtraBackup, задающая каталог архива в формате `label:path` **только когда переменная `innodb_redo_log_archive_dirs` не задана на сервере**: при заданной переменной она имеет приоритет, а опция игнорируется. Поскольку утилита выполняет `SET` внутренне, пользователь бэкапа помимо `INNODB_REDO_LOG_ARCHIVE` должен иметь `SUPER` или `SYSTEM_VARIABLES_ADMIN`. Доступна с версии XtraBackup 8.0.34-29.

**`subdir`** — необязательный второй аргумент `innodb_redo_log_archive_start()`: простое имя каталога (без `/`, `\`, `:`) внутри каталога, заданного меткой. Каталог и подкаталог должны существовать заранее — процесс архивирования их не создаёт; аргумент может быть пустым, `NULL` или опущен.

**`innodb_redo_log_archive_flush()` / `innodb_redo_log_sharp_checkpoint()`** — вспомогательные функции (с 8.0.31): сброс очереди архива redo log и создание sharp checkpoint. Используются MySQL Enterprise Backup для инкрементальных бэкапов.

## Основные концепции

### Проблема, которую решает архивирование

Физический бэкап работает в два прохода: сначала копируются файлы данных InnoDB, затем отдельно дочитываются недостающие записи redo log, чтобы довести состояние файлов до согласованного. На этом втором проходе возникает проблема, которую Oracle формулирует предельно ясно:

> Backup-утилиты, копирующие записи redo log, иногда не могут угнаться за генерацией redo log во время бэкапа, что приводит к **потере** записей, потому что они были перезаписаны. Проблема чаще возникает при значительной активности сервера и когда носитель redo log быстрее носителя бэкапа.

До 8.0.17 утилита была вынуждена читать redo log из основных файлов, которые сервер продолжает перезаписывать по мере роста нагрузки. Ошибка проявлялась уже после завершения бэкапа, при применении скопированного redo — и бэкап оказывался непригодным.

Redo log archive разрывает эту зависимость от скорости: сервер сам пишет архив последовательно, а утилита читает его в своём темпе.

### Ограничения на каталог архива

Требования проверяются в момент активации, а не при старте сервера:

| Требование | Ошибка при нарушении |
| :--- | :--- |
| Каталог должен существовать | `ERROR 3844 (HY000): Redo log archive directory ... does not exist or is not a directory` |
| Не должен быть доступен всем пользователям ОС (world-accessible) | `ERROR 3846 (HY000): Redo log archive directory ... is accessible to all OS users` |
| Не может совпадать с `datadir`, `innodb_data_home_dir`, `innodb_directories`, `innodb_log_group_home_dir`, `innodb_temp_tablespaces_dir`, `innodb_tmpdir`, `innodb_undo_directory`, `secure_file_priv`, а также быть их родительским или вложенным каталогом | `ERROR 3845 (HY000): Redo log archive directory ... is in, under, or over server directory 'datadir' - ...` |
| В пути запрещена точка с запятой | Ошибка активации |

Требование «не вложен в `datadir`» логично: архив redo содержит данные всех таблиц, и размещение его рядом с данными означало бы, что бэкап данных уносит с собой и незавершённый архив, а наивное удаление старых бэкапов могло бы затронуть работающий архив.

### Жизненный цикл сессии архивирования

Ключевое и часто упускаемое правило: **сессия, активировавшая архивирование, должна оставаться открытой до явной деактивации.**

```
backup utility → innodb_redo_log_archive_start('label')  [в своей сессии]
              → копирование файлов данных InnoDB
              → копирование записей из archive.serverUUID.000001.log
              → innodb_redo_log_archive_stop()
```

Если сессия закрывается раньше вызова `stop()`, сервер деактивирует архивирование неявно и **удаляет файл архива**. Это объясняет, почему ручная активация через одноразовое подключение вида `mysql -e "..."` не работает: сессия закрывается сразу после выполнения запроса — архива нет.

Имя файла формируется как `archive.serverUUID.000001.log`, где `serverUUID` берётся из `SELECT @@server_uuid`. Метка в имени относится к каталогу из `innodb_redo_log_archive_dirs`, а `subdir` — необязательный простой каталог внутри него.

### Удаление файла архива

В штатном режиме файл архива удаляет сама backup-утилита, когда дочитала нужные записи. Если операция завершилась аварийно до вызова `stop()`, файл удаляет сам сервер. Право на удаление лежит на утилите — это стоит понимать при разборе инцидента, когда на диске неожиданно много места.

## Практические сценарии

### Сценарий 1: Подготовка сервера

```sql
-- Каталог создаётся ОС, не сервером, и не должен быть world-accessible
SELECT @@server_uuid;
-- → e71a47dc-61f8-11e9-a3cb-080027154b4d
```

```bash
install -d -o mysql -g mysql -m 750 /var/lib/mysql-redo-archive
# → создан каталог с правами 750, доступен mysql, недоступен world
ls -ld /var/lib/mysql-redo-archive
# → drwxr-x--- 2 mysql mysql 4096 Oct  3 03:10 /var/lib/mysql-redo-archive
```

```ini
# /etc/mysql/mysql.conf.d/backup.cnf
[mysqld]
innodb_redo_log_archive_dirs=backup1:/var/lib/mysql-redo-archive
```

```sql
SELECT @@innodb_redo_log_archive_dirs;
-- → backup1:/var/lib/mysql-redo-archive
```

Привилегия выдаётся пользователю бэкапа (полный блок — в **[Пользователь бэкапа](./overview.md#пользователь-бэкапа-принцип-наименьших-привилегий)**):

```sql
GRANT INNODB_REDO_LOG_ARCHIVE ON *.* TO 'backup_user'@'localhost';
```

> **Важно:** переменная — `GLOBAL`, и её можно менять на работающем сервере (`SET GLOBAL`). Но она должна быть задана **до** активации архивирования; при значении `NULL` вызов `start()` невозможен. Для постоянства задавайте её в конфигурационном файле, а не только в рантайме — иначе после перезагрузки архивирование молча перестанет работать.

### Сценарий 2: Ручная активация и проверка

```bash
mysql -u backup_user -p
# → Welcome to the MySQL monitor.  Commands end with ; or \g.
mysql> SELECT innodb_redo_log_archive_start('backup1');
# → 0
```

> **Одноразовый вызов не работает:** `mysql -e "SELECT innodb_redo_log_archive_start('backup1')"` завершается сразу после запроса — сессия закрывается, сервер неявно деактивирует архивирование и удаляет файл. Для скриптов сессию держат открытой, например через именованный канал:
>
> ```bash
> mkfifo /tmp/redo-arch-fifo
> mysql -u backup_user -p < /tmp/redo-arch-fifo &
> exec 3>/tmp/redo-arch-fifo
> echo "SELECT innodb_redo_log_archive_start('backup1');" >&3
> # → бэкап запускается в это время
> echo "SELECT innodb_redo_log_archive_stop();" >&3
> exec 3>&- && rm /tmp/redo-arch-fifo
> ```

```bash
ls -l /var/lib/mysql-redo-archive/
# → -rw-r----- 1 mysql mysql 41240 Oct  3 03:12 archive.e71a47dc-61f8-11e9-a3cb-080027154b4d.000001.log
```

```sql
-- Метки из переменной
SELECT @@innodb_redo_log_archive_dirs;
-- → backup1:/var/lib/mysql-redo-archive
```

```sql
-- Деактивация: сессия обязана быть той же, что активировала архив.
-- Вызов из другой сессии, пока исходная открыта, даёт ERROR 3851.
SELECT innodb_redo_log_archive_stop();
# → 0
```

> **Ошибки, которые чаще всего встречаются:**
> - `ERROR 3842 (HY000): Label 'backup2' not found in server variable 'innodb_redo_log_archive_dirs'` — метка не совпадает с объявленной. Список меток: `label1:/path1;label2:/path2`. Обратите внимание на разделитель — точка с запятой.
> - Каталог под `datadir` → `ERROR 3845`. Например, `/var/lib/mysql/redo-archive` недопустим, `/var/lib/mysql-redo-archive` — допустим.
> - `ERROR 3846` при `chmod 777` — типичная ошибка из скрипта установки, который «на всякий случай» делает каталог доступным всем.

### Сценарий 3: XtraBackup с архивированием redo

```bash
# Вариант A: переменная задана на сервере (сценарий 1) — флаг не нужен,
# xtrabackup использует innodb_redo_log_archive_dirs автоматически
xtrabackup --backup \
  --target-dir=/backups/xtrabackup/full \
  --user=backup_user --password="$MYSQL_PWD" \
  --parallel=4
# → [Note] [MY-011825] [Xtrabackup] completed OK!

# Вариант B: переменная НЕ задана на сервере — каталог задаётся флагом
# в формате label:path; пользователь бэкапа должен иметь
# SUPER или SYSTEM_VARIABLES_ADMIN (утилита выполняет SET внутренне)
xtrabackup --backup \
  --target-dir=/backups/xtrabackup/full \
  --user=backup_user --password="$MYSQL_PWD" \
  --redo-log-arch-dir=backup1:/var/lib/mysql-redo-archive \
  --parallel=4
```

> **OS-пользователь:** xtrabackup должен запускаться от того же владельца, что и `mysqld` (обычно `mysql`), и иметь доступ к каталогу архива на уровне чтения и записи. Иначе — `Permission denied` (OS errno: 13) и архивирование не используется.

Что происходит под капотом (PXB 8.0.34-29+): утилита при необходимости выполняет `SET GLOBAL innodb_redo_log_archive_dirs` (вариант B), вызывает `innodb_redo_log_archive_start('backup1', '<подкаталог>')` в своей сессии, копирует файлы данных, затем дочитывает необходимые записи из архива вместо основных файлов redo log, вызывает `stop()` и удаляет файл архива.

Приоритет выбора каталога: серверная переменная `innodb_redo_log_archive_dirs` → флаг `--redo-log-arch-dir` → временный каталог, создаваемый утилитой. То есть начиная с 8.0.34-29 XtraBackup использует архивирование **всегда** — «старый» способ чтения основных файлов redo log остался только в версиях ниже 8.0.34-29.

> MySQL Enterprise Backup (MySQL Enterprise Edition) использует архивирование redo log автоматически, когда `innodb_redo_log_archive_dirs` задана на сервере.

### Сценарий 4: Диагностика проблем с архивированием

```sql
-- Переменная задана?
SELECT @@innodb_redo_log_archive_dirs;
-- → NULL означает, что архивирование недоступно

-- Активно ли архивирование? Фоновый поток присутствует,
-- только пока архивирование идёт
SELECT thread_id, name, type FROM performance_schema.threads
WHERE name LIKE '%redo_log_archive%';
-- → строка возвращается, пока архивирование активно

-- Используется ли файл архива (запись может сохраняться
-- и после корректного stop() — сама по себе не доказывает активность)
SELECT * FROM performance_schema.file_instances
WHERE event_name LIKE '%::redo_log_archive_file'\G
```

```bash
# Размер файла архива растёт ли?
watch -n 2 'ls -l /var/lib/mysql-redo-archive/'

# Ошибки в логе сервера
grep -i "redo log archive\|3842\|3844\|3845\|3846\|3847\|3848\|3850\|3851" /var/log/mysql/error.log
# → [ERROR] 3846 (HY000) at line 1: Redo log archive directory '/var/lib/mysql-redo-archive'
#   is accessible to all OS users
```

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR 3842` Label not found | Метка в вызове не совпадает с `innodb_redo_log_archive_dirs` | Сверить метки; помнить разделитель `;` |
| `ERROR 3844` directory does not exist | Каталог не создан | `install -d -o mysql -g mysql -m 750 /var/lib/mysql-redo-archive` |
| `ERROR 3845` in, under, or over server directory | Каталог внутри `datadir` или `secure_file_priv` | Перенести каталог вне `datadir` |
| `ERROR 3846` accessible to all OS users | Права слишком широкие | `chmod 750` |
| `ERROR 3847` Cannot create redo log archive file (OS errno: 13 - Permission denied) | Каталог/подкаталог есть, но не принадлежит OS-пользователю mysqld | `chown mysql:mysql` на каталог и подкаталог |
| `ERROR 3848` Redo log archiving has been started ... Call innodb_redo_log_archive_stop() first | Архивирование уже активно | Вызвать `stop()` в сессии, которая его начала |
| `ERROR 3850` Session terminated with active redo log archiving | Сессия, начавшая архивирование, закрылась раньше `stop()` | Архив удалён сервером; запустить бэкап заново |
| `ERROR 3851` Redo log archiving has not been started by this session | `stop()` вызван из другой сессии, пока исходная открыта | Вызвать `stop()` в исходной сессии |
| Файл архива не появляется | Сессия закрылась раньше `stop()` | Держать сессию открытой весь период архивирования |
| Архив перестал работать после перезагрузки | Переменная была задана только через `SET GLOBAL` | Перенести в конфигурационный файл |
| Медленный бэкап, ошибок нет | Носитель архива медленнее генерации redo | Смонтировать архив на быстрый локальный диск, исключить из антивирусного сканирования |

## Ограничения и особенности

1. **Только MySQL 8.0.17 и новее.** На 5.7 и в более ранних 8.0 механизма нет; там единственный путь — `--force-non-transactional-tables` не помогает, остаётся работать с основными файлами redo log и контролировать нагрузку.
2. **Требуется привилегия `INNODB_REDO_LOG_ARCHIVE`.** Утилита, не имеющая её, активировать архивирование не сможет.
3. **Сессия должна жить весь период.** Это делает «ручной» сценарий неудобным: нужен интерактивный клиент или утилита, умеющая удерживать сессию.
4. **Требуется отдельный носитель.** Архив, лежащий на том же диске, что и `datadir`, не защищает от отказа диска и лишается смысла по производительности — ровно та ситуация, которую механизм и устраняет.
5. **Каталог не создаётся автоматически** и проверяется только в момент активации — опечатка в `my.cnf` обнаружится в момент бэкапа, а не при старте сервера.
6. **Механизм не заменяет архивирование binlog.** Успешный физический бэкап с redo log archive не даёт возможности PITR до произвольного момента: для этого нужен **[архив бинарного лога](../replication/binlog_management.md)**.

## Бест-практики

1. **Каталог архива — на отдельном носителе,** быстрее и надёжнее, чем `datadir`. Если это невозможно, осознайте, что выигрываете только в консистентности, но не в отказоустойчивости.
2. **Права `750`, владелец — OS-пользователь MySQL.** Мир читает ваши redo-записи, потенциально содержащие изменённые данные.
3. **Задавайте `innodb_redo_log_archive_dirs` в конфигурационном файле,** а не через `SET GLOBAL` в рантайме.
4. **Проверяйте архивирование в рамках smoke-теста бэкапов,** а не при аварии. Пустой архив при штатном бэкапе — сигнал о том, что он не работает.
5. **Не держите архивирование включённым постоянно.** Оно активируется на время бэкапа и деактивируется сразу после — постоянно работающий архив бесполезен и расходует место.
6. **Для XtraBackup используйте ветку 8.0.34-29+ или 8.4** — в них архивирование redo log применяется всегда (приоритет: серверная переменная → флаг `--redo-log-arch-dir` → временный каталог утилиты).

## Дополнительная информация

### См. также

- **[Физический бэкап XtraBackup](./xtrabackup.md)** — использование физического бэкапа и его параметры.
- **[Обзор инструментов бэкапа](./overview.md)** — сравнение физических и логических методов, консистентность, привилегии.
- **[Управление бинарным логом](../replication/binlog_management.md)** — binlog archive и PITR (не путать с redo log archive).
- **[Point-in-Time Recovery](./pitr.md)** — применение архивов для восстановления на заданный момент.
- **[Хранилища MySQL](../Operations/storage_engines_deep_dive.md)** — механизм InnoDB, MVCC, redo log как основа транзакций.
- **[Конфигурация MySQL](../configuration.md)** — где размещать переменные уровня `GLOBAL`, динамическое управление через `SET PERSIST`.

### Внешние ресурсы

- **[Redo Log — MySQL 8.4 Reference Manual](https://dev.mysql.com/doc/refman/8.4/en/innodb-redo-log.html)** — раздел Redo Log Archiving, полный список ограничений и ошибок.
- **[InnoDB Redo Log Archiving — MySQL 8.0 Reference Manual](https://dev.mysql.com/doc/refman/8.0/en/innodb-redo-log.html)** — синтаксис для 8.0.
- **[InnoDB redo log archiving — Percona XtraBackup 8.0](https://docs.percona.com/percona-xtrabackup/8.0/redo-log-archiving.html)** — использование в XtraBackup.
- **[Percona XtraBackup 8.4 — документация](https://docs.percona.com/percona-xtrabackup/8.4/index.html)** — актуальная ветка (8.4.0-7, 2026-09-17).
- **[Backing up Using Redo Log Archiving — MySQL Enterprise Backup](https://docs.oracle.com/cd/E17952_01/mysql-enterprise-backup-8.0-en/meb-redo-log-archiving.html)** — требования `mysqlbackup` к каталогу и привилегиям.