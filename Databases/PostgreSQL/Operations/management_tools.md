# Инструменты управления PostgreSQL

**Актуально для:** PostgreSQL 13–18; pgAdmin 4 v9.x, pg_activity 3.6.x, pgcenter 0.9.x, pgweb 0.17.x, PGlite 0.5.x

## Определения

**Инструменты управления PostgreSQL** — набор программных средств (CLI, TUI, GUI, Web, WASM) для администрирования, мониторинга, отладки и разработки баз данных PostgreSQL.

**Категории:**

- **CLI (Command Line Interface):** стандартные утилиты командной строки: интерактивный терминал `psql` и утилиты обслуживания (`pg_dump`, `pg_basebackup`, `vacuumdb`, `pg_isready` и др.).
- **TUI (Terminal User Interface):** интерактивные консольные инструменты мониторинга в реальном времени (`pg_activity`, `pgcenter`).
- **GUI (Graphical User Interface):** полнофункциональные графические клиенты для разработки и проектирования (`pgAdmin 4`, `DBeaver`, `DataGrip`).
- **Web-интерфейсы:** легковесные браузерные клиенты (`pgweb`).
- **WASM-песочницы:** встраиваемый PostgreSQL прямо в браузер/Node.js (`PGlite`) — для тестирования без установки сервера.

**Предопределённая роль `pg_monitor`** — роль для мониторинга (включает `pg_read_all_settings`, `pg_read_all_stats`, `pg_stat_scan_tables`); детали и выдача прав — в **[Управлении ролями](./role_management.md)**.

## Предпосылки

Для работы с инструментами управления требуются:

1. **Сетевой доступ:** открытый порт 5432 (TCP), локальный Unix-сокет (`/var/run/postgresql`) для утилит на сервере, либо настроенный SSH-туннель до сервера БД.
2. **Конфигурация доступа:** разрешение в `pg_hba.conf` для IP-адреса администратора и корректный метод аутентификации (`scram-sha-256` для TCP, `peer` для локальных подключений) — механика в **[Безопасности и шифровании](../Concepts/security_and_encryption.md)**.
3. **Права доступа:** роль с членством в `pg_monitor` для TUI/мониторинга (с версии 3.0 `pg_activity` работает и без суперпользователя); права владельца БД для GUI-разработки; **суперпользователь** требуется для отладки PL/pgSQL в pgAdmin/DBeaver (см. **[Отладку хранимых объектов](../Concepts/stored_objects_debugging.md)**).
4. **Среда исполнения:** браузер (pgAdmin в web-режиме, pgweb, PGlite). Отдельная JRE **не требуется**: начиная с версии 23.0 каждый официальный пакет DBeaver включает собственный OpenJDK. При установке `pg_activity` через `pip` нужен Python 3.9+ (apt- и PGDG-пакеты ставят зависимости сами).

## Основные концепции

### Выбор инструмента по сценарию

| Сценарий | Рекомендуемый инструмент | Особенности |
| :--- | :--- | :--- |
| Быстрая отладка и скрипты на сервере | **[psql](./console_basics.md)** | Всегда доступен, минимальные накладные расходы; основа автоматизации. |
| Мониторинг «живой» нагрузки | **pg_activity** / **pgcenter** | Визуализация процессов, ожиданий (Wait Events), блокировок и I/O в консоли. |
| Проектирование и разработка | **DBeaver** / **DataGrip** | Визуализация схем, автодополнение, ER-диаграммы, работа с множеством СУБД. |
| Разовый просмотр через браузер | **pgweb** | Один бинарник на Go, ноль зависимостей, запуск за секунды. |
| Песочница без сервера | **PGlite** | Полный PostgreSQL в WASM в браузере или Node.js. |

### Стандартные утилиты кластера

Эти утилиты поставляются вместе с клиентом/сервером PostgreSQL и являются основным инструментарием SRE. Детали — в соответствующих файлах:

| Утилита | Назначение | Подробнее |
| :--- | :--- | :--- |
| `psql` | Интерактивный терминал и выполнение SQL-скриптов | [Консольные основы](./console_basics.md) |
| `createdb` / `dropdb` | Создание/удаление БД (обёртки над `CREATE`/`DROP DATABASE`) | [Управление ролями](./role_management.md) |
| `createuser` / `dropuser` | Создание/удаление ролей (обёртки над `CREATE`/`DROP ROLE`) | [Управление ролями](./role_management.md) |
| `pg_dump` | Логический бэкап одной БД (текстовый или custom/dir/tar формат) | [Стратегии резервного копирования](../../Concepts/backups.md) |
| `pg_dumpall` | Дамп **всех** БД плюс глобальные объекты (роли, табличные пространства) | [Стратегии резервного копирования](../../Concepts/backups.md) |
| `pg_restore` | Восстановление из custom/dir/tar формата `pg_dump` (параллельно, выборочно) | [Стратегии резервного копирования](../../Concepts/backups.md) |
| `pg_basebackup` | Физический побайтовый бэкап всего кластера с работающего сервера (основа PITR и развёртывания реплик) | [Backup and Recovery](../Concepts/backup_and_recovery.md) |
| `pg_verifybackup` | Проверка целостности и пригодности физического бэкапа | [Backup and Recovery](../Concepts/backup_and_recovery.md) |
| `pg_upgrade` | Обновление кластера между мажорными версиями (in-place, fast mode переносит файлы данных) | [Обновление между мажорными версиями](./pg_upgrade.md) |
| `vacuumdb` | `VACUUM`/`ANALYZE` из CLI (обёртка над SQL-командами) | [Планировщик и статистика](../Concepts/planner_internals.md) |
| `reindexdb` / `clusterdb` | `REINDEX` / `CLUSTER` из CLI | документация PostgreSQL |
| `pg_isready` | Проверка готовности сервера: exit code `0` — принимает, `1` — отклоняет (старт), `2` — нет ответа, `3` — параметры неверны. Не требует корректных логина/пароля (неверные значения лишь логируют неудачную попытку) | раздел «Операции и команды» |
| `pg_lsclusters` | Листинг всех кластеров (версия, имя, порт, статус `online`/`down`, владелец, каталоги) — **Debian/Ubuntu**, пакет `postgresql-common`. Опции: `-j` (JSON), `-s` (start.conf), `-h` (без заголовка) | раздел «Операции и команды» |
| `pgbench` | Нагрузочное тестирование (TPC-B-подобный сценарий, свои скрипты) | [pgbench](../../Concepts/pgbench.md) |

### Как инструменты читают права

- **Мониторинг чужих сессий и запросов** в `pg_stat_activity` видна не всем: для просмотра запросов других пользователей нужна роль `pg_monitor` (через `pg_read_all_stats`) или суперпользователь. Без неё TUI покажет только собственные подключения.
- **Системные колонки `pg_activity` (CPU/MEM/READ/WRITE):** доступны только при запуске **на том же сервере**, от имени пользователя, запустившего инстанс (или `root`) — утилита читает `/proc` и системную статистику.
- **`pgcenter`** собирает данные из представлений `pg_stat_*`: базовая статистика доступна всем, полная (включая системные метрики по каждому бэкенду) требует `pg_monitor` или суперпользователя.
- **Останов/отмена запросов** в TUI: свой запрос — любой; чужие сессии — право `pg_signal_backend` (или суперпользователь).

## Практические сценарии

### pgAdmin 4 — универсальный GUI

Самое популярное графическое средство, поставляется в настольной и серверной (Web) версиях; текущая линейка версий — 9.x.

#### Установка в Ubuntu/Debian

```bash
# Импорт ключа репозитория
curl -fsS https://www.pgadmin.org/static/packages_pgadmin_org.pub | sudo gpg --dearmor -o /usr/share/keyrings/packages-pgadmin-org.gpg

# Подключение репозитория (Debian 12/13, Ubuntu 22.04/24.04/26.04)
sudo sh -c 'echo "deb [signed-by=/usr/share/keyrings/packages-pgadmin-org.gpg] https://ftp.postgresql.org/pub/pgadmin/pgadmin4/apt/$(lsb_release -cs) pgadmin4 main" > /etc/apt/sources.list.d/pgadmin4.list && apt update'

# Установка: оба режима — pgadmin4; только desktop — pgadmin4-desktop; только web — pgadmin4-web
sudo apt install pgadmin4-desktop
```

Для **web-режима** после установки обязательно выполнить конфигурацию (задаёт email/пароль администратора, настраивает Apache WSGI):

```bash
sudo /usr/pgadmin4/bin/setup-web.sh
# → доступ: http://127.0.0.1/pgadmin4
```

Конфигурация desktop-версии хранится в `~/.local/share/pgadmin/`.

#### Управление ролями

1. В дереве объекта сервера: **Login/Group Roles** → **Create** → **Login/Group Role**.
2. Вкладка **Definition**: имя, пароль, срок действия пароля (`VALID UNTIL`).
3. Вкладка **Privileges**: право на вход (`Can login?`), создание БД, статус суперпользователя.
4. Вкладка **Membership**: членство в ролях, включая системные (например, `pg_monitor`).

Полная семантика атрибутов и членства (включая опции `ADMIN`/`INHERIT`/`SET` PG 16+) — в **[Управлении ролями](./role_management.md)**.

#### Отладка PL/pgSQL

Пошаговый отладчик в pgAdmin 4 и DBeaver требует **суперпользователя** и установленного расширения `pldebugger` (`plugin_debugger` в `shared_preload_libraries` + перезапуск сервера). Механика и типичные ошибки — в **[Отладке хранимых объектов](../Concepts/stored_objects_debugging.md)**.

### psql — интерактивный терминал

Базовый инструмент: интерактивный ввод, метакоманды (`\dt`, `\d`, `\l`, `\du`, `\x`, `\watch`), выполнение скриптов, переменные, `\copy`. Полное руководство — в **[Консольных основах](./console_basics.md)**; управление пулом соединений — в **[Управлении соединениями](./connection_management.md)**.

### Терминальные интерфейсы (TUI)

#### pg_activity

Аналог `top` для PostgreSQL: активные сессии, ожидания (Wait Events), блокировки, нагрузка на диск. Текущая линейка — 3.6.x.

```bash
# Установка (Debian/Ubuntu; PGDG-пакет — для свежей версии)
sudo apt install pg-activity
# Альтернативы: python3 -m pip install "pg_activity[psycopg]"  или  pipx install "pg_activity[psycopg]"

# Запуск
pg_activity -U postgres
pg_activity -h /var/run/postgresql        # подключение через Unix-сокет
```

- **Без суперпользователя** (с версии 3.0): базовый мониторинг доступен обычной роли; для чужих сессий и запросов — членство в `pg_monitor`.
- **Ключ `I`:** информация об инстансе (версия, хост, интервал обновления).
- **Kill запросов:** отмена/завершение через `pg_cancel_backend`/`pg_terminate_backend` (для чужих сессий требуется `pg_signal_backend`).
- Колонки CPU/MEM/READ/WRITE — только при запуске на сервере от имени пользователя инстанса или `root`.

#### pgcenter

Go-утилита для анализа статистики из системных представлений `pg_stat_*` в реальном времени; текущая линейка — 0.9.x. Готовые пакеты DEB/RPM/APK — на странице релизов GitHub (`lesovsky/pgcenter`), образ Docker — `lesovsky/pgcenter`.

```bash
pgcenter top -h 127.0.0.1 -U postgres -d postgres
```

- **Подкоманды:** `top` (top-like просмотр), `record` (сбор статистики в файл), `report` (отчёт по файлу), `profile` (профайлер Wait Events), `config` (установка/удаление stats-схемы).
- **`Shift+S`:** системные метрики по каждому бэкенду (CPU, I/O, IO-wait) рядом с текстом запроса — быстрая классификация «CPU-bound или IO-bound».
- **«Poor man's monitoring»:** `pgcenter record` непрерывно собирает статистику в файлы, `pgcenter report` строит пост-мортем-отчёт — полезно для инцидентов без внешней системы мониторинга.

### Профессиональные IDE и клиенты

- **DBeaver Community** (бесплатная, Eclipse-платформа):
  - Поддержка PostgreSQL и десятков других СУБД (реляционных и NoSQL).
  - Визуальный конструктор запросов, ER-диаграммы, редактор данных, экспорт в 10+ форматов.
  - Форматы: `.deb`, `.rpm`, `.tar.gz`, snap, flatpak (Linux x86_64/aarch64); OpenJDK включён в пакет — системная Java не нужна. Настройки хранятся в `DBeaverData` в домашнем каталоге.
- **DataGrip (JetBrains)** (коммерческий):
  - Лучшее в классе автодополнение и инспекция SQL-кода.
  - Глубокая интеграция с Git, инструменты рефакторинга схем.

### Веб-интерфейсы

- **pgweb** (текущая версия 0.17.x, поддержка PostgreSQL 9.6+): современный, сверхлегкий (один бинарный файл на Go, ноль зависимостей) браузер БД. Идеален для быстрого развертывания в Docker-окружении (**[Docker-деплой](./docker_deployment.md)**) и для разовой диагностики.

```bash
pgweb                                            # запуск: http://localhost:8081
pgweb --host 127.0.0.1 --port 5432 --user app --db mydb
pgweb --url postgres://user:password@host:5432/mydb?sslmode=require
pgweb --sessions                                 # несколько подключений одновременно
pgweb --auth-user admin --auth-pass secret       # HTTP Basic Auth перед UI
```

Возможности: несколько сессий, нативные SSH-туннели, выполнение произвольного SQL, экспорт результатов в CSV/JSON/XML, история запросов, закладки серверов. Флаг `--listen` меняет HTTP-порт (дефолт 8081), `--bind` — адрес прослушивания.

- **PGlite (Electric)** (текущая линейка 0.5.x, статус Alpha, двойная лицензия Apache-2.0/PostgreSQL License): полноценный PostgreSQL в WASM (~3 MB gzipped) для браузера, Node.js, Bun и Deno. Не виртуальная машина — настоящий сервер в single-user mode.

```bash
npm install @electric-sql/pglite
```

```javascript
import { PGlite } from '@electric-sql/pglite'

const db = new PGlite()                 // in-memory (браузер/Node)
// const db = new PGlite('./pgdata')    // persist на файловой системе (Node/Bun/Deno)
// const db = new PGlite('idb://my-pgdata')  // persist в IndexedDB (браузер)
await db.query("SELECT 'Hello world' AS message;")
```

Динамическая загрузка расширений, включая `pgvector` и PostGIS. Подходит для песочниц, демо и локальной разработки — **не** для production-нагрузки.

## Операции и команды

| Инструмент | Команда | Назначение |
| :--- | :--- | :--- |
| `pg_isready` | `pg_isready -h 127.0.0.1 -p 5432` | Проверка готовности сервера (см. коды возврата выше) |
| `pg_lsclusters` | `pg_lsclusters` / `pg_lsclusters -j` | Статус всех кластеров (Debian/Ubuntu), опционально JSON |
| `pg_activity` | `pg_activity -U postgres` | Live-мониторинг сессий, wait events, блокировок |
| `pgcenter` | `pgcenter top -h 127.0.0.1 -U postgres` | Top-like статистика из `pg_stat_*` |
| `pgcenter record` | `pgcenter record -h 127.0.0.1 -U postgres` | Сбор статистики в файл для пост-мортема (`pgcenter report`) |
| `pgweb` | `pgweb --host 127.0.0.1 --user app --db mydb` | Web-браузер БД (порт UI 8081) |
| pgAdmin web | `sudo /usr/pgadmin4/bin/setup-web.sh` | Конфигурация web-режима после установки |
| `pg_dump` | `pg_dump -Fc -f /backup/mydb.dump mydb` | Логический бэкап — [бэкапы](../../Concepts/backups.md) |
| `pg_basebackup` | `pg_basebackup -D /backup/full -P -X stream` | Физический бэкап — [backup and recovery](../Concepts/backup_and_recovery.md) |
| `vacuumdb` | `vacuumdb --analyze-only -d mydb` | Обновление статистики — [планировщик](../Concepts/planner_internals.md) |
| `pgbench` | `pgbench -c 10 -j 2 -T 60 mydb` | Нагрузочное тестирование — [pgbench](../../Concepts/pgbench.md) |

## Валидация и проверка

Для проверки работоспособности выбранного инструмента выполните следующие шаги:

1. **Сервер отвечает:**
   ```bash
   pg_isready -h 127.0.0.1 -p 5432
   # → 127.0.0.1:5432 - accepting connections
   echo $?   # → 0
   ```
2. **Кластеры в порядке (Debian/Ubuntu):**
   ```bash
   pg_lsclusters
   # → Ver Cluster Port Status Owner    Data directory               Log file
   # → 18  main    5432 online postgres /var/lib/postgresql/18/main /var/log/postgresql/postgresql-18-main.log
   ```
3. **Права мониторинга:** `SELECT pg_has_role(current_user, 'pg_monitor', 'MEMBER');` → `t` для TUI с полным доступом к чужим сессиям.
4. **Тест соединения и прав:** простой запрос `SELECT 1;` без ошибок `Connection Refused`/`permission denied`; в GUI — раскрытие дерева схем и таблиц (в psql — `\dt`).
5. **pgAdmin web-режим:** `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/pgadmin4` → `200` или `302` (редирект на login).
6. **pgweb:** в консоли после запуска — строка с URL; UI открывается и подключается к целевой БД.

## Устранение неполадок

| Ошибка | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Connection Refused** | Сервер не слушает порт или закрыт Firewall. | Проверьте `listen_addresses` в `postgresql.conf` и настройки `ufw`/`iptables`; локально — Unix-сокет (`pg_isready -h /var/run/postgresql`). |
| **FATAL: no pg_hba.conf entry** | Доступ для данного IP/пользователя не разрешён. | Добавьте запись в `pg_hba.conf` и выполните `SELECT pg_reload_conf();`. |
| **SSH Tunnel Failed** | Некорректные ключи или запрет форвардинга портов. | Проверьте `AllowTcpForwarding yes` в `/etc/ssh/sshd_config` на сервере. |
| **Slow GUI Refresh** | Огромное количество объектов (таблиц/схем) в БД. | В настройках DBeaver/pgAdmin включите фильтрацию схем (Connection Filters). |
| **pgAdmin web не открывается после установки** | Не выполнен `setup-web.sh` или Apache не перезапущен. | Запустите `sudo /usr/pgadmin4/bin/setup-web.sh` и проверьте порт Apache. |
| **DBeaver: «Incompatible JVM»** | Старая системная Java конфликтует (актуально для старых сборок). | Удалите системную Java или укажите `-vm <путь>/bin` в `dbeaver.ini`; в сборках 23.0+ используется встроенный OpenJDK. |
| **pg_activity: пустые CPU/MEM/IO** | Утилита запущена не на сервере или не от пользователя инстанса. | Запустите на сервере от имени пользователя, запустившего PostgreSQL (или `root`). |
| **pg_activity/pgcenter: не видны чужие сессии/запросы** | Нет прав на `pg_stat_activity` чужих пользователей. | Выдайте `GRANT pg_monitor TO <role>` (см. [роли](./role_management.md)). |
| **FATAL: too many connections for role** | Достигнут `CONNECTION LIMIT` роли. | Поднять лимит (`ALTER ROLE ... CONNECTION LIMIT n`) или оптимизировать пулинг — [PgBouncer](./pgbouncer_setup.md). |

## Лучшие практики

1. **Мониторинг через `pg_monitor`, а не суперпользователя:** выдайте отдельной сервисной роли членство в `pg_monitor` — TUI и утилиты статистики получат полный доступ без прав на изменение данных.
2. **GUI — для исследования и разработки, автоматизация — через CLI:** `psql` и утилиты обслуживания внятно встраиваются в скрипты, CI и cron (пример планировщика — в [Таймерах systemd](../../../Linux/Core/systemd/timers.md)), GUI — нет.
3. **Версионирование `pg_dump`:** утилита может дампить серверы **старше** своей версии (до 9.2), но **откажется дампить сервер новее своей мажорной версии**. Дамп загружается в серверы новее `pg_dump`; загрузка в более старый сервер не гарантируется. Для миграций — [логическая миграция](./logical_backup_migration.md).
4. **SSH-туннели вместо открытия 5432 наружу:** pgweb, pgAdmin и IDE поддерживают туннели нативно (pgweb — флаг/настройки подключения).
5. **Пароли — в `~/.pgpass` с правами `0600`**, а не в закладках GUI в открытом виде: [Управление соединениями](./connection_management.md).
6. **Фильтрация схем** в GUI на хостах с сотнями схем — иначе раскрытие дерева блокирует инструмент.
7. **Обновляйте клиентские инструменты** (pgAdmin, pgweb, DBeaver) вместе с сервером: они получают исправления безопасности и поддержку новых возможностей сервера (например, pgweb 0.17 добавил поддержку PostgreSQL 18).
8. **PGlite/pgweb — для песочниц и разведки:** ни один из них не заменяет контроль доступа сервера; pgweb при доступе по сети защищайте HTTP Basic Auth (`--auth-user`/`--auth-pass`) и привязкой к localhost.

## Очистка и откат

```bash
# Удаление pgAdmin 4 вместе с репозиторием
sudo apt purge pgadmin4-desktop pgadmin4-web pgadmin4
sudo rm -f /etc/apt/sources.list.d/pgadmin4.list /usr/share/keyrings/packages-pgadmin-org.gpg
sudo apt update

# TUI-инструменты
sudo apt purge pg-activity
rm -f "$(command -v pgcenter)" "$(command -v pgweb)" 2>/dev/null   # бинарники с GitHub releases

# PGlite (Node-проект)
npm uninstall @electric-sql/pglite
```

Откат изменений, сделанных через GUI (удалённые роли, изменённые привилегии), — через SQL-скрипты: восстановление из `pg_dumpall` (глобальные объекты) или повторный `GRANT` согласно [управлению ролями](./role_management.md).

## Дополнительная информация

### Сравнение функциональности

| Функция | psql | pg_activity | pgcenter | pgAdmin | DBeaver |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Просмотр данных | Да | Нет | Нет | Да | Да |
| Мониторинг Wait Events | Вручную (`pg_stat_activity`) | Авто | Авто | Да | Нет |
| Системные метрики по бэкендам | Нет | Да (на сервере) | Да (`Shift+S`) | Нет | Нет |
| Пост-мортем отчёты | Нет | Нет | Да (`record`/`report`) | Нет | Нет |
| Визуальный ER-дизайн | Нет | Нет | Нет | Да | Да |
| Работа через SSH-туннель | Да | Да | Да | Да | Да |

### Связанные документы

- [Основы работы в psql](./console_basics.md) — мастерство владения CLI.
- [Управление ролями и правами](./role_management.md) — `pg_monitor`, атрибуты, членство.
- [Безопасность и шифрование](../Concepts/security_and_encryption.md) — `pg_hba.conf`, методы аутентификации.
- [Управление соединениями](./connection_management.md) — `~/.pgpass`, libpq-переменные, пулинг.
- [Наблюдаемость PostgreSQL](./observability.md) — метрики, трассировка, платформенный мониторинг.
- [Стратегии резервного копирования](../../Concepts/backups.md) и [Backup and Recovery](../Concepts/backup_and_recovery.md) — `pg_dump`/`pg_restore`/`pg_basebackup`.
- [pgbench](../../Concepts/pgbench.md) — нагрузочное тестирование.
- [Установка Ubuntu](./installation_ubuntu.md) — сервер и клиент из PGDG.
- [Docker-деплой](./docker_deployment.md) — запуск инструментов и сервера в контейнерах.
- [Отладка хранимых объектов](../Concepts/stored_objects_debugging.md) — `pldebugger` и отладка в pgAdmin/DBeaver.
