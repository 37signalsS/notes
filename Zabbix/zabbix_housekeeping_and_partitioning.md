# Zabbix — Housekeeper и партиционирование БД

**Актуально для:** Zabbix 7.0 LTS / 7.4

Документ описывает механизмы очистки устаревших данных в базе Zabbix: встроенный Housekeeper, партиционирование через TimescaleDB (PostgreSQL) и через community-скрипты (MySQL/MariaDB). Настройка самой БД — в **[Установке](./installation.md)**.

---

## Определения

* **Housekeeper** — процесс Zabbix, периодически удаляющий устаревшие данные (history, trends, events, alerts и др.) согласно срокам хранения.
* **HousekeepingFrequency** — период (часы), с которым запускается Housekeeper. По умолчанию `1`.
* **MaxHousekeeperDelete** — максимальное число записей, удаляемых за один цикл Housekeeper на одну задачу. По умолчанию `5000`.
* **Housekeeper table** — служебная таблица `housekeeper`, в которую сервер помещает строки к удалению (в отличие от прокси; см. ниже).
* **Partition (партиция)** — секция таблицы, соответствующая временному диапазону. Удаление устаревших данных сводится к `DROP PARTITION`, что в разы дешевле построчного удаления.
* **TimescaleDB hypertable** — таблица TimescaleDB, автоматически разбитая на чанки (chunks) по времени.
* **Chunk** — внутренняя единица хранения TimescaleDB; единица сжатия и удаления.
* **Compression (сжатие)** — упаковка чанков TimescaleDB для экономии места.

---

## Основные концепции

### Как работает Housekeeper

Housekeeper удаляет данные, у которых срок хранения истёк. Сроки задаются:

* **глобально** — Administration → Housekeeping (для всей системы);
* **на уровне элемента данных** — поля `History storage period` и `Trend storage period` (переопределяют глобальные, если включены соответствующие флаги override).

Особенности сервера и прокси различаются:

* **Сервер:** использует таблицу `housekeeper` и удаляет данные **партиями**, ограниченными `MaxHousekeeperDelete` за цикл. Это защищает БД от блокировки длинным `DELETE`.
* **Прокси:** своего параметра `MaxHousekeeperDelete` не применяет; удаляет устаревшие данные **целиком за один цикл** (частоту задаёт `HousekeepingFrequency`, а объёмные лимиты связаны с `ProxyLocalBuffer`/`ProxyOfflineBuffer`).

Построчное удаление больших объёмов — тяжёлая операция для БД, поэтому на крупных инсталляциях переходят к партиционированию.

### Партиционирование: зачем

При построчном удалении СУБД вынуждена удалять миллионы строк и поддерживать индексы. При партиционировании устаревшие данные лежат в отдельной секции, которую можно **отбросить целиком** — операция почти мгновенная и не создаёт нагрузки.

### TimescaleDB (PostgreSQL) — штатный путь

TimescaleDB — расширение PostgreSQL, превращающее крупные таблицы Zabbix в hypertables с чанками. Установочный скрипт PostgreSQL-схемы Zabbix — `postgresql/timescaledb/schema.sql` (или `timescaledb.sql` в зависимости от версии пакета) — помимо создания hypertables выставляет параметры housekeeping:

* `Override item history period` — включён;
* `Override item trend period` — включён;
* `Enable compression` — включено;
* `Compress records older than` — `7d`.

Важно:

* Чтобы Housekeeper **удалял** сжатые данные, оба override-флага (history и trends) должны быть включены. Иначе сжатые чанки не удаляются, а в Housekeeping и System information появляются предупреждения о неверной конфигурации.
* Параметр `Compress records older than` не может быть меньше **7 дней**. Сжатые чанки неизменяемы, поэтому «поздние» данные старше этого порога (например, задержанные прокси) **отбрасываются**.
* Ограничения compression: изменения в сжатых чанках (inserts/deletes/updates) и изменение схемы сжатых таблиц запрещены.
* Включение/отключение сжатия не действует мгновенно: компрессией управляет Housekeeper, изменения применяются в течение до **2 × HousekeepingFrequency часов**.
* При обновлении со старых версий Zabbix сжатие по умолчанию **не** включается.

### MySQL/MariaDB — только community-скрипты

Нативного партиционирования (аналога TimescaleDB) для MySQL/MariaDB в Zabbix **нет**. Применяются внешние решения:

* **Хранимые процедуры** (наборы вида `partition_create/drop/verify/maintenance/maintenance_all`, например репозиторий `incama/Zabbix-Mysql-Partitioning`). Процедура `partition_maintenance_all(SCHEMA_NAME VARCHAR(32))` в этом репозитории охватывает `history`, `history_log`, `history_str`, `history_text`, `history_uint`, `trends`, `trends_uint` — таблицу `history_bin` (7.0+) нужно добавить в неё вручную.
* **Perl-скрипт** `mysql_zbx_part.pl` (Opensource ICT Solutions), запускаемый по cron.

Общие требования и ограничения:

* Партиционируются таблицы `history*` (по дням) и `trends*` (по месяцам): `history`, `history_uint`, `history_str`, `history_text`, `history_log`, `history_bin` (с 7.0), `trends`, `trends_uint`.
* Должен быть включён планировщик событий MySQL: `event_scheduler=ON` (при использовании MySQL event), либо настроен cron.
* **Housekeeper для history/trends в веб-интерфейсе необходимо отключить** — иначе он конфликтует с партиционированием.
* **Таблицы `events` и `alerts` партиционировать нельзя** (ограничение MySQL: партиционирование несовместимо с external keys) — их очистку оставляют Housekeeper.
* Создание партиций на большой БД — длительная операция (может идти днями); выполнять в `tmux`/screen, желательно после остановки сервера или на копии БД.
* При **крупном обновлении Zabbix** (для 6.0+ — обновление схемы БД) партиционирование **снимается** и его нужно настроить заново.
* Ошибка управления партициями приводит к `Table has no partition for value ...` (`[Z3005]`) и остановке записи данных — настраивать аккуратно.

---

## Практические сценарии

### Предварительные требования

* Доступ к БД Zabbix с правами изменения схемы (для партиционирования) и к файлам конфигурации сервера.
* Понимание требуемых сроков хранения (сколько дней истории, сколько месяцев трендов).
* Для TimescaleDB — PostgreSQL с установленным расширением TimescaleDB (см. **[Установку](./installation.md)**).

### Сценарий 1. Настройка Housekeeper в интерфейсе

Administration → Housekeeping:

* `History` → включить период, задать `Keep history` (например, `90d`).
* `Trends` → `Keep trends` (например, `365d`).
* `Events` / `Alerts` — задать сроки хранения событий/оповещений.

На уровне элемента (Item → History storage period / Trend storage period) можно переопределить срок для конкретной метрики, включив соответствующий флаг override.

### Сценарий 2. Включение TimescaleDB

```bash
# Для Zabbix 7.0 — применить скрипт после инициализации схемы PostgreSQL
cat /usr/share/zabbix-sql-scripts/postgresql/timescaledb/schema.sql | \
  sudo -u postgres psql -d zabbix
# → CREATE EXTENSION / CREATE TABLE / SELECT ... (создание hypertables)
```

Затем в Administration → Housekeeping:
* включить `Enable compression`;
* `Compress records older than` = `7d`;
* убедиться, что включены оба override (history и trends).

### Сценарий 3. Партиционирование MySQL/MariaDB (event scheduler)

1. Включить планировщик:

```ini
; /etc/mysql/my.cnf
[mysqld]
event_scheduler=ON
```

2. Применить скрипт хранимых процедур (создаёт `partition_create`, `partition_maintenance` и т. д.) и инициализировать таблицу управления партициями.
3. Создать событие периодического обслуживания:

```sql
CREATE EVENT zbx_partitioning
ON SCHEDULE EVERY 12 HOUR
DO CALL partition_maintenance_all('zabbix');
```

4. Отключить Housekeeper для history и trends: Administration → Housekeeping → снять соответствующие галочки.

### Сценарий 4. Партиционирование через Perl-скрипт (cron)

```bash
# Ежедневно в 03:30, срок: history 60 дней, trends 12 месяцев
30 03 * * * /usr/bin/perl /opt/zabbix/mysql_zbx_part.pl >/tmp/zbx_part.log 2>&1
```

В скрипте период хранения задаётся в хэше `$tables` (`keep_history`). Помните: с 7.0 присутствует таблица `history_bin` (в старых версиях строку нужно закомментировать).

### Валидация

```sql
-- Размеры крупнейших таблиц (MySQL/MariaDB)
SELECT table_name, ROUND(data_length/1024/1024) AS data_mb,
       ROUND(index_length/1024/1024) AS idx_mb
FROM information_schema.tables
WHERE table_schema='zabbix'
ORDER BY data_length DESC LIMIT 10;

-- Проверка, что таблица разбита на партиции (аналог verify)
SELECT table_name, partition_name, partition_description
FROM information_schema.partitions
WHERE table_schema='zabbix' AND table_name='history_uint'
ORDER BY partition_ordinal_position;
```

```bash
# TimescaleDB: список чанков и их сжатие
sudo -u postgres psql -d zabbix -c "SELECT hypertable_name, pg_size_pretty(total_bytes) FROM timescaledb_information.hypertables;"
# → строки с hypertable history/trends и их размером
```

---

## Операции и команды

```bash
# Запустить Housekeeper вне расписания (runtime control)
zabbix_server -R housekeeper_execute
# → "command sent successfully"

# Другая полезная команда: перечитать конфигурацию (не относится к HK, для полноты)
zabbix_server -R config_cache_reload
```

| Параметр | Где | Назначение | По умолчанию |
|---|---|---|---|
| `HousekeepingFrequency` | `zabbix_server.conf` | Период запуска Housekeeper, часы | `1` |
| `MaxHousekeeperDelete` | `zabbix_server.conf` | Лимит удаляемых записей за цикл на задачу | `5000` |
| `HousekeepingFrequency` | `zabbix_proxy.conf` | Период очистки на прокси, часы | `1` |
| Override item history/trend period | UI (Housekeeping) | Удаление сжатых данных TimescaleDB | выкл (кроме новых установок TimescaleDB) |
| Compress records older than | UI (Housekeeping) | Порог сжатия, не < 7d | `7d` |

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| БД растёт, Housekeeper «не успевает» | Построчное удаление медленнее поступления данных | Уменьшить сроки хранения; перейти на TimescaleDB/партиционирование |
| Предупреждение о неверной конфигурации в Housekeeping | Для сжатых чанков не включены override history/trends | Включить оба override |
| `Table has no partition for value ...` (`[Z3005]`) | Партиции не создаются / event scheduler выключен | Включить `event_scheduler=ON`/cron, исправить скрипт |
| Данные пропадают раньше срока | `Compress records older than` меньше реальной задержки прокси | Увеличить порог; учесть отбрасывание поздних данных |
| После крупного обновления партиционирование сломалось | Обновление схемы БД снимает партиции | Пересоздать партиции после апгрейда |
| Housekeeper VS партиционирование конфликтуют | HK для history/trends не отключён | Отключить Housekeeper для этих таблиц в UI |
| Прокси долго чистит локальную БД | Прокси удаляет за один цикл без `MaxHousekeeperDelete` | Учесть при планировании диска прокси |

---

## Лучшие практики

* **TimescaleDB — предпочтительный путь** на PostgreSQL: штатная поддержка, сжатие, дешёвое удаление чанков.
* **MySQL/MariaDB — планировать партиционирование заранее**, до роста БД: создание партиций на большой таблице очень долгое.
* **Отключать Housekeeper для history/trends** при использовании партиционирования — во избежание двойной нагрузки и конфликтов.
* **Сроки хранения задавать осознанно:** history — дни (детализация графиков), trends — месяцы/годы (агрегаты).
* **Использовать item-level override** только там, где действительно нужны особые сроки — иначе растёт объём.
* **Мониторить Housekeeper и размер БД** (см. **[Тюнинг](./zabbix_troubleshooting_and_performance_tuning.md)**), предупреждения в System information.
* **Для `events`/`alerts`** оставлять очистку Housekeeper — их партиционировать нельзя.
* **Планировать время обслуживания партиций** вне пиков (например, ночью), а также следить за `event_scheduler`.

---

## Дополнительная информация

### См. также

* [Zabbix — Установка](./installation.md) — создание схемы БД, TimescaleDB, PostgreSQL/MySQL.
* [Zabbix — тюнинг и устранение неисправностей](./zabbix_troubleshooting_and_performance_tuning.md) — нагрузка БД, размеры кэшей.
* [Zabbix — внутреннее устройство и архитектура процессов](./additional_info.md) — процессы Housekeeper сервера и прокси.
* [Zabbix — мониторинг баз данных](./zabbix_database_monitoring.md) — контроль состояния СУБД Zabbix.

### Источники и ссылки

* Zabbix documentation: [TimescaleDB setup](https://www.zabbix.com/documentation/7.0/en/manual/appendix/install/timescaledb)
* Zabbix documentation: [Housekeeping](https://www.zabbix.com/documentation/7.0/en/manual/web_interface/frontend_sections/administration/housekeeping)
* Zabbix documentation: [Configuration parameters: Zabbix server](https://www.zabbix.com/documentation/7.0/en/manual/appendix/config/zabbix_server)
* Zabbix community: [Partitioning MySQL database](https://blog.zabbix.com/partitioning-a-zabbix-mysql-database-with-perl-or-stored-procedures/13531/)
* GitHub: [incama/Zabbix-Mysql-Partitioning](https://github.com/incama/Zabbix-Mysql-Partitioning)
