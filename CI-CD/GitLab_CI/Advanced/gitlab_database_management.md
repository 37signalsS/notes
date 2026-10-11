# Управление базами данных GitLab

**Актуально для:** GitLab 17.x–19.x (PostgreSQL 17+, Valkey 7.2+ / Redis 7.2+)

## Определения

* **PostgreSQL** — реляционная СУБД, используемая GitLab для хранения метаданных (пользователи, проекты, права, пайплайны, миграции).
* **Valkey** — высокопроизводительное in-memory хранилище (форк Redis), используемое в GitLab 19.x как основной механизм кэширования и брокер сообщений для Sidekiq. В Omnibus GitLab управляется через те же ключи `redis['...']` в `gitlab.rb` с флагом `redis['backend'] = 'valkey'`.
* **Patroni** — кластерный менеджер для PostgreSQL, обеспечивающий автоматический failover и репликацию. В GitLab Premium/Ultimate интегрирован в Omnibus пакет.
* **Consul** — система обнаружения сервисов и распределённое хранилище конфигураций (DCS), используемая Patroni для хранения состояния кластера и координации узлов.
* **DCS (Distributed Configuration Store)** — распределённое хранилище, в котором Patroni хранит lock лидера, конфигурацию кластера и статусы узлов.
* **PgBouncer** — легковесный пул соединений для PostgreSQL, снижающий overhead на установку TCP-соединений и ограничивающий количество одновременных подключений.
* **Connection Pool** — пул соединений с базой данных, ограничивающий количество одновременных подключений.
* **shared_buffers** — параметр PostgreSQL, определяющий объём памяти для кэширования данных.
* **Eviction Policy** — политика вытеснения данных из памяти (allkeys-lru, volatile-lru и др.).
* **PITR (Point-in-Time Recovery)** — восстановление базы данных на произвольный момент времени путём комбинации полного бэкапа и последовательных WAL-файлов.
* **WAL (Write-Ahead Log)** — журнал предзаписи PostgreSQL, обеспечивающий durability и служащий основой для репликации и PITR.
* **Replication Slot** — механизм PostgreSQL, гарантирующий, что WAL-файлы не будут удалены до их получения репликой.

## Предварительные требования

Перед настройкой управления базами данных GitLab убедитесь, что выполнены следующие условия:

* **ОС:** Omnibus GitLab 17.x–19.x поддерживает Debian 12/13, Ubuntu 22.04/24.04, RHEL 9/10.
* **Память:** минимум 16 GB RAM для standalone-инстанса; при использовании Patroni + PgBouncer — минимум 8 GB на каждый узел PostgreSQL.
* **Диски:** SSD/NVMe с IOPS > 3000 для PostgreSQL; отдельный раздел для `/var/opt/gitlab/postgresql` снижает риск заполнения корня.
* **Сеть:** открытые порты 5432 (PostgreSQL), 8500/8501 (Consul), 6432 (PgBouncer), 6379 (Redis/Valkey).
* **Права:** доступ root или sudo для выполнения `gitlab-ctl reconfigure` и управления сервисами.
* **Секреты:** `/etc/gitlab/gitlab-secrets.json` должен существовать и быть доступен; без него восстановление после сбоя невозможно.
* **Версии:** PostgreSQL 17+ (минимальная для GitLab 19.0); Valkey 7.2+ или Redis 7.2+ (Redis 6 удалён в GitLab 19.0).

## Основные концепции

### Архитектура данных GitLab

GitLab использует три основных хранилища данных:

1. **PostgreSQL** — метаданные инстанса (пользователи, проекты, группы, права доступа, пайплайны, комментарии, события).
2. **Valkey/Redis** — кэш сессий, кэш приложения, очереди Sidekiq, временные данные.
3. **Gitaly** — Git-репозитории (не relational, но критичны для производительности и целостности данных).

### Роли PostgreSQL в GitLab

| Роль | Описание |
|:---|:---|
| **Метаданные** | Пользователи, проекты, группы, права доступа |
| **CI/CD состояние** | Пайплайны, джобы, артефакты (ссылки) |
| **Аудит** | Логи событий, compliance данные |
| **Аналитика** | DORA-метрики, ClickHouse (отдельный инстанс) |

### Роли Valkey/Redis в GitLab

| Роль | Описание |
|:---|:---|
| **Кэш сессий** | Хранение сессий пользователей |
| **Кэш приложения** | Кэширование частых запросов |
| **Очереди Sidekiq** | Брокер сообщений для фоновых задач |
| **Временные данные** | Кэширование результатов запросов |

### Архитектура HA PostgreSQL (Patroni + Consul + PgBouncer)

В GitLab Premium/Ultimate высоконагруженные инстансы используют кластерную конфигурацию:

1. **Patroni** управляет жизненным циклом PostgreSQL на каждом узле: запуск, остановка, failover, репликация.
2. **Consul** выполняет роль DCS: хранит lock лидера, обнаруживает сервисы и координирует переключение.
3. **PgBouncer** принимает подключения от Rails/Sidekiq и транслирует их в пул соединений к PostgreSQL, снижая overhead.

Принцип работы:
- Patroni поднимает сессию в Consul с TTL (по умолчанию 30 секунд) и обновляет её регулярно (loop_wait ≈ 10 секунд).
- Если Patroni не может обновить TTL (сбой узла или сеть), Consul считает лидера потерянным, и другой узел проводит выборы.
- PgBouncer получает уведомление от Consul о новом лидере и переключает пул без перезапуска приложения.

### Модельpersistence Valkey/Redis

Valkey/Redis сохраняет данные двумя механизмами:
* **RDB (Redis Database)** — снапшот всего набора данных в файл. Подходит для бэкапов и быстрого восстановления, но теряет данные за последние секунды перед сбоем.
* **AOF (Append-Only File)** — лог всех операций записи. Обеспечивает лучшую durability (настраивается через `appendfsync`), но файл grows быстрее и требует периодического `rewrite`.

Для production GitLab рекомендуется комбинация: RDB для регулярных снапшотов + AOF с `appendfsync everysec` для минимизации потерь.

### Валидация изменений

После любых изменений в конфигурации PostgreSQL или Valkey/Redis выполняйте проверку:

```bash
# 1. Применить конфигурацию
sudo gitlab-ctl reconfigure

# 2. Проверить статус сервисов
sudo gitlab-ctl status postgresql
sudo gitlab-ctl status redis

# 3. Проверить здоровье инстанса
sudo gitlab-rake gitlab:check SANITIZE=true

# 4. Проверить подключение к БД
sudo gitlab-psql -d gitlabhq_production -c "SELECT count(*) FROM users;"
```

## Практические сценарии

### Сценарий 1: Настройка PostgreSQL для GitLab

```ruby
# /etc/gitlab/gitlab.rb

# Базовые параметры PostgreSQL
postgresql['enable'] = true
postgresql['listen_address'] = '127.0.0.1'
postgresql['port'] = 5432
postgresql['max_connections'] = 200
postgresql['shared_buffers'] = "4GB"
postgresql['work_mem'] = "16MB"
postgresql['maintenance_work_mem'] = "512MB"
postgresql['effective_cache_size'] = "12GB"
postgresql['random_page_cost'] = 1.1  # Для SSD
postgresql['effective_io_concurrency'] = 200  # Для SSD
postgresql['wal_buffers'] = "64MB"
postgresql['min_wal_size'] = "1GB"
postgresql['max_wal_size'] = "4GB"
postgresql['checkpoint_completion_target'] = 0.9
postgresql['default_statistics_target'] = 100
postgresql['log_statement'] = 'ddl'
postgresql['log_min_duration_statement'] = 1000

# Пути к данным
postgresql['data_dir'] = "/var/opt/gitlab/postgresql/data"
postgresql['log_directory'] = "/var/log/gitlab/postgresql"

# Резервное копирование
postgresql['backup_path'] = "/var/opt/gitlab/postgresql/backups"
postgresql['backup_keep_time'] = 604800  # 7 дней

# Применение
sudo gitlab-ctl reconfigure
```

### Сценарий 2: Настройка Valkey для GitLab

```ruby
# /etc/gitlab/gitlab.rb

# Включение Valkey (GitLab 19.x)
redis['backend'] = 'valkey'
redis['listen_address'] = '127.0.0.1'
redis['port'] = 6379
redis['maxmemory'] = "8gb"
redis['maxmemory_policy'] = "allkeys-lru"
redis['maxmemory_samples'] = 5
redis['save'] = ["900 1", "300 10", "60 10000"]
redis['stop_writes_on_bgsave_error'] = 'no'
redis['rdbcompression'] = 'yes'
redis['rdbchecksum'] = 'yes'

# Аутентификация
redis['requirepass'] = 'strong_password_here'

# Применение
sudo gitlab-ctl reconfigure
```

**Миграция с Redis на Valkey:**

```bash
# 1. Обновить gitlab.rb: добавить redis['backend'] = 'valkey'
# 2. Применить конфигурацию
sudo gitlab-ctl reconfigure

# 3. Проверить, что сервис работает под Valkey
sudo gitlab-redis-cli INFO server | grep valkey_version
# → valkey_version:7.2.0
```

### Сценарий 3: Мониторинг PostgreSQL

```sql
-- Подключение к PostgreSQL
sudo gitlab-psql -d gitlabhq_production

-- Проверка размера БД
SELECT pg_size_pretty(pg_database_size('gitlabhq_production'));

-- Проверка активных соединений
SELECT count(*) FROM pg_stat_activity WHERE datname = 'gitlabhq_production';

-- Проверка долгих запросов (>5 секунд)
SELECT pid, now() - pg_stat_activity.query_start AS duration, query, state
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 seconds'
  AND datname = 'gitlabhq_production'
ORDER BY duration DESC;

-- Проверка использования индексов
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan ASC;

-- Проверка блокировок
SELECT * FROM pg_locks WHERE NOT granted;

-- Проверка размера таблиц
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 20;
```

### Сценарий 4: Оптимизация PostgreSQL

```bash
-- Анализ таблиц
sudo gitlab-psql -d gitlabhq_production -c "ANALYZE VERBOSE;"

-- Перестроение индексов
sudo gitlab-psql -d gitlabhq_production -c "REINDEX DATABASE gitlabhq_production;"

-- Очистка таблиц (VACUUM)
sudo gitlab-psql -d gitlabhq_production -c "VACUUM VERBOSE ANALYZE;"

-- Проверка планов запросов
EXPLAIN ANALYZE SELECT * FROM users WHERE id = 1;
```

### Сценарий 5: Резервное копирование PostgreSQL

```bash
# Создание бэкапа через gitlab-ctl (логический дамп)
sudo gitlab-ctl pg-backup /backup/postgresql-$(date +%Y%m%d).sql.gz

# Создание бэкапа через pg_dump (кастом формат)
sudo -u gitlab-psql /opt/gitlab/embedded/bin/pg_dump -d gitlabhq_production -F c -b -v -f /backup/gitlab-db-$(date +%Y%m%d).dump

# Восстановление из бэкапа полного инстанса
sudo gitlab-ctl stop puma
sudo gitlab-ctl stop sidekiq
sudo gitlab-backup restore BACKUP=1748774401_2026_06_01_19.0.0
sudo gitlab-ctl start

# Восстановление только PostgreSQL из кастомного дампа
sudo gitlab-ctl stop puma
sudo gitlab-ctl stop sidekiq
sudo -u gitlab-psql /opt/gitlab/embedded/bin/pg_restore -d gitlabhq_production -v /backup/gitlab-db-20260601.dump
sudo gitlab-ctl start
```

### Сценарий 6: Настройка HA PostgreSQL (Patroni + Consul)

```yaml
# /etc/gitlab/gitlab.rb

postgresql['enable'] = true
postgresql['listen_address'] = '0.0.0.0'
postgresql['max_connections'] = 200
postgresql['shared_buffers'] = "4GB"

# Patroni
patroni['enable'] = true
patroni['scope'] = 'gitlab'
patroni['name'] = 'node-1'
patroni['consul']['url'] = 'http://localhost:8500'
patroni['register_service'] = true

# Consul
consul['enable'] = true
consul['server'] = true
consul['bootstrap']['expect'] = 3

# Применение
sudo gitlab-ctl reconfigure
```

**Проверка статуса кластера:**

```bash
# Список узлов Patroni
sudo gitlab-ctl patroni members

# Проверка лидера через Consul
curl http://localhost:8500/v1/kv/patroni/gitlab/leader
```

### Сценарий 7: Настройка PITR для PostgreSQL

PITR требует архивации WAL-файлов. В Omnibus GitLab настройка выполняется через параметры PostgreSQL:

```ruby
# /etc/gitlab/gitlab.rb

postgresql['archive_mode'] = 'on'
postgresql['archive_command'] = 'test ! -f /var/opt/gitlab/postgresql/wal_archive/%f && cp %p /var/opt/gitlab/postgresql/wal_archive/%f'
postgresql['archive_timeout'] = 300
postgresql['wal_level'] = 'replica'
postgresql['max_wal_senders'] = 10
postgresql['wal_keep_size'] = '1GB'
```

**Восстановление на момент времени:**

```bash
# 1. Остановить PostgreSQL
sudo gitlab-ctl stop postgresql

# 2. Восстановить базовый бэкап
sudo -u gitlab-psql /opt/gitlab/embedded/bin/pg_basebackup -D /var/opt/gitlab/postgresql/data -X fetch -P -R

# 3. Создать recovery.signal
sudo -u gitlab-psql touch /var/opt/gitlab/postgresql/data/recovery.signal

# 4. Настроить restore_command
echo "restore_command = 'cp /var/opt/gitlab/postgresql/wal_archive/%f %p'" >> /var/opt/gitlab/postgresql/data/postgresql.conf
echo "recovery_target_time = '2026-06-01 14:30:00'" >> /var/opt/gitlab/postgresql/data/postgresql.conf

# 5. Запустить PostgreSQL
sudo gitlab-ctl start postgresql
```

### Сценарий 8: Обновление PostgreSQL с помощью pg-upgrade

```bash
# 1. Создать полный бэкап перед обновлением
sudo gitlab-ctl pg-backup /backup/pre-upgrade-$(date +%Y%m%d).sql.gz

# 2. Выполнить pg-upgrade (переключает версию PostgreSQL)
sudo gitlab-ctl pg-upgrade

# 3. Проверить статус
sudo gitlab-ctl status postgresql
sudo gitlab-rake gitlab:check SANITIZE=true

# 4. Если требуется откат (доступно только если предыдущая версия ещё установлена)
sudo gitlab-ctl revert-pg-upgrade
```

### Сценарий 9: Настройка PgBouncer

PgBouncer снижает количество соединений к PostgreSQL, что критично при большом количестве Rails/Sidekiq процессов:

```ruby
# /etc/gitlab/gitlab.rb

postgresql['pgbouncer_enable'] = true
postgresql['pgbouncer_port'] = 6432
postgresql['pgbouncer_pool_mode'] = 'transaction'
postgresql['pgbouncer_max_client_conn'] = 1000
postgresql['pgbouncer_default_pool_size'] = 50

# Применение
sudo gitlab-ctl reconfigure
```

### Сценарий 10: Мониторинг Valkey

```bash
# Подключение к Valkey (wrapper автоматически определяет backend)
sudo gitlab-redis-cli

-- Проверка информации
INFO

-- Проверка памяти
INFO memory

-- Проверка клиентов
INFO clients

-- Проверка статистики
INFO stats

-- Проверка ключей
DBSIZE
```

### Сценарий 11: Оптимизация Valkey

```bash
# Настройка памяти
sudo gitlab-redis-cli CONFIG SET maxmemory 8gb
sudo gitlab-redis-cli CONFIG SET maxmemory-policy allkeys-lru

-- Проверка hit ratio
INFO stats | grep keyspace_hits
INFO stats | grep keyspace_misses

-- Расчет hit ratio
keyspace_hits / (keyspace_hits + keyspace_misses) * 100
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `PG::ConnectionBad` | PostgreSQL не отвечает | Проверьте статус: `gitlab-ctl status postgresql`. Проверьте логи. |
| `FATAL: password authentication failed` | Неверный пароль | Проверьте `postgresql['sql_user_password']` в `gitlab.rb`. Для генерации хеша используйте `gitlab-ctl pg-password-md5 'gitlab'`. |
| `too many connections` | Исчерпан лимит соединений | Увеличьте `max_connections` или используйте connection pooling (PgBouncer). |
| Valkey memory overflow | Исчерпан лимит памяти | Увеличьте `maxmemory` или настройте eviction policy. |
| Sidekiq queue растёт | Проблемы с Valkey/Redis | Проверьте доступность Valkey: `gitlab-ctl status redis`. |
| Медленные запросы | Отсутствие индексов | Запустите `ANALYZE`, проверьте планы запросов. |
| Репликация отстаёт | Сетевая задержка | Проверьте сеть, увеличьте `wal_buffers`. |
| `gitlab-ctl pg-restore` не найден | Команда не существует | Для восстановления используйте `gitlab-backup restore BACKUP=...` или `pg_restore` напрямую. |

## Лучшие практики

### PostgreSQL

* **Версия:** используйте PostgreSQL 17+ (минимальная для GitLab 19.0).
* **SSD:** используйте SSD/NVMe для данных PostgreSQL.
* **shared_buffers:** выделяйте 25-40% доступной RAM.
* **Индексы:** регулярно анализируйте и оптимизируйте индексы.
* **Мониторинг:** отслеживайте долгие запросы, соединения, размер БД.
* **Бэкап:** регулярный бэкап через `gitlab-ctl pg-backup` или `pg_dump`.
* **WAL-архивация:** настройте `archive_command` для возможности PITR.
* **HA:** для enterprise используйте Patroni + Consul + PgBouncer (GitLab Premium/Ultimate).

### Valkey/Redis

* **Версия:** используйте Valkey 7.2+ или Redis 7.2+ (Redis 6 удалён в GitLab 19.0).
* **Память:** выделяйте достаточно RAM (обычно 25-30% от общей памяти сервера).
* **Eviction policy:** используйте `allkeys-lru` для кэша.
* **Персистентность:** настройте RDB + AOF в зависимости от требований к RPO.
* **Миграция:** при переходе на Valkey используйте `redis['backend'] = 'valkey'` в `gitlab.rb`.
* **Мониторинг:** отслеживайте память, hit ratio, количество клиентов.

### Общее

* **Разделение:** для больших инстансов выносите PostgreSQL и Valkey на отдельные серверы.
* **HA:** используйте Patroni + Consul для автоматического failover PostgreSQL.
* **Мониторинг:** настройте алерты на критичные метрики (соединения, память, диск).
* **Бэкап секретов:** `/etc/gitlab/gitlab-secrets.json` и `/etc/gitlab/gitlab.rb` должны быть включены в offsite-бэкап.
* **Тестирование восстановления:** выполняйте DR drill минимум раз в квартал.

## Дополнительная информация

### Связанные темы

* **[Управление инстансом GitLab](./gitlab_instance_administration.md)** — бэкап, восстановление, обновление
* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[PostgreSQL Documentation](https://www.postgresql.org/docs/17/)** — официальная документация
* **[Valkey Documentation](https://valkey.io/)** — официальная документация

### Полезные запросы

```sql
-- Размер БД
SELECT pg_size_pretty(pg_database_size('gitlabhq_production'));

-- Активные соединения
SELECT count(*) FROM pg_stat_activity WHERE datname = 'gitlabhq_production';

-- Долгие запросы
SELECT pid, now() - pg_stat_activity.query_start AS duration, query, state
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 seconds'
  AND datname = 'gitlabhq_production'
ORDER BY duration DESC;

-- Размер таблиц
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 20;
```
