# Клиентские утилиты MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**Клиентские утилиты MariaDB** — набор консольных инструментов для администрирования сервера, управления данными, резервного копирования, анализа производительности и нагрузочного тестирования. Начиная с MariaDB 10.5 утилиты переименованы во избежание конфликтов с Oracle MySQL.

**MariaDB Shell (`mariadb-shell`)** — интерактивный клиент нового поколения с поддержкой трёх режимов работы: **SQL**, **JavaScript** и **Python**. Подходит для интерактивного администрирования, автоматизации скриптами и пакетной обработки.

**Point-in-Time Recovery (PITR)** — восстановление базы данных до точно определённого момента времени путём наката бинарных логов (WAL) на полный бэкап.

**`mariadb-import`** — утилита для пакетной загрузки данных из текстовых файлов (CSV, TSV) в таблицы MariaDB. Использует внутренне `LOAD DATA INFILE`.

**`mariadb-slap`** — диагностическая утилита для эмуляции клиентской нагрузки и измерения latency на различных стадиях выполнения запросов.

**`mariadb-dumpslow`** — утилита для парсинга лога медленных запросов и вывода сводной статистики по шаблонам запросов.

## Основные концепции

### Ребрендинг и обратная совместимость

Начиная с версии 10.5+, MariaDB перешла на собственные имена утилит. Старые имена (`mysql*`) сохраняются как символические ссылки, но в SRE-практике и автоматизации **обязательно** использовать новые имена для предотвращения конфликтов с Oracle MySQL.

| Старое имя | Актуальное имя | Назначение |
| :--- | :--- | :--- |
| `mysql` | `mariadb` | Основной интерактивный SQL-клиент |
| `mysqldump` | `mariadb-dump` | Логическое резервное копирование |
| `mysqladmin` | `mariadb-admin` | Управление сервером (status, ping, shutdown) |
| `mysqlcheck` | `mariadb-check` | Проверка, ремонт и оптимизация таблиц |
| `mysqlbinlog` | `mariadb-binlog` | Обработка бинарных логов (WAL) |
| `mysql_upgrade` | `mariadb-upgrade` | Миграция системных таблиц при обновлении |
| `mysqlimport` | `mariadb-import` | Импорт структурированных данных (CSV, TSV) |
| `mysqlslap` | `mariadb-slap` | Нагрузочное тестирование (стресс-тесты) |

### Безопасная аутентификация в утилитах

Для предотвращения утечки паролей через историю команд (`history`) или список процессов (`ps`), утилиты MariaDB поддерживают следующие методы:
- **Файлы параметров:** Использование флага `--defaults-extra-file=/path/to/creds.cnf`.
- **Unix Socket:** Локальный вход через `sudo` без пароля (актуально для `mariadb` и `mariadb-admin`).
- **MARIADB_HISTFILE:** Переменная окружения для выноса истории команд в защищенное место.

### Режимы работы MariaDB Shell

MariaDB Shell поддерживает три изолированных режима выполнения кода. Переключение происходит командами `\sql`, `\js`, `\py` в интерактивном режиме или флагами `--sql`, `--js`, `--py` в пакетном.

- **SQL:** Стандартный режим. Все выражения отправляются на сервер как SQL.
- **JavaScript:** Полезен для автоматизации и работы с результатами запросов через объектную модель.
- **Python:** Полезен для скриптов миграции и аналитики. Доступ к глобальной сессии через объект `session`.

## Предварительные требования

Перед использованием клиентских утилит убедитесь, что среда соответствует минимальным требованиям.

### Требования к оборудованию и ОС

- **ОЗУ:** Минимум 2GB для тестовых сред. Production: минимум 8GB.
- **Диск:** Файловые системы, совместимые с `O_DIRECT` (ext4, XFS, ZFS), для прямого ввода-вывода.
- **Ядра Linux:** 5.4+ для стабильной работы Thread Pool и Transparent Huge Pages.
- **Права доступа:** Пользователь `mysql` должен иметь права на запись в `datadir`, каталог логов и каталог сокета. Пользователь, под которым запускаются утилиты бэкапа, должен иметь привилегии `RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT`.
- **Сеть:** Для удалённого использования утилит убедитесь, что порт 3306 доступен и настроен `bind-address`. Для `mariadb-binlog --read-from-remote-server` требуется открытый порт и активный пользователь с правами `REPLICATION SLAVE` или `REPLICATION CLIENT`.

### Подготовка ОС

```bash
# Проверка прозрачных огромных страниц (THP)
cat /sys/kernel/mm/transparent_hugepage/enabled
# → рекомендуется: never

# Проверка лимитов файловых дескрипторов
ulimit -n
# → должно быть >= 65535 для production

# Проверка vm.swappiness
cat /proc/sys/vm/swappiness
# → рекомендуется: 1
```

**Валидация:**

```bash
# Проверка vm.swappiness
sysctl vm.swappiness
# → vm.swappiness = 1

# Проверка открытых файловых дескрипторов для mysql
cat /proc/$(pidof mysqld)/limits | grep "open files"
# → Max open files 65535 65535 files
```

## Практические сценарии

### 1. MariaDB Shell: Режимы SQL, JavaScript и Python

MariaDB Shell поддерживает три режима. В пакетном режиме указывается флаг языка; в интерактивном — команды `\sql`, `\js`, `\py`.

**SQL-режим (по умолчанию):**

```bash
mariadb-shell --sql -e "SELECT VERSION();"
# → 12.3.2-MariaDB-12.3.2+maria~ubu2204
```

**JavaScript-режим:**

```bash
mariadb-shell --js -e "\\sql SELECT @@version"
# → 12.3.2-MariaDB-12.3.2+maria~ubu2204
```

**Python-режим:**

```bash
mariadb-shell --py -e "
import mariadb
session = mariadb.connect(host='localhost', user='root')
cursor = session.cursor()
cursor.execute('SELECT VERSION()')
print(cursor.fetchone()[0])
"
# → 12.3.2-MariaDB-12.3.2+maria~ubu2204
```

### 2. Анализ медленных запросов (mariadb-dumpslow)

Для выявления проблемных запросов используйте `mariadb-dumpslow`. Детальный разбор Slow Query Log и Performance Schema см. в **[Мониторинге MariaDB](monitoring.md)**.

```bash
# Топ-10 запросов по общему времени
mariadb-dumpslow -s t /var/log/mysql/slow.log | head -10

# Топ-10 запросов по количеству вызовов
mariadb-dumpslow -s c /var/log/mysql/slow.log | head -10
```

**Валидация:**

```bash
# Проверка наличия лога медленных запросов
ls -lh /var/log/mysql/slow.log
# → -rw-r----- 1 mysql mysql 15M Aug 17 10:15 /var/log/mysql/slow.log
```

### 3. Пакетный импорт данных (mariadb-import)

`mariadb-import` загружает данные из CSV/TSV-файлов через `LOAD DATA INFILE`. Начиная с MariaDB 11.6 поддерживается пакетный режим `--dir`.

```bash
# Импорт одного CSV-файла
mariadb-import --user=root --password \
  --fields-terminated-by=',' \
  --ignore-lines=1 \
  app_db /data/import/users.csv

# Пакетный импорт всей директории (MariaDB 11.6+)
mariadb-import --user=root --password \
  --dir=/data/import/batch \
  --database=app_db
```

**Валидация:**

```sql
-- Проверка количества загруженных строк
SELECT COUNT(*) FROM app_db.users;
-- → 150000
```

### 4. Нагрузочное тестирование (mariadb-slap)

Используется для измерения производительности сервера под эмулируемой нагрузкой.

```bash
# Тест с 50 параллельными клиентами, 1000 запросов каждый
mariadb-slap --user=root --password \
  --concurrency=50 \
  --iterations=10 \
  --query="SELECT * FROM app_db.users WHERE id = 1"
```

**Валидация:**

```bash
# Ожидаемый вывод: среднее время выполнения запроса по клиентам
# → Average number of seconds to run all queries: 0.015 seconds
# → Minimum number of seconds to run all queries: 0.012 seconds
# → Maximum number of seconds to run all queries: 0.023 seconds
```

### 5. Консистентное резервное копирование (mariadb-dump)

Для обеспечения целостности данных при дампе транзакционных таблиц (InnoDB) необходимо использовать специальные флаги. Детальные сценарии, включая `mydumper`, см. в **[Резервном копировании MariaDB](backup_and_recovery.md)**. Включение хранимых объектов см. в **[Хранимых объектах в MariaDB](./Concepts/stored_objects_management.md)**.

```bash
# Создание консистентного дампа большой БД
mariadb-dump --user=admin --password \
    --single-transaction \  # Не блокирует чтение/запись в InnoDB
    --routines --events \    # Включает процедуры и события
    --triggers \
    --master-data=2 \       # Записывает позицию бинарного лога (для репликации)
    app_db > app_db_full.sql
```

**Валидация:**

```bash
# Проверка размера дампа
ls -lh app_db_full.sql
# → -rw-r--r-- 1 admin admin 1.2G Aug 17 10:20 app_db_full.sql

# Проверка начала файла (должен содержать CREATE DATABASE)
head -5 app_db_full.sql
# → -- MariaDB dump
# → -- Host: localhost    Database: app_db
# → -- ------------------------------------------------------
# → -- Server version 12.3.2-MariaDB-12.3.2+maria~ubu2204
```

### 6. Жизненный цикл сервера (mariadb-admin)

Краткие административные действия без входа в интерактивный режим. Детальное обслуживание, `mariadb-upgrade` и окна обслуживания см. в **[Обслуживании MariaDB](maintenance.md)**.

```bash
# Проверка доступности сервера
mariadb-admin -u root ping
# → mysqld is alive

# Получение краткого статуса (Uptime, Threads, Questions)
mariadb-admin status

# Безопасная перезагрузка логов (Flush logs)
mariadb-admin flush-logs

# Вывод текущих значений системных переменных
mariadb-admin variables | grep "innodb_buffer_pool"
```

**Валидация:**

```bash
# Проверка после flush-logs
ls -lh /var/lib/mysql/mariadb-bin.* | tail -5
# → новые файлы логов созданы
```

### 7. Восстановление данных через PITR (mariadb-binlog)

Сценарий: случайное удаление таблицы в 10:15 утра. Бэкап был сделан в 00:00. Детальный разбор PITR, GTID и физических бэкапов см. в **[Резервном копировании MariaDB](backup_and_recovery.md)** и **[Бинарном логировании](./security/binary-logging.md)**.

```bash
# 1. Восстанавливаем полный бэкап
mariadb -u root < backup_00_00.sql

# 2. Накатываем бинарный лог до момента ошибки
# Используем GTID для точности в MariaDB 12.3
mariadb-binlog --start-datetime="2026-08-17 00:00:00" \
               --stop-datetime="2026-08-17 10:14:59" \
               --base64-output=DECODE-ROWS \
               /var/lib/mysql/binlog.000005 | mariadb -u root
```

**Валидация:**

```sql
-- Проверка восстановленной таблицы
SELECT COUNT(*) FROM app_db.users;
-- → 150000
```

### 8. Продвинутая автоматизация через MariaDB Shell (Python)

MariaDB Shell в режиме Python позволяет создавать скрипты мониторинга и миграции без внешних зависимостей.

```python
# mariadb-shell --py
import mariadb
session = mariadb.connect(host='localhost', user='monitor')

# Анализ фрагментации всех таблиц InnoDB
cursor = session.cursor()
cursor.execute("""
    SELECT table_schema, table_name, data_free, data_length
    FROM information_schema.tables
    WHERE engine='InnoDB'
      AND data_free > 0
      AND table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    ORDER BY data_free DESC
""")
for row in cursor.fetch_all():
    print(f"Table {row[0]}.{row[1]} has {row[2]} bytes free of {row[3]}")
```

**Валидация:**

```bash
# Запуск скрипта
mariadb-shell --py monitor_fragmentation.py
# → Table app_db.events has 536870912 bytes free of 16106127360
```

## Лучшие практики (Best Practices)

1. **Имена утилит:** Используйте новые имена (`mariadb-*`) во всех скриптах, IaC и документации. Старые имена (`mysql*`) считаются устаревшими и могут исчезнуть в будущих версиях.
2. **Аутентификация:** Никогда не передавайте пароль через командную строку (`--password=secret`). Используйте `--defaults-extra-file`, `~/.my.cnf` или Unix Socket.
3. **Пакетное администрирование:** Всегда указывайте `--defaults-extra-file` в cron-задачах, чтобы избежать интерактивного запроса пароля.
4. **Логические бэкапы:** Для InnoDB используйте `--single-transaction` в `mariadb-dump`, чтобы избежать блокировок чтения. Для хранимых объектов добавляйте `--routines --triggers --events`.
5. **Репликация и binlog:** При использовании `mariadb-binlog` для PITR предпочитайте GTID позиционированию по файлу и смещению (File:Offset). Настройте `expire_logs_days` не менее, чем максимальная задержка реплики + 1 день.
6. **Тестирование PITR:** Регулярно проверяйте восстановление на staging. Без этого вы не узнаете о проблемах с целостностью бэкапа в момент инцидента.
7. **Обслуживание:** Запускайте `mariadb-upgrade` только при мажорных апгрейдах. Для минорных обновлений (12.3.1 → 12.3.2) утилита не требуется, если Changelog не содержит изменений в системных таблицах.
8. **Нагрузочное тестирование:** Не запускайте `mariadb-slap` на production без предварительного согласования окна. Используйте его в staging для измерения влияния изменений конфигурации.
9. **Версионный контроль:** Скрипты, использующие утилиты, должны проверять версию MariaDB (`mariadb -e "SELECT VERSION()"`) и адаптировать флаги под целевую версию.
10. **Мониторинг:** Включите `slow_query_log` и ротацию через `expire_logs_days` или `binlog_expire_logs_seconds`. Регулярно анализируйте лог через `mariadb-dumpslow`.

## Особенности и ограничения (Edge Cases)

- **Конфликт имён с MySQL:** На одном сервере не должно быть установлено одновременно MySQL и MariaDB с пересекающимися путями `my.cnf` и `datadir`. Удалите один из пакетов перед установкой другого.
- **Символические ссылки:** Старые имена (`mysql*`) являются символическими ссылками. При обновлении пакетов они могут быть удалены. Всегда используйте новые имена в скриптах.
- **`mariadb-dump` и `--single-transaction`:** Флаг работает только для движков с MVCC (InnoDB). Для Aria/MyISAM он не снимает блокировки. Используйте `--lock-all-tables` для консистентности смешанных дампов.
- **`mariadb-dump` и хранимые объекты:** По умолчанию `mariadb-dump` не экспортирует процедуры, функции, триггеры и события. Без флагов `--routines --triggers --events` объекты теряются при восстановлении.
- **`mariadb-binlog` и формат лога:** При `binlog_format=STATEMENT` кросс-базовые запросы могут давать непредсказуемые результаты при восстановлении. Используйте `ROW` или `MIXED` для production.
- **`mariadb-import` и `LOAD DATA INFILE`:** При использовании `--local` файл читается клиентом, а не сервером. Без флага сервер должен иметь прямой доступ к файлу по пути, что часто нарушает политику безопасности.
- **`mariadb-slap` и production:** Утилита создаёт реальную нагрузку на сервер. Тестируйте только на staging или в окно с минимальной нагрузкой.
- **`mariadb-upgrade` и права:** Утилита требует прав `SUPER` или `ALTER USER` на системных таблицах. В Galera Cluster запускайте только на одном узле; остальные обновятся через SST.
- **Пароли в истории:** Даже с `--defaults-extra-file` убедитесь, что файл имеет права `0600` и не попал в репозиторий. Проверяйте через `git diff` перед коммитом.

## Устранение неполадок (Troubleshooting)

### Ошибка: `mariadb-dump: Got error: 1045`
- **Причина:** Неверные учетные данные.
- **Решение:** Проверьте `~/.my.cnf` или используйте `--defaults-extra-file`. Убедитесь, что у пользователя есть права `SELECT` и `LOCK TABLES`.

### Ошибка: `mariadb-dump: Couldn't execute 'SELECT * FROM ...`: Table is marked as crashed
- **Причина:** Повреждение таблицы InnoDB или Aria.
- **Решение:** Для Aria/MyISAM выполните `mariadb-check --repair`. Для InnoDB проверьте логи на наличие ошибок и восстановитесь из бэкапа. Если сервер не стартует, временно включите `innodb_force_recovery=1..6` в `my.cnf` для экспорта данных.

### Ошибка: `mariadb-upgrade: Upgrade failed`
- **Причина:** Нехватка прав или запущенный процесс `mariadb-upgrade` от другого пользователя.
- **Решение:** Запускайте утилиту через `sudo` и проверьте, что сервер находится в режиме `read_only=OFF`.

### Ошибка: `mariadb-binlog: Could not find target log file`
- **Причина:** Лог удалён политикой ротации или перемещён.
- **Решение:** Проверьте путь в `mariadb-binlog.index`. Убедитесь, что `expire_logs_days` или `binlog_expire_logs_seconds` настроен с запасом. Настройте `log_bin` на фиксированный путь.

### Ошибка: `mariadb-import: Access denied; you need (at least one of) the FILE privilege`
- **Причина:** У пользователя нет привилегии `FILE` или используется `--local` без права `SELECT`.
- **Решение:** Для `--local` достаточно `SELECT` и `INSERT` на целевую таблицу. Без `--local` требуется `FILE`.

### Ошибка: `mariadb-slap: Unknown table '...'`
- **Причина:** В запросе указана несуществующая таблица или база данных.
- **Решение:** Проверьте синтаксис запроса и права пользователя. Убедитесь, что таблица существует и содержит данные.

### Ошибка: `mariadb-admin: Can't connect to local server`
- **Причина:** Сервер не запущен или путь к сокету указан неверно.
- **Решение:** Проверьте `systemctl status mariadb`. Если сокет в нестандартном пути, передайте его через `--socket=/run/mysqld/mysqld.sock`.

## Дополнительная информация

### См. также
- **[Обзор MariaDB](overview.md)** — архитектура и стратегия развития.
- **[Обслуживание MariaDB](maintenance.md)** — детальные сценарии `mariadb-check`, `mariadb-admin`, `mariadb-upgrade` и окна обслуживания.
- **[Резервное копирование MariaDB](backup_and_recovery.md)** — `mariadb-backup`, `mariadb-dump`, PITR через GTID.
- **[Бинарное логирование](security/binary-logging.md)** — настройка ротации, `mariadb-binlog`, GTID.
- **[Хранимые объекты в MariaDB](Concepts/stored_objects_management.md)** — экспорт процедур, функций, триггеров и событий через `mariadb-dump`.
- **[Конфигурация MariaDB](configuration.md)** — настройка путей, прав доступа и параметров в `my.cnf`.
- **[Мониторинг MariaDB](monitoring.md)** — анализ Slow Query Log через `mariadb-dumpslow`, алерты, Performance Schema.
- **[Миграция MySQL → MariaDB](./Operations/migration_mysql_to_mariadb.md)** — использование `mariadb-dump` для переноса данных.
- **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)** — процедура обновления кластеров.
- **[Безопасная установка СУБД](../installation_security.md)** — принципы защиты конфигурационных файлов с паролями.

### Внешние ресурсы
- [MariaDB Client Utilities](https://mariadb.com/docs/server/server-usage/clients-and-utilities/)
- [MariaDB Shell Documentation](https://mariadb.com/docs/server/server-usage/mariadb-shell/)
- [MariaDB 12.3 Release Notes](https://mariadb.com/docs/release-notes/community-server/12.3/)
