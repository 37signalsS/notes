# Flyway: Практическое руководство по эксплуатации

**Актуально для:** Flyway 10.x

## Определения

*   **Версионированная миграция (Versioned Migration):** Скрипт с уникальным номером версии (например, `V1__init.sql`), который применяется один раз.
*   **Повторяемая миграция (Repeatable Migration):** Скрипт (например, `R__views.sql`), который применяется каждый раз при изменении его контрольной суммы. Идеально для View, функций и процедур.
*   **Undo-миграция (Undo Migration):** Скрипт (например, `U1__init.sql`), предназначенный для отката соответствующей версионированной миграции (доступно в Teams/Enterprise).
*   **Схема метаданных (Schema History Table):** Таблица (по умолчанию `flyway_schema_history`), где Flyway хранит состояние примененных миграций.
*   **Callback:** Функция или скрипт, который Flyway вызывает на определенных этапах (`beforeMigrate`, `afterMigrate`, `beforeEachMigrate`, `afterEachMigrate` и др.). Позволяет интегрировать внешнюю логику (уведомления, аудит, очистка кэша) без изменения кода миграций.
*   **Placeholder (Плейсхолдер):** Переменная в скрипте миграции (например, `${schema_name}`), подставляемая из конфигурации во время выполнения. Один скрипт можно использовать в Dev, Stage и Prod с разными значениями.
*   **Target:** Версия миграции, до которой Flyway должен применить изменения (`flyway.target=5.3`). Полезно для частичного развертывания или отката на уровне инструмента.
*   **Baseline:** Операция создания начальной записи в `flyway_schema_history` для существующей БД. Позволяет начать использовать Flyway в проекте, где схема уже существует.
*   **Validate:** Проверка контрольных сумм (checksum) уже примененных миграций. При изменении файла после применения Flyway сообщает `Validate failed` и требует `repair`.
*   **Edition:** Flyway выпускается в трех редакциях: Community (бесплатно, SQL-based, undo недоступны), Teams (undo, callbacks, dry-run, облачные целевые БД), Enterprise (Kerberos, SSO, консультации). Большинство операционных возможностей доступны в Community.

## Архитектура и принцип работы

### Основной цикл

Flyway реализует императивный подход к миграциям:

1.  **Сканирование locations:** При запуске `migrate` Flyway сканирует указанные директории (`filesystem:./sql`, `classpath:db/migration`) и URL (`s3:migrations`, `gcs:migrations`) на наличие файлов миграций.
2.  **Чтение состояния:** Открывает `flyway_schema_history` в целевой схеме и определяет, какие версии уже применены.
3.  **Сортировка:** Упорядочивает найденные файлы по версии (`V1`, `V2`, `R__views`). Повторяемые миграции (`R*`) сортируются после версионированных.
4.  **Валидация:** Сравнивает контрольные суммы (`checksum`) файлов на диске с записанными в таблице истории. При расхождении — ошибка `Validate failed`.
5.  **Применение:** Выполняет новые миграции по порядку. В Community-редакции каждая миграция выполняется в отдельной транзакции (если СУБД поддерживает DDL-транзакции).
6.  **Запись:** Фиксирует результат в `flyway_schema_history`: версия, описание, тип, checksum, время выполнения, успех/неудача.

### Структура таблицы `flyway_schema_history`

| Колонка | Тип | Описание |
| :--- | :--- | :--- |
| `installed_rank` | INT | Порядковый номер применения |
| `version` | VARCHAR | Номер версии миграции (NULL для R*) |
| `description` | VARCHAR | Описание из имени файла |
| `type` | VARCHAR | `SQL`, `UNDO`, `REPEATABLE` |
| `script` | VARCHAR | Имя файла или путь |
| `checksum` | INT | Контрольная сумма содержимого |
| `installed_by` | VARCHAR | Пользователь СУБД, выполнивший миграцию |
| `installed_on` | TIMESTAMP | Время применения |
| `execution_time` | INT | Длительность в миллисекундах |
| `success` | BOOLEAN | Результат выполнения |

### Поддерживаемые СУБД

| СУБД | Community | Teams/Enterprise | Особенности |
| :--- | :--- | :--- | :--- |
| **PostgreSQL** | Да | Да | Полная поддержка DDL-транзакций |
| **MySQL / MariaDB** | Да | Да | Нет DDL-транзакций; `undo` рискован |
| **Oracle** | Да | Да | Требует лицензии; ограниченный DDL-транзакционный |
| **SQL Server** | Да | Да | Полная поддержка DDL-транзакций |
| **CockroachDB** | Да | Нет | Совместим с PostgreSQL-режимом |
| **DB2** | Нет | Да | Enterprise-only |
| **Redshift** | Нет | Да | Enterprise-only |

## Установка

### 1. CLI (рекомендуется для production)

```bash
# Linux x86_64
wget -qO- https://download.red-gate.com/maven/release/com/redgate/flyway/flyway-commandline/10.0.0/flyway-commandline-10.0.0-linux-x64.tar.gz | tar xvz
sudo ln -s $(pwd)/flyway-10.0.0/flyway /usr/local/bin/flyway

# Проверка
flyway --version
# → Flyway Community Edition 10.0.0 by Redgate
```

### 2. Docker (рекомендуется для CI/CD)

```bash
# Информация о версии образа
docker inspect redgate/flyway:10.0.0-alpine --format='{{.Created}}'

# Запуск миграции
docker run --rm \
  -v $(pwd)/sql:/flyway/sql \
  -e FLYWAY_URL=jdbc:postgresql://db:5432/mydb \
  -e FLYWAY_USER=flyway_user \
  -e FLYWAY_PASSWORD=${DB_PASSWORD} \
  redgate/flyway:10.0.0-alpine migrate
```

### 3. Maven

```xml
<plugin>
    <groupId>org.flywaydb</groupId>
    <artifactId>flyway-maven-plugin</artifactId>
    <version>10.0.0</version>
    <configuration>
        <url>jdbc:postgresql://localhost:5432/mydb</url>
        <user>postgres</user>
        <password>pass</password>
        <locations>
            <location>filesystem:src/main/resources/db/migration</location>
        </locations>
    </configuration>
</plugin>
```

### 4. Gradle

```groovy
plugins {
    id 'org.flywaydb.flyway' version '10.0.0'
}

flyway {
    url = 'jdbc:postgresql://localhost:5432/mydb'
    user = 'postgres'
    password = 'pass'
    locations = ['filesystem:src/main/resources/db/migration']
}
```

### 5. Java API

```java
Flyway flyway = Flyway.configure()
    .dataSource("jdbc:postgresql://localhost:5432/mydb", "flyway_user", "password")
    .locations("filesystem:./sql")
    .load();

flyway.migrate();
```

### Зависимости

| Компонент | Версия | Примечание |
| :--- | :--- | :--- |
| JRE | 11+ | Для CLI и API |
| Docker | 20.10+ | Для Alpine-образа |
| Tcl/Tk | Н/Т | Не требуется (в отличие от HammerDB) |

## Конфигурация

### `flyway.conf` (рекомендуется)

```properties
# Подключение
flyway.url=jdbc:postgresql://db.example.com:5432/mydb
flyway.user=flyway_user
flyway.password=${DB_PASSWORD}

# Схемы
flyway.schemas=public
flyway.defaultSchema=public
flyway.table=flyway_schema_history

# Миграции
flyway.locations=filesystem:./sql
flyway.connectRetries=10
flyway.connectRetriesInterval=10

# Безопасность
flyway.cleanDisabled=true
flyway.validateOnMigrate=true

# Поведение
flyway.baselineOnMigrate=false
flyway.group=true
flyway.outOfOrder=false

# Callbacks (опционально)
flyway.callbacks=com.example.CustomCallback
```

### Переменные окружения (Docker / CI)

```bash
FLYWAY_URL=jdbc:postgresql://db:5432/mydb
FLYWAY_USER=flyway_user
FLYWAY_PASSWORD=${DB_PASSWORD}
FLYWAY_SCHEMAS=public
FLYWAY_LOCATIONS=filesystem:/flyway/sql
FLYWAY_CONNECT_RETRIES=60
```

### Placeholder-ы

Используйте плейсхолдеры для параметризации скриптов:

```sql
-- V20240817__create_orders.sql
CREATE TABLE ${schemaName}.orders (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT now()
);
```

```properties
# flyway.conf
flyway.placeholders.schemaName=app
flyway.placeholders.someTable=orders
```

В CLI/Docker placeholder-ы передаются через `-placeholders.schemaName=app`.

### Callback-и

Flyway вызывает callback-и на ключевых этапах:

| Событие | Описание |
| :--- | :--- |
| `beforeMigrate` | Перед началом всех миграций |
| `afterMigrate` | После успешного завершения всех миграций |
| `beforeEachMigrate` | Перед каждой отдельной миграцией |
| `afterEachMigrate` | После каждой отдельной миграции |
| `beforeClean` / `afterClean` | Перед/после `clean` |
| `beforeBaseline` / `afterBaseline` | Перед/после `baseline` |

Пример callback на SQL (встроенный):

```sql
-- afterMigrate.sql
INSERT INTO audit.log (event, timestamp)
VALUES ('migration_completed', now());
```

Для сложной логики используйте Java-callback или `beforeMigrate.sql` / `afterMigrate.sql` в locations.

### Multi-environment конфигурация

Храните конфигурацию вне репозитория миграций:

```
project/
├── sql/                    # Только миграции, коммитятся в Git
│   ├── V1__init.sql
│   └── V2__add_orders.sql
├── config/
│   ├── flyway-dev.conf
│   ├── flyway-stage.conf
│   └── flyway-prod.conf    # .gitignore
```

Запуск:
```bash
flyway -configFiles=config/flyway-prod.conf migrate
```

## Основные команды

| Команда | Описание | Пример использования |
| :--- | :--- | :--- |
| `info` | Показывает состояние всех миграций | Преддеплойная проверка |
| `migrate` | Применяет новые миграции | Основная команда CI/CD |
| `validate` | Проверяет checksum уже примененных | Перед `migrate` в CI |
| `repair` | Исправляет `flyway_schema_history` (сбрасывает failed, обновляет checksum) | Только Dev/Test, никогда в Prod |
| `baseline` | Создает базовую запись для существующей БД | Онбортинг legacy-проекта |
| `undo` | Откатывает последнюю примененную миграцию | Teams/Enterprise только |
| `clean` | Удаляет все объекты в целевых схемах | Только local; запрещена в Prod |
| `snapshot` | Сохраняет текущее состояние схемы в директорию | Аудит, сравнение сред |

## Подготовка окружения и изоляция

### Требования к окружению

Перед запуском Flyway убедитесь, что окружение соответствует рекомендациям из [Нагрузочное тестирование СУБД](../../benchmarking.md) и [Database CI/CD](../database-ci-cd.md). Ниже — Flyway-специфичные дополнения.

### Отдельный сервер для миграций

Запускайте Flyway на выделенном сервере или в изолированном Kubernetes Job, отдельно от приложения и целевой СУБД:
- **CPU:** 2+ ядра для длинных DDL-операций (например, `CREATE INDEX CONCURRENTLY`).
- **RAM:** 4+ ГБ; при больших дампах может потребоваться больше.
- **Сеть:** Стабильное соединение с БД; настройте `connectRetries` и `connectRetriesInterval`.

### Операционная система

```bash
# Фиксация частоты CPU (предотвращает throttle во время длительных DDL)
for i in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > $i
done

# Увеличение лимита открытых файлов (для параллельных миграций или больших дампов)
ulimit -n 65536

# Отключение NUMA balancing (если БД и Flyway на одном хосте)
echo 0 > /proc/sys/kernel/numa_balancing
```

### Резервное копирование перед миграцией

Всегда создавайте снимок перед применением миграций в production:

```bash
# PostgreSQL
pg_dump -Fc -d mydb -f /backups/pre_migration_$(date +%F_%H%M).dump

# ZFS/LVM снапшот
zfs snapshot pool/db@pre_migration_$(date +%F_%H%M)
```

См. также: [Резервное копирование баз данных](../../../Concepts/backups.md).

## Производственная эксплуатация

### Привилегии пользователя БД

Минимизируйте права пользователя, под которым Flyway подключается к БД:

**PostgreSQL (минимальные права):**
```sql
CREATE ROLE flyway_user WITH LOGIN PASSWORD '${FLYWAY_PASSWORD}';
GRANT CONNECT ON DATABASE mydb TO flyway_user;
GRANT USAGE, CREATE ON SCHEMA public TO flyway_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO flyway_user;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO flyway_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO flyway_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO flyway_user;
```

**MySQL:**
```sql
CREATE USER 'flyway_user'@'%' IDENTIFIED BY '${FLYWAY_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP ON mydb.* TO 'flyway_user'@'%';
FLUSH PRIVILEGES;
```

> **Важно:** Не давайте пользователю Flyway права `SUPERUSER` или `OWNER`. Это снижает риск случайного `clean` или деструктивных изменений.

### Управление секретами

Никогда не храните пароли в `flyway.conf` или скриптах миграций, которые коммитятся в Git:

- **Vault / SOPS:** Шифруйте `flyway-prod.conf` и расшифровывайте в CI/CD во время выполнения.
- **Kubernetes Secrets:** Монтируйте как файл или переменную окружения в Job.
- **Docker Secrets:** `/run/secrets/db_password`.
- **CI/CD Variables:** GitLab CI/CD Variables, GitHub Secrets, Jenkins Credentials.

### Таймауты и окна обслуживания

Установите защитные барьеры на уровне СУБД для предотвращения зависаний:

```sql
-- PostgreSQL: установите на сессию Flyway перед запуском
SET lock_timeout = '10s';          -- Ждать блокировку не более 10 секунд
SET statement_timeout = '600s';    -- Прекратить запрос, если он идет дольше 10 минут
SET idle_in_transaction_session_timeout = '60s';  -- Завершить "зависшие" транзакции
```

Для длительных DDL (`CREATE INDEX CONCURRENTLY`, большие `ALTER TABLE`) увеличьте `statement_timeout` или отключите его на время миграции.

### Запуск миграций

#### Kubernetes Job (рекомендуется для production)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: flyway-migrate
  annotations:
    "helm.sh/hook": pre-upgrade,pre-install
    "helm.sh/hook-delete-policy": hook-succeeded,before-hook-creation
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: flyway
        image: redgate/flyway:10.0.0-alpine
        env:
        - name: FLYWAY_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
        - name: FLYWAY_USER
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: username
        - name: FLYWAY_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: password
        command: ["flyway", "migrate"]
        resources:
          limits:
            cpu: "2"
            memory: "4Gi"
          requests:
            cpu: "500m"
            memory: "1Gi"
```

#### systemd-сервис (для на-prem БД)

```ini
[Unit]
Description=Flyway Database Migration
After=network.target postgresql.service

[Service]
Type=oneshot
User=flyway
WorkingDirectory=/opt/flyway
EnvironmentFile=/etc/flyway/flyway-prod.env
ExecStart=/usr/local/bin/flyway -configFiles=/etc/flyway/flyway-prod.conf migrate
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Синхронизация с репликацией

Длительные миграции данных могут вызвать лаг репликации:
- **PostgreSQL:** Мониторьте `pg_stat_replication` и `sent_lsn` / `replay_lsn`.
- **MySQL:** Мониторьте `Seconds_Behind_Master` в `SHOW SLAVE STATUS`.
- При превышении порога — приостановите или замедлите пакетную DML-миграцию (увеличьте `sleep` между батчами).

См. также: [Мониторинг миграций](../monitoring.md).

## Стратегии отката

### Fix-Forward (рекомендуется)

Самый безопасный метод для production. Вместо физического отката создается новая миграция, исправляющая проблему.

```text
V2__add_index.sql     ← вызвал лаг или блокировку
V3__drop_problematic_index.sql  ← исправляет проблему
```

**Плюс:** Сохраняется иммутабельность истории, нет риска расхождения состояний между БД в кластере.

### Undo-скрипты (Flyway Teams/Enterprise)

Если необходимо физически откатить схему:

1. Создайте пару: `V5__add_col.sql` и `U5__add_col.sql`.
2. Выполните: `flyway undo`.

> **Риск:** `Undo` не может восстановить данные, удаленные с помощью `DROP COLUMN`. Всегда делайте бэкап перед `undo`.

### Восстановление после Checksum Mismatch

Если файл миграции был изменен после применения:

1. **Dev/Test:** Выполните `flyway repair`. Это обновит контрольные суммы в таблице истории.
2. **Production:** **НИКОГДА** не делайте `repair` автоматически. Исправьте файл в Git так, чтобы он соответствовал тому, что было применено, или создайте новую миграцию.

См. также: [Стратегии отката (Rollback)](../rollback_strategies.md), [Database CI/CD](../database-ci-cd.md).

## Мониторинг

### Выходные коды Flyway

| Код | Описание | Действие |
| :--- | :--- | :--- |
| `0` | Успех | Продолжайте деплой |
| `1` | Ошибка миграции (Validate failed, SQL error) | Остановка пайплайна, расследование |
| `2` | Ошибка параметров | Проверьте конфигурацию |
| `3` | Ошибка подключения | Проверьте сеть, credentials, доступность БД |

### Логирование

Включите детальное логирование для расследования ошибок:

```bash
flyway -X -logLevel=DEBUG migrate
```

Направляйте вывод в файл или систему сбора логов (ELK, Loki):

```bash
flyway migrate 2>&1 | tee /var/log/flyway/migrate-$(date +%F_%H%M).log
```

### Проверка состояния после миграции

```sql
-- PostgreSQL: проверка последних примененных миграций
SELECT version, description, installed_on, execution_time, success
FROM flyway_schema_history
ORDER BY installed_rank DESC
LIMIT 10;

-- Проверка неудачных миграций
SELECT * FROM flyway_schema_history WHERE success = false;

-- Проверка pending миграций (если migrate не отработал)
SELECT * FROM flyway_schema_history WHERE success = true;
-- Сравните с файлами в sql/ директории
```

### Интеграция с мониторингом

- **Prometheus / Grafana:** Используйте `postgres_exporter` для метрик `pg_stat_activity`, `pg_locks`, `pg_stat_replication` во время миграции.
- **Алерты:** Настройте алертинг на `pg_replication_lag_seconds > 60`, `iowait` >30%, `load average` > ядер.
- **Distributed Tracing:** Добавьте `application_name = 'flyway_migration'` в строку подключения для фильтрации в логах.

См. также: [Мониторинг миграций](../monitoring.md).

## Поиск и устранение неисправностей

### Validate failed (Checksum mismatch)

**Симптомы:** `Flyway validate failed` при запуске `migrate`. Контрольная сумма applied-миграции не совпадает с файлом на диске.

**Причины:**
- Файл миграции был изменен после применения (например, исправлена опечатка).
- Файл был пересоздан в другом окружении с другим окончанием строк (LF vs CRLF).

**Решение:**
- **Dev/Test:** `flyway repair` обновляет checksum в `flyway_schema_history`.
- **Production:** Никогда не делайте `repair` автоматически. Исправьте файл в Git так, чтобы он соответствовал тому, что было применено, или создайте новую компенсирующую миграцию (Fix-Forward).

### Migration failed (частичное применение)

**Симптомы:** Миграция упала на середине, `flyway_schema_history` показывает `success = false`. Таблица или данные частично изменены.

**Причины:**
- Сетевая ошибка во время выполнения DDL.
- Исчерпание дискового пространства.
- Откат по `statement_timeout`.

**Решение:**
- **PostgreSQL:** Если используется transactional DDL — база автоматически откатила изменения. Просто исправьте миграцию и перезапустите.
- **MySQL / Oracle:** DDL вызывает неявный коммит. Ручная очистка может потребоваться. Проверьте состояние схемы и используйте Fix-Forward.

### Clean on Production (аварийный сценарий)

**Симптом:** Кто-то выполнил `flyway clean` на Production.

**Решение:**
1. Немедленно остановите все deployment-ы.
2. Восстановите БД из последнего бэкапа.
3. Выполните `flyway baseline` с версией, соответствующей состоянию на момент бэкапа.
4. Проведите аудит: кто, когда и почему выполнил `clean`.

> **Предотвращение:** `flyway.cleanDisabled=true` в конфигурации всех сред кроме local. В Kubernetes добавьте ` PodSecurityPolicy` или admission-контроллер, запрещающий запуск `clean` в Production namespace.

### Lock timeout и зависание

**Симптом:** Миграция зависает на `LOCK` или не завершается за отведенное время.

**Решение:**
- Убедитесь, что `lock_timeout` и `statement_timeout` установлены.
- Найдите блокирующий процесс: `pg_stat_activity` (PostgreSQL) или `information_schema.innodb_trx` (MySQL).
- Завершите блокирующий backend: `SELECT pg_terminate_backend(pid);` (PostgreSQL) или `KILL query thread_id;` (MySQL).

### Нестабильность results между запусками

**Симптом:** При одинаковых параметрах результаты миграций отличаются или возникают race conditions.

**Причины:**
- Не фиксирована частота CPU (Turbo Boost / throttle).
- Не изолированы миграции от фоновых задач (autovacuum, репликация).
- Данные не выровнены по pages (фрагментация).

**Решение:**
- Фиксируйте `scaling_governor = performance`.
- Запускайте миграции в окно минимальной нагрузки.
- Используйте `pg_prewarm` или аналоги для прогрева кэша перед длительными DDL.

## Best Practices

1.  **Никогда не коммитьте пароли:** Храните `flyway.conf` с секретами в `.gitignore`. Используйте vault, CI/CD variables или Kubernetes Secrets.
2.  **Одна миграция — одно изменение:** Не объединяйте несколько несвязанных DDL/DML в один файл. Это упрощает откат и аудит.
3.  **Используйте таймстампы в именовании:** `V20240817120000__add_email_to_users.sql` вместо `V1`, `V2`. Исключает коллизии при параллельной разработке.
4.  **Тестируйте на эфемерной БД:** Перед мерджем запускайте миграции на временной базе в Docker/Testcontainers.
5.  **Запретите `clean` в Production:** `flyway.cleanDisabled=true` на всех окружениях кроме локального.
6.  **Валидируйте в CI:** `flyway validate` должен быть обязательным шагом перед `migrate`.
7.  **Используйте Fix-Forward:** Вместо отката создавайте компенсирующие миграции. Это сохраняет историю и безопаснее.
8.  **Минимизируйте права БД:** Flyway-пользователь должен иметь только необходимые привилегии (`CREATE` на схему, DML на таблицы), но не `SUPERUSER`.
9.  **Изолируйте окружение:** Запускайте Flyway на отдельном сервере или в изолированном Kubernetes Job с лимитами ресурсов.
10. **Резервное копирование:** Всегда создавайте снапшот или дамп перед миграцией в Production.
11. **Используйте Repeatable Migration для Views/Functions:** `R__views.sql` автоматически пересоздается при изменении, обеспечивая идемпотентность хранимых объектов.
12. **Мониторьте репликацию:** Длительные миграции данных могут вызвать лаг репликации. Настройте алерты на `pg_replication_lag_seconds` или `Seconds_Behind_Master`.
13. **Не изменяйте примененные миграции:** Если миграция `V3` ужеApplied в Production — создайте `V4` с исправлением. Изменение `V3` требует `repair` и несет риск дрейфа.
14. **Используйте callbacks для аудита:** `beforeMigrate.sql` / `afterMigrate.sql` или Java-callbacks для логирования в аудит-таблицу.

## Дополнительная информация

### См. также

- **[Database CI/CD](../database-ci-cd.md)** — интеграция Flyway в пайплайны, drift detection, GitOps.
- **[Стратегии отката (Rollback)](../rollback_strategies.md)** — Fix-Forward, Undo, точки восстановления PostgreSQL, PITR.
- **[Мониторинг миграций](../monitoring.md)** — SRE Golden Signals, `pg_stat_activity`, алерты репликации.
- **[Лучшие практики миграций](../migration_practices.md)** — именование, идемпотентность, lock timeout, DDL/DML separation.
- **[Обратно-совместимые миграции (Expand-Contract)](../expand_contract.md)** — паттерн Zero-downtime, Dual Write, триггеры синхронизации.
- **[Типовые сценарии миграций](../scenarios.md)** — пакетная обработка данных, Online Schema Change.
- **[Миграции баз данных: Основы](../migration_basics.md)** — парадигмы императивный/декларативный, transactional DDL.
- **[Liquibase: Практическое руководство](./liquibase_practical_guide.md)** — альтернативный инструмент с поддержкой YAML/XML.
