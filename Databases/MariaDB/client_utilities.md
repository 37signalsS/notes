# Клиентские утилиты MariaDB

## Определения

**Клиентские утилиты MariaDB** — это набор консольных инструментов, предназначенных для администрирования сервера, управления данными, выполнения резервного копирования и анализа производительности. В MariaDB 12.3 LTS утилиты полностью интегрированы с современными протоколами безопасности и AI-интерфейсами.

**MariaDB Shell (`mariadb-shell`)** — интерактивный клиент нового поколения, поддерживающий три режима работы: **SQL**, **JavaScript** и **Python**. Является основным инструментом для работы с AI (через протокол MCP) и управления кластерами.

**Point-in-Time Recovery (PITR)** — процесс восстановления базы данных до точно определенного момента времени в прошлом с использованием полных бэкапов и бинарных логов.

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
-   **Файлы параметров:** Использование флага `--defaults-extra-file=/path/to/creds.cnf`.
-   **Unix Socket:** Локальный вход через `sudo` без пароля (актуально для `mariadb` и `mariadb-admin`).
-   **MARIADB_HISTFILE:** Переменная окружения для выноса истории команд в защищенное место.

## Практические сценарии

### Жизненный цикл сервера (mariadb-admin)

Утилита используется для быстрых административных действий без входа в интерактивный режим.

```bash
# Проверка доступности сервера
mariadb-admin -u root ping

# Получение краткого статуса (Uptime, Threads, Questions)
mariadb-admin status

# Безопасная перезагрузка логов (Flush logs)
mariadb-admin flush-logs

# Вывод текущих значений системных переменных
mariadb-admin variables | grep "innodb_buffer_pool"
```

### Консистентное резервное копирование (mariadb-dump)

Для обеспечения целостности данных (Consistency) при дампе транзакционных таблиц (InnoDB) необходимо использовать специальные флаги.

```bash
# Создание консистентного дампа большой БД
mariadb-dump --user=admin --password \
    --single-transaction \  # Не блокирует чтение/запись в InnoDB
    --routines --events \    # Включает процедуры и события
    --triggers \
    --master-data=2 \       # Записывает позицию бинарного лога (для репликации)
    app_db > app_db_full.sql
```

### Анализ и исправление таблиц (mariadb-check)

Используется при подозрении на повреждение индексов или после некорректного завершения работы сервера.

```bash
# Проверка всех баз данных на ошибки
mariadb-check --all-databases

# Оптимизация конкретной базы (дефрагментация индексов)
mariadb-check --optimize app_db

# Попытка автоматического восстановления поврежденных таблиц
mariadb-check --repair app_db
```

### Восстановление данных через PITR (mariadb-binlog)

Сценарий: случайное удаление таблицы в 10:15 утра. Бэкап был сделан в 00:00.

```bash
# 1. Восстанавливаем полный бэкап
mariadb -u root < backup_00_00.sql

# 2. Находим позицию в бинарном логе до момента ошибки
# Используем GTID для точности в MariaDB 12.3
mariadb-binlog --start-datetime="2026-08-17 00:00:00" \
               --stop-datetime="2026-08-17 10:14:59" \
               --base64-output=DECODE-ROWS \
               /var/lib/mysql/binlog.000005 | mariadb -u root
```

### Продвинутая автоматизация в MariaDB Shell

MariaDB Shell в режиме Python позволяет создавать сложные скрипты мониторинга.

```python
# mariadb-shell --py
import mariadb_shell
session = mariadb_shell.get_default_session()

# Анализ фрагментации всех таблиц InnoDB
tables = session.run_sql("SELECT table_schema, table_name, data_free FROM information_schema.tables WHERE engine='InnoDB' AND data_free > 0")
for row in tables.fetch_all():
    print(f"Table {row[0]}.{row[1]} has {row[2]} bytes of free space")
```

### Интеграция с AI (MCP Protocol)

MariaDB Shell (12.3+) поддерживает взаимодействие с LLM для анализа схем данных.

```bash
# Запуск Shell с активацией контекста для AI
mariadb-shell --ai-assist --ai-model=qwen-2.5-coder

# В режиме AI можно спросить:
# > "Проанализируй структуру таблицы users и предложи индексы для ускорения поиска по email"
```

## Устранение неполадок (Troubleshooting)

### Ошибка: `mariadb-dump: Got error: 1045`
-   **Причина:** Неверные учетные данные.
-   **Решение:** Проверьте `~/.my.cnf` или используйте `--defaults-extra-file`. Убедитесь, что у пользователя есть права `SELECT` и `LOCK TABLES`.

### Ошибка: `mariadb-upgrade: Upgrade failed`
-   **Причина:** Нехватка прав или запущенный процесс `mariadb-upgrade` от другого пользователя.
-   **Решение:** Запускайте утилиту через `sudo` и проверьте, что сервер находится в режиме `read_only=OFF`.

### Проблемы с `mariadb-binlog`
-   **Ошибка:** `Could not find target log file`.
-   **Решение:** Проверьте путь в `mariadb-binlog.index`. Убедитесь, что логи не были удалены политикой `expire_logs_days`.

## Дополнительная информация

### См. также
- **[Конфигурация MariaDB](configuration.md)** — настройка путей и прав доступа для утилит.
- **[Резервное копирование MariaDB](backup_and_recovery.md)** — глубокий разбор `mariadb-backup` (физический бэкап).
- **[Безопасная установка СУБД](../installation_security.md)** — принципы защиты конфигурационных файлов с паролями.
- **[Официальный репозиторий MariaDB Shell](https://github.com/mariadb-corporation/mariadb-shell)**
