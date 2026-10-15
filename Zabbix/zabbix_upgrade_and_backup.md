# Zabbix — обновление и резервное копирование

**Актуально для:** Zabbix 7.0 LTS / 7.4

Документ описывает процедуры обновления Zabbix (major и minor), резервного копирования и восстановления базы данных и конфигурации. Схема БД и её настройка — в **[Установке](./installation.md)**, вопросы партиционирования — в **[Housekeeper и партиционировании](./zabbix_housekeeping_and_partitioning.md)**.

---

## Определения

* **LTS (Long Term Support)** — версия с длительной поддержкой (для 7.0 — до 2029). Обновление между LTS выполняют реже и планово.
* **Upgrade (обновление)** — переход на новую версию; при major-обновлении включает автоматическое обновление схемы БД при первом запуске.
* **Mandatory / optional database version** — обязательная и необязательная версия схемы БД, которые Zabbix сравнивает при старте.
* **Database upgrade patches** — SQL-патчи, применяемые сервером автоматически для приведения схемы к требуемой версии.
* **Configuration backup** — резервная копия конфигурации Zabbix (хосты, шаблоны, триггеры) через export/import, независимо от БД.

---

## Основные концепции

### Пути обновления

Прямое обновление до Zabbix **7.0.x** возможно с версий: **6.4.x, 6.2.x, 6.0.x, 5.4.x, 5.2.x, 5.0.x, 4.4.x, 4.2.x, 4.0.x, 3.4.x, 3.2.x, 3.0.x, 2.4.x, 2.2.x, 2.0.x**. С более старых — по документации соответствующей версии.

Прямое обновление до **7.4.x** дополнительно допускает промежуточные линии 7.2.x, 7.0.x.

### Автоматическое обновление схемы БД

При старте новой версии сервер:

1. Сообщает текущую (mandatory/optional) и требуемую версию БД в лог.
2. Если текущая mandatory-версия **старше** требуемой — автоматически выполняет SQL-патчи.
3. Пишет в лог старт, прогресс (в процентах) и завершение: `database upgrade fully completed`.
4. Если патч не выполнился — сервер **не запустится**. Также сервер не запустится, если mandatory-версия БД **новее** требуемой.

```default
8673:20161117:104750.259 current database version (mandatory/optional): 03040000/03040000
8673:20161117:104750.259 required mandatory version: 03040000
```

### Обновление между minor-версиями

Обновление внутри одной линии (например, 7.0.1 → 7.0.3) выполняется **теми же действиями**, что и major-обновление, но **схема БД не меняется**.

### Критические изменения по версиям

| Из версии | Для 7.0 | Ключевые изменения |
|---|---|---|
| 6.4.x | 7.0 | Минимум PHP повышен до **8.0.0**; асинхронные поллеры для `agent`, `http agent`, `snmp walk/get`; отдельная таблица для прокси; изменился путь конфигурации Windows-агента; Oracle DB объявлена устаревшей; удалён старый числовой (float) тип значения |
| 6.2.x | 6.4 / 7.0 | Минимум MySQL повышен до **8.0.30**; требуется библиотека `libevent_pthreads`; прокси с SQLite3 при первом запуске после обновления **удаляет старую БД прокси вместе с историей** и создаёт новую |
| 6.0.x | 6.2 / 6.4 / 7.0 | Минимум PHP повышен до 7.4.0; при обновлении создаются детерминированные триггеры; при включённом binary logging для MySQL/MariaDB нужны superuser-права или `log_bin_trust_function_creators = 1` |

### Порядок обновления компонентов

Для минимизации простоя и потерь данных:

1. Остановить, обновить и запустить **Zabbix Server**.
2. Затем поочерёдно остановить, обновить и запустить **прокси**.

Во время простоя сервера **работающие прокси продолжают сбор данных** и, когда сервер поднимется, передадут накопленное. Устаревшие (не обновлённые) прокси остаются частично работоспособными: сбор данных, удалённые команды, немедленная проверка значений — работают, но **обновление конфигурации отключено**, и они работают со старой конфигурацией. Проблемы, возникшие во время простоя сервера, генерируют уведомления только после запуска обновлённого сервера.

Совместимость прокси: сервер полностью поддерживает прокси своего major-релиза, а также прокси не старше предыдущего LTS — с ограниченной функциональностью.

### Особенности TimescaleDB и пересоздание партиций

* При обновлении **TimescaleDB со сжатием** схема БД обновляется **вручную** (см. раздел upgrade notes для соответствующей версии).
* При крупном обновлении, затрагивающем схему БД (для 6.0+ — переход на primary keys), **партиционирование MySQL/MariaDB снимается** и его нужно настроить заново (см. **[Housekeeper и партиционирование](./zabbix_housekeeping_and_partitioning.md)**).

### Резервное копирование

Резервировать нужно три уровня:

1. **База данных** — содержит и конфигурацию, и данные. Крупные таблицы `history*`, `trends*`, `events` можно **исключить** из дампа, чтобы уменьшить объём и ускорить бэкап; при восстановлении они пересоздаются.
2. **Файлы конфигурации и скрипты:**
   * `/etc/zabbix/*` (server, proxy, agent, а также symlink на конфиг фронтенда);
   * внешние скрипты `/usr/lib/zabbix/externalscripts/`;
   * alert-скрипты `/usr/lib/zabbix/alertscripts/`;
   * конфиги веб-сервера: `/etc/httpd/conf.d/zabbix.conf`, `/etc/php-fpm.d/zabbix.conf` (пути зависят от дистрибутива).
3. **Конфигурация через export/import** — экспорт шаблонов/хостов в YAML/XML/JSON; удобно для точечного восстановления и под контроль версий (Monitoring as Code, см. **[API и автоматизация](./zabbix_api_automation.md)**).

---

## Практические сценарии

### Предварительные требования

* Резервная копия БД (обязательно) и конфигурации.
* Достаточно свободного места на диске (для дампа и для патчей схемы).
* Совместимые версии ПО: PHP, MySQL/MariaDB, PostgreSQL (см. таблицу критических изменений).
* Окно обслуживания (при больших БД обновление схемы идёт долго).

### Сценарий 1. Резервное копирование БД

MySQL/MariaDB (с исключением больших таблиц):

```bash
mysqldump -uzabbix -p --single-transaction --quick \
  --ignore-table=zabbix.history --ignore-table=zabbix.history_uint \
  --ignore-table=zabbix.history_str --ignore-table=zabbix.history_text \
  --ignore-table=zabbix.history_log --ignore-table=zabbix.trends \
  --ignore-table=zabbix.trends_uint \
  zabbix | gzip > /backup/zabbix_$(date +%F).sql.gz
# → файл дампа без крупных таблиц
```

PostgreSQL:

```bash
sudo -u postgres pg_dump -Fc zabbix > /backup/zabbix_$(date +%F).dump
# → custom-format дамп (восстанавливается pg_restore)
```

### Сценарий 2. Резервное копирование конфигурации

```bash
sudo tar czf /backup/zabbix_conf_$(date +%F).tar.gz \
  /etc/zabbix \
  /usr/lib/zabbix/externalscripts \
  /usr/lib/zabbix/alertscripts \
  /etc/httpd/conf.d/zabbix.conf \
  /etc/php-fpm.d/zabbix.conf 2>/dev/null
# → архив конфигурации и скриптов
```

### Сценарий 3. Обновление пакетами (RHEL-подобные)

```bash
# 1. Остановить сервер
sudo systemctl stop zabbix-server zabbix-agent
# 2. Сделать бэкап (сценарии 1 и 2)
# 3. Обновить репозиторий и пакеты (пример для 7.0)
sudo dnf install -y https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/zabbix-release-latest-7.0.el9.noarch.rpm
sudo dnf clean all
sudo dnf upgrade -y zabbix-server-mysql zabbix-web-mysql zabbix-sql-scripts zabbix-agent
# 4. Запустить сервер — схема БД обновится автоматически
sudo systemctl start zabbix-server
# 5. Проверить лог
sudo tail -f /var/log/zabbix/zabbix_server.log
# → "database upgrade fully completed" и запуск сервера
```

### Сценарий 4. Обновление из контейнеров

```bash
cd zabbix-docker
git pull
git checkout 7.0
docker compose -f ./compose.yaml up -d
# → перезапуск компонентов на новых образах; БД обновляется автоматически
```

Для MySQL/MariaDB с binary logging и обновлением с 6.0 и старше: выставить `log_bin_trust_function_creators=1` перед запуском и вернуть `0` после успеха.

### Сценарий 5. Восстановление

```bash
# MySQL/MariaDB
zcat /backup/zabbix_2026-01-01.sql.gz | mysql -uzabbix -p zabbix
# PostgreSQL
sudo -u postgres pg_restore -d zabbix -c /backup/zabbix_2026-01-01.dump
```

После восстановления БД без history/trends — пересоздать эти таблицы по схеме (или принять их отсутствие, они наполнятся заново).

### Валидация

```bash
# Версия сервера
zabbix_server -V
# → Zabbix Server 7.0.x (revision ...)

# Версия схемы БД (в логе при старте)
grep -iE "database version|upgrade (fully )?completed" /var/log/zabbix/zabbix_server.log

# Проверка фронтенда
curl -s http://zabbix.example.com/zabbix/ -o /dev/null -w "%{http_code}\n"
# → 200
```

---

## Операции и команды

```bash
# Остановить/запустить компоненты
sudo systemctl stop zabbix-server zabbix-proxy zabbix-agent
sudo systemctl start zabbix-server

# Проверить конфигурацию перед запуском
zabbix_server -T -c /etc/zabbix/zabbix_server.conf
# → "configuration file looks OK" / ошибка с указанием параметра

# Версии
zabbix_server -V && zabbix_proxy -V && zabbix_agent2 -V
```

| Действие | Инструмент |
|---|---|
| Дамп MySQL/MariaDB | `mysqldump --single-transaction` |
| Дамп PostgreSQL | `pg_dump -Fc` |
| Восстановление MySQL | `mysql < dump.sql` |
| Восстановление PostgreSQL | `pg_restore -c` |
| Бэкап конфигурации Zabbix | `tar` по `/etc/zabbix` и скриптам |
| Бэкап конфигурации как код | export/import (UI или API) |

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| `database version does not match` | Сервер не выполнил патчи (не стартовал) | Запустить сервер, дождаться патчей; проверить лог |
| `mandatory patches were found ... upgrade failed` | Патч упал (например, объект уже существует) | Разобрать ошибку в логе; при необходимости обновить промежуточную версию (6.4.x) |
| `Table 'scim_group' already exists` | Промежуточная «release candidate» версия БД | Обновиться сначала до стабильной промежуточной версии |
| Обновление с 6.0 зависло на создании триггеров | Включён binary logging без прав | `SET GLOBAL log_bin_trust_function_creators = 1` (вернуть `0` после) |
| Прокси не запускается после обновления | SQLite3 удалил БД; либо версия прокси старше файла БД | Учесть потерю истории прокси; обновить прокси до версии сервера |
| TimescaleDB со сжатием не обновился | Схема обновляется вручную | Применить manual-патчи compression/no-compression |
| Партиции «потерялись» после апгрейда | Обновление схемы снимает партиционирование | Пересоздать партиции |
| Не хватило места при обновлении схемы | Патчи создают промежуточные таблицы | Освободить место заранее |
| Фронтенд отдаёт ошибку после апгрейда | Несовместимая версия PHP или кэш | Проверить требования PHP; очистить кэш браузера/обновить фронтенд |

---

## Лучшие практики

* **Бэкап БД — обязателен до любого обновления.** Пропуск этого шага — главная причина тяжёлых инцидентов.
* **Исключать history/trends из дампа** для скорости; восстанавливать при необходимости отдельно.
* **Резервировать конфигурацию и скрипты** — их восстановление из БД не покрывает внешние скрипты.
* **Обновлять server → proxies**, не наоборот; агенты можно обновлять позже.
* **Тестировать обновление на копии БД** перед продом; обновление схемы больших БД долгое.
* **Держать конфигурацию под Git** через export/import (MaC) — точечный откат без полного restore.
* **Планировать окно обслуживания** и предупреждать дежурных; прокси переживут простой сервера.
* **Фиксировать версии** в репозиториях/образах, не использовать `latest`.
* **После обновления проверить:** старт сервера, отсутствие ошибок в логе, работу фронтенда, приём данных с прокси.

---

## Дополнительная информация

### См. также

* [Zabbix — Установка](./installation.md) — требования к версиям ПО и схема БД.
* [Zabbix — Housekeeper и партиционирование БД](./zabbix_housekeeping_and_partitioning.md) — влияние обновления на партиции.
* [Zabbix — API и автоматизация](./zabbix_api_automation.md) — export/import конфигурации как код.
* [Zabbix — внутреннее устройство и архитектура процессов](./additional_info.md) — версии процессов и совместимость прокси.

### Источники и ссылки

* Zabbix documentation: [Upgrade procedure](https://www.zabbix.com/documentation/7.0/en/manual/installation/upgrade)
* Zabbix documentation: [Upgrade from sources](https://www.zabbix.com/documentation/7.0/en/manual/installation/upgrade/sources)
* Zabbix documentation: [Upgrade from containers](https://www.zabbix.com/documentation/7.0/en/manual/installation/upgrade/containers)
* Zabbix documentation: [Database upgrade to primary keys](https://www.zabbix.com/documentation/7.0/en/manual/appendix/install/db_primary_keys)
