# Liquibase: Практическое руководство по эксплуатации

**Актуально для:** Liquibase 4.x

## Определения

*   **Changelog (Журнал изменений):** Корневой файл (XML, YAML, JSON или SQL), содержащий список всех изменений БД.
*   **Changeset (Набор изменений):** Атомарная единица изменений, идентифицируемая парой `id` и `author`.
*   **DatabaseChangeLog (Таблица истории):** Системная таблица `DATABASECHANGELOG`, где хранится история примененных ченджсетов.
*   **Contexts (Контексты):** Механизм фильтрации миграций по окружениям (например, `test`, `prod`).
*   **Labels (Метки):** Дополнительный механизм фильтрации, работающий вместе с контекстами. Позволяет группировать миграции по функциональности (`feature-x`, `hotfix`).
*   **Preconditions (Предусловия):** Условия, которые должны быть истинны перед выполнением ченджсета. При неудаче Liquibase может пропустить ченджсет (`onFail: MARK_RAN`) или прервать выполнение (`onFail: HALT`).
*   **Rollback (Откат):** Процесс отмены изменений, описанный внутри ченджсета или вычисляемый автоматически для стандартных команд.
*   **Snapshot (Слепок):** Текущее состояние схемы БД, которое Liquibase может сохранить и сравнить с другим слепком для обнаружения дрейфа.
*   **Diff (Сравнение):** Команда, сравнивающая два snapshot'а и генерирующая changelog с различиями.
*   **Edition (Редакция):** Существует три редакции Liquibase: Community (бесплатная), Enterprise (коммерческая), Pro (коммерческая). Enterprise добавляет поддержку SQL*Plus, Kerberos, расширенные security policy, а Pro — GUI и расширенные отчёты.

---

## Архитектура и принцип работы

Liquibase работает как stateful-инструмент: он хранит историю применённых изменений в таблице `DATABASECHANGELOG` и использует её для определения, какие ченджсеты нужно применить.

### Основной цикл выполнения

1.  **Инициализация:** Проверка подключения к БД и существования таблицы `DATABASECHANGELOG`. Если таблица отсутствует — создаётся.
2.  **Сканирование changelog:** Чтение корневого changelog-файла и всех подключённых через `<include>` или `includeAll`.
3.  **Определение состояния:** Сравнение списка ченджсетов из файлов с записями в `DATABASECHANGELOG`.
4.  **Фильтрация:** Учёт `contexts`, `labels`, `preconditions` и флагов (`runOnChange`, `runAlways`).
5.  **Валидация:** Проверка контрольных сумм (`checksum`) для уже применённых ченджсетов. При расхождении — ошибка `ValidationFailed`.
6.  **Применение:** Выполнение ченджсетов, не найденных в таблице истории. Liquibase по умолчанию удерживает блокировку на уровне таблицы `DATABASECHANGELOG` для предотвращения параллельных запусков (singleton pattern).
7.  **Запись:** Вставка записей в `DATABASECHANGELOG` (и `DATABASECHANGELOGLOCK` для блокировки).
8.  **Rollback-логирование:** При наличии `rollback`-блока — сохранение информации для возможного отката.

### Структура таблиц истории

#### `DATABASECHANGELOG`

| Колонка | Тип | Назначение |
| :--- | :--- | :--- |
| `ID` | `VARCHAR` | Идентификатор ченджсета |
| `AUTHOR` | `VARCHAR` | Автор ченджсета |
| `FILENAME` | `VARCHAR` | Путь к changelog-файлу |
| `DATEEXECUTED` | `TIMESTAMP` | Время применения |
| `ORDEREXECUTED` | `INT` | Порядковый номер применения |
| `EXECTYPE` | `VARCHAR` | Тип выполнения (`EXECUTE`, `MARK_RAN`, `FAILED`) |
| `MD5SUM` | `VARCHAR` | Контрольная сумма ченджсета |
| `DESCRIPTION` | `VARCHAR` | Тип изменений (например, `addColumn`) |
| `COMMENTS` | `VARCHAR` | Комментарии к ченджсету |
| `TAG` | `VARCHAR` | Тег, на который была откачена БД (если применимо) |
| `LIQUIBASE` | `VARCHAR` | Версия Liquibase, применившая ченджсет |

#### `DATABASECHANGELOGLOCK`

Liquibase использует эту таблицу для реализации distributed lock. При старте Liquibase пытается захватить запись (`LOCKED = 1`). Если запись уже захвачена другим процессом — Liquibase ожидает освобождения или завершается с ошибкой.

| Колонка | Тип | Назначение |
| :--- | :--- | :--- |
| `ID` | `INT` | Первичный ключ (обычно `1`) |
| `LOCKED` | `BOOLEAN` | Флаг блокировки |
| `LOCKGRANTED` | `TIMESTAMP` | Время захвата блокировки |
| `LOCKEDBY` | `VARCHAR` | Имя хоста/IP процесса, держащего блокировку |

### Поддерживаемые СУБД

Liquibase поддерживает более 20 СУБД, включая PostgreSQL, MySQL/MariaDB, Oracle, SQL Server, DB2, H2, SQLite, CockroachDB, Cassandra и другие. Поддержка специфичных функций (например, SQL*Plus для Oracle) доступна только в Enterprise-редакции.

---

## Установка и настройка

### 1. CLI (универсальный)

Скачайте дистрибутив с официального сайта и распакуйте в `/opt/liquibase`.

```bash
# Проверка установки
liquibase --version
# → Liquibase Version: 4.24.0
```

### 2. Docker (изолированный запуск)

```bash
docker run --rm \
  -v $(pwd)/changelog:/liquibase/changelog \
  liquibase/liquibase:4.24.0 \
  --changelog-file=db.changelog-master.yaml \
  --url="jdbc:postgresql://db:5432/mydb" \
  --username=liquibase_user \
  --password="${DB_PASSWORD}" \
  update
```

### 3. Maven

```xml
<plugin>
    <groupId>org.liquibase</groupId>
    <artifactId>liquibase-maven-plugin</artifactId>
    <version>4.24.0</version>
    <configuration>
        <changeLogFile>src/main/resources/db/changelog/db.changelog-master.yaml</changeLogFile>
        <url>jdbc:postgresql://localhost:5432/mydb</url>
        <username>${db.user}</username>
        <password>${db.password}</password>
    </configuration>
</plugin>
```

### 4. Gradle

```groovy
plugins {
    id 'org.liquibase.gradle' version '2.2.0'
}

liquibase {
    activities {
        main {
            changeLogFile 'src/main/resources/db/changelog/db.changelog-master.yaml'
            url 'jdbc:postgresql://localhost:5432/mydb'
            username 'liquibase_user'
            password System.getenv('DB_PASSWORD')
        }
    }
}
```

### 5. Spring Boot

Добавьте зависимость `liquibase-core` и поместите changelog в `classpath:db/changelog/db.changelog-master.yaml`. Liquibase выполнится автоматически при старте приложения.

См. также: [Database CI/CD](../database-ci-cd.md) — интеграция в пайплайны, [Flyway: Практическое руководство](./flyway_practical_guide.md) — альтернативный инструмент.

---

## Конфигурация

### 1. `liquibase.properties` (CLI/Docker)

```properties
changeLogFile=db/changelog/db.changelog-master.yaml
url=jdbc:postgresql://localhost:5432/mydb
username=liquibase_user
password=${DB_PASSWORD}
driver=org.postgresql.Driver
classpath=drivers/postgresql-42.6.0.jar

# Схемы
defaultSchemaName=public
schemas=public
liquibaseSchemaName=liquibase
liquibaseTablespaceName=pg_default

# Безопасность
promptForNonLocalDatabase=false

# Производительность
lockRetryCount=50
lockRetryDelay=1000ms
databaseChangeLogLockTableName=DATABASECHANGELOGLOCK
databaseChangeLogTableName=DATABASECHANGELOG
```

### 2. Переменные окружения (Docker/CI)

```bash
LIQUIBASE_URL=jdbc:postgresql://db:5432/mydb
LIQUIBASE_USERNAME=liquibase_user
LIQUIBASE_PASSWORD=${DB_PASSWORD}
LIQUIBASE_CHANGELOG_FILE=db/changelog/db.changelog-master.yaml
LIQUIBASE_CONTEXTS=test
LIQUIBASE_LABELS=hotfix
LIQUIBASE_DEFAULT_SCHEMA_NAME=public
LIQUIBASE_DATABASECHANGELOG_TABLE_NAME=DATABASECHANGELOG
```

### 3. Placeholder-ы

Liquibase позволяет использовать `${placeholder}` внутри changelog-файлов.

```yaml
databaseChangeLog:
  - changeSet:
      id: create-table-${table.name}
      author: devops
      changes:
        - createTable:
            tableName: ${table.name}
            columns:
              - column:
                  name: id
                  type: uuid
                  defaultValueComputed: gen_random_uuid()
```

Запуск:
```bash
liquibase \
  --changeLogFile=db.changelog-master.yaml \
  --url="jdbc:postgresql://localhost:5432/mydb" \
  --username=liquibase_user \
  --password="${DB_PASSWORD}" \
  update \
  -Dtable.name=orders
```

### 4. Contexts и Labels

Contexts используются для фильтрации миграций по окружению. Labels — для фильтрации по функциональности.

```yaml
databaseChangeLog:
  - changeSet:
      id: 1
      author: devops
      context: test
      labels: seed-data
      changes:
        - loadData:
            tableName: users
            file: seed/users.csv
```

Запуск только для `prod` контекста:
```bash
liquibase \
  --changeLogFile=db.changelog-master.yaml \
  --url="jdbc:postgresql://prod:5432/mydb" \
  --contexts=prod \
  update
```

### 5. Include и IncludeAll

Для разделения миграций по модулям используйте `<include>` или `<includeAll>`.

```yaml
databaseChangeLog:
  - include:
      file: db/changelog/users/user-changelog.yaml
  - include:
      file: db/changelog/orders/order-changelog.yaml
  - includeAll:
      path: db/changelog/audit/
      relativeToChangelogFile: true
      errorIfMissingOrEmpty: true
```

`includeAll` подключает все файлы из указанной директории. Убедитесь, что файлы отсортированы лексикографически, чтобы порядок применения был предсказуем.

---

## Форматы changelog

Liquibase поддерживает четыре формата. Выбор формата зависит от команды и предпочтений команды.

### 1. YAML (рекомендуется)

```yaml
databaseChangeLog:
  - changeSet:
      id: 1
      author: devops_engineer
      changes:
        - addColumn:
            tableName: users
            columns:
              - column:
                  name: middle_name
                  type: varchar(50)
                  constraints:
                    nullable: true
        rollback:
          - dropColumn:
              tableName: users
              columnName: middle_name
```

### 2. XML

```xml
<databaseChangeLog
    xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog
        http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-4.24.xsd">
    <changeSet id="1" author="devops">
        <addColumn tableName="users">
            <column name="middle_name" type="varchar(50)"/>
        </addColumn>
        <rollback>
            <dropColumn tableName="users" columnName="middle_name"/>
        </rollback>
    </changeSet>
</databaseChangeLog>
```

### 3. JSON

```json
{
  "databaseChangeLog": [
    {
      "changeSet": {
        "id": "1",
        "author": "devops",
        "changes": [
          {
            "addColumn": {
              "tableName": "users",
              "columns": [
                {
                  "column": {
                    "name": "middle_name",
                    "type": "varchar(50)"
                  }
                }
              ]
            }
          }
        ],
        "rollback": [
          {
            "dropColumn": {
              "tableName": "users",
              "columnName": "middle_name"
            }
          }
        ]
      }
    }
  ]
}
```

### 4. SQL (формат Liquibase)

```sql
--liquibase formatted sql
--changeset devops:1
ALTER TABLE users ADD COLUMN middle_name varchar(50);
--rollback
ALTER TABLE users DROP COLUMN middle_name;
```

---

## Основные команды

| Команда | Описание | Пример использования |
| :--- | :--- | :--- |
| `update` | Применяет все не применённые ченджсеты | `liquibase update` |
| `updateSQL` | Генерирует SQL-отчёт без применения | `liquibase updateSQL > migration.sql` |
| `rollback` | Откатывает к предыдущему тегу (`tag`) | `liquibase rollback --tag release-1.0` |
| `rollbackCount` | Откатывает последние N ченджсетов | `liquibase rollback-count 3` |
| `rollbackSQL` | Генерирует SQL-отчёт отката | `liquibase rollbackSQL --count 2 > rollback.sql` |
| `rollbackToDate` | Откатывает к указанной дате | `liquibase rollback-to-date "2024-08-17T10:00:00"` |
| `future-rollback-sql` | Генерирует откат для будущих миграций | `liquibase future-rollback-sql` |
| `status` | Показывает статус ченджсетов | `liquibase status` |
| `validate` | Проверяет целостность changelog | `liquibase validate` |
| `info` | Информация о состоянии БД и changelog | `liquibase info` |
| `diff` | Сравнивает две БД (source/target) | `liquibase diff --referenceUrl=...` |
| `snapshot` | Сохраняет текущее состояние схемы | `liquibase snapshot` |
| `tag` | Создаёт тег на текущем состоянии | `liquibase tag --tag release-2.1` |
| `clearCheckSums` | Сбрасывает контрольные суммы в `DATABASECHANGELOG` | `liquibase clearCheckSums` |

---

## Подготовка окружения и изоляция

### Требования к инфраструктуре

**Характеристики хоста:**
- **CPU:** Минимум 2 vCPU для CLI/Docker-запусков. Для длительных DML-миграций (batch update) выделите отдельный хост или укажите `nice -n 10`, чтобы не конкурировать с приложением.
- **Память:** Минимум 2 GiB RAM. Liquibase загружает метаданные и snapshot'ы в память; для больших БД (>500 таблиц) может потребоваться 4–8 GiB.
- **Диск:** Docker-образ `liquibase/liquibase:4.24.0` занимает ~300 MB. Драйверы JDBC дополнительно ~50 MB.
- **Сеть:** Низкая задержка (<5 ms) между хостом с Liquibase и целевой БД. Используйте внутреннюю сеть (Docker bridge, VLAN), а не публичный интерфейс.

### Фиксация поведения планировщика

Установите `scaling_governor` в режим `performance` на macOS/Linux, чтобы миграция не замедлялась из-за изменения частоты CPU:

```bash
# macOS
sudo pmset -a powernap 0 disksleep 0 networkoversleep 0 sleep 0 hibernatemode 0
sudo pmset -a gpuswitch 0
sudo pmset -a cpumonitoring 1

# Linux
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
ulimit -n 65536
```

### Резервное копирование перед миграцией

Всегда создавайте снапшот или точку восстановления перед применением миграций на production. См. также: [Резервное копирование](../../../Concepts/backups.md).

---

## Производственная эксплуатация

### Минимальные привилегии пользователя БД

Liquibase должен работать от отдельного пользователя с минимально необходимыми правами. **Никогда** не используйте `SUPERUSER` или `sysadmin`.

**PostgreSQL:**
```sql
CREATE ROLE liquibase_user WITH LOGIN PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE mydb TO liquibase_user;
GRANT USAGE ON SCHEMA public TO liquibase_user;
GRANT CREATE ON SCHEMA public TO liquibase_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO liquibase_user;
GRANT SELECT, USAGE ON ALL SEQUENCES IN SCHEMA public TO liquibase_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO liquibase_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, USAGE ON SEQUENCES TO liquibase_user;
```

**MySQL:**
```sql
CREATE USER 'liquibase_user'@'%' IDENTIFIED BY 'secure_password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP ON mydb.* TO 'liquibase_user'@'%';
FLUSH PRIVILEGES;
```

### Управление секретами

Никогда не храните пароли в changelog-файлах или `liquibase.properties` в Git. Используйте один из следующих методов:

- **Vault / SOPS:** Шифрование `liquibase.properties` и дешифрование в CI/CD перед запуском.
- **Kubernetes Secrets:** Монтирование как файл в под или переменные окружения.
- **Docker Secrets:** Монтирование в контейнер через `/run/secrets/`.
- **CI/CD Variables:** Использование защищённых переменных окружения (GitLab CI `protected variables`, GitHub Actions `secrets`).

### Таймауты блокировок и сессий

Настройте таймауты на уровне СУБД, чтобы "зависшая" миграция не блокировала всю БД.

**PostgreSQL (`postgresql.conf` или ALTER ROLE):**
```conf
# Таймаут ожидания блокировки таблицы
lock_timeout = 30s

# Таймаут на выполнение одного оператора
statement_timeout = 10min

# Таймаут на idle в транзакции
idle_in_transaction_session_timeout = 5min
```

**MySQL (`my.cnf`):**
```ini
[mysqld]
innodb_lock_wait_timeout = 30
max_execution_time = 600000
```

### Запуск миграций

#### Kubernetes Job (Docker)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: liquibase-migrate
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: liquibase
          image: liquibase/liquibase:4.24.0
          command:
            - /liquibase/liquibase
            - --changeLogFile=db/changelog/db.changelog-master.yaml
            - --url=jdbc:postgresql://postgres:5432/mydb
            - --username=liquibase_user
            - --password=$(DB_PASSWORD)
            - update
          env:
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: liquibase-secret
                  key: db-password
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2"
              memory: "4Gi"
```

#### systemd-сервис (для на-prem БД)

```ini
[Unit]
Description=Liquibase Database Migration
After=network.target postgresql.service

[Service]
Type=oneshot
User=liquibase
WorkingDirectory=/opt/liquibase
EnvironmentFile=/etc/liquibase/liquibase-prod.env
ExecStart=/usr/local/bin/liquibase --changeLogFile=db.changelog-master.yaml update
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
-- changelog-master.yaml
databaseChangeLog:
  - changeSet:
      id: 2
      author: devops
      changes:
        - addColumn:
            tableName: users
            columns:
              - column:
                  name: email
                  type: varchar(255)
```

При ошибке создаётся новый ченджсет `3`, исправляющий схему.

**Плюс:** Сохраняется иммутабельность истории, нет риска расхождения состояний между БД в кластере.

### Rollback с тегом (Tag Rollback)

SRE паттерн: тегирование состояния БД перед каждым релизом.

1. В начале пайплайна: `liquibase tag --tag release-2.1`.
2. Если деплой провален: `liquibase rollback --tag release-2.1`.

### Rollback Count

`liquibase rollback-count 3` — отменяет последние 3 применённых ченджсета. Используйте с осторожностью, так как это может привести к потере данных, добавленных в промежутке.

### Восстановление после Checksum Mismatch

Если файл миграции был изменен после применения:

1. **Dev/Test:** Выполните `liquibase clearCheckSums`. Это обновит контрольные суммы в таблице истории.
2. **Production:** **НИКОГДА** не делайте `clearCheckSums` автоматически. Исправьте файл в Git так, чтобы он соответствовал тому, что было применено, или создайте новую миграцию.

См. также: [Стратегии отката (Rollback)](../rollback_strategies.md), [Database CI/CD](../database-ci-cd.md).

---

## Мониторинг

### Выходные коды Liquibase

| Код | Описание | Действие |
| :--- | :--- | :--- |
| `0` | Успех | Продолжайте деплой |
| `1` | Ошибка миграции (Validation Failed, SQL error) | Остановка пайплайна, расследование |
| `2` | Ошибка параметров | Проверьте конфигурацию |
| `3` | Ошибка подключения | Проверьте сеть, credentials, доступность БД |

### Логирование

Включите детальное логирование для расследования ошибок:

```bash
liquibase \
  --changeLogFile=db.changelog-master.yaml \
  --url="jdbc:postgresql://localhost:5432/mydb" \
  --logLevel=debug \
  update
# → 11:45:23.123 [main] DEBUG liquibase.executor - Executing UPDATE users SET middle_name = 'test' WHERE id = 1
```

### Проверка состояния после миграции

```sql
-- PostgreSQL: проверка последних применённых миграций
SELECT id, author, dateexecuted, exectype, md5sum
FROM DATABASECHANGELOG
ORDER BY dateexecuted DESC
LIMIT 10;

-- Проверка блокировки
SELECT * FROM DATABASECHANGELOGLOCK;
```

### Интеграция с Prometheus/Grafana

Liquibase не предоставляет нативных метрик Prometheus. Используйте один из подходов:

1. **Sidecar exporter:** Запустите `liquibase status` через cron и экспортируйте результат в текстовый файл для `node_exporter` или `textfile_collector`.
2. **CI/CD метрики:** Считайте метрики успешности/длительности миграций на уровне пайплайна и отправляйте в Prometheus через pushgateway или `loki` + `promtail`.

### Распределённый трейсинг

Liquibase поддерживает `application_name` для PostgreSQL:

```bash
liquibase \
  --url="jdbc:postgresql://db:5432/mydb?ApplicationName=liquibase-migrate-prod" \
  update
```

Это позволяет коррелировать логи Liquibase с `pg_stat_activity` в PostgreSQL.

См. также: [Мониторинг миграций](../monitoring.md) — SRE Golden Signals, `pg_stat_activity`, блокировки.

---

## Поиск и устранение неисправностей

### Validate Failed (Checksum mismatch)

**Симптомы:** `Validation Failed` при запуске `update`. Контрольная сумма applied-миграции не совпадает с файлом на диске.

**Причины:**
- Изменён файл ченджсета после применения на этом окружении.
- Разные окончания строк (LF vs CRLF) при переносе файла между Windows и Linux.
- Конфигурация `liquibase.diff` изменила computed-колонки.

**Решение:**
1. **Dev/Test:** `liquibase clearCheckSums` обновляет контрольные суммы в `DATABASECHANGELOG`.
2. **Production:** Никогда не делайте `clearCheckSums` автоматически. Исправьте файл в Git так, чтобы он соответствовал тому, что было применено, или создайте новую компенсирующую миграцию (Fix-Forward).

### Migration failed (частичное применение)

**Симптомы:** Миграция прервалась на середине, часть ченджсетов применена, часть нет.

**Решение:**
1. Проверьте статус: `liquibase status` покажет, какие ченджсеты находятся в состоянии `FAILED`.
2. Исправьте ошибку в ченджсете.
3. Примените `liquibase clearCheckSums` для failed-ченджсетов (если ошибка была в computed-полях или в конфигурации).
4. Повторно запустите `liquibase update`. Liquibase продолжит с первого неудавшегося ченджсета.

> **Важно:** Liquibase не поддерживает автоматический откат частично применённого ченджсета внутри одной транзакции (зависит от СУБД). Для MySQL, где DDL вызывает implicit commit, частичное применение ченджсета с несколькими операциями может привести к несогласованному состоянию.

### Lock timeout / DATABASECHANGELOGLOCK удерживается

**Симптомы:** `Waiting for changelog lock` при запуске `update`.

**Решение:**
1. Проверьте, не выполняется ли другой экземпляр Liquibase:
   ```sql
   SELECT * FROM DATABASECHANGELOGLOCK;
   ```
2. Если блокировка удерживается мертвым процессом (хост не доступен), освободите вручную:
   ```sql
   UPDATE DATABASECHANGELOGLOCK SET LOCKED = FALSE, LOCKEDBY = NULL, LOCKGRANTED = NULL WHERE ID = 1;
   ```
3. Увеличьте `lockRetryCount` и `lockRetryDelay` в `liquibase.properties` для устойчивости к кратковременным блокировкам.

### Clean on Production

**Симптомы:** `liquibase clearCheckSums` или `dropAll` случайно запущены на production.

**Решение:**
1. **Остановите все пайплайны**, которые могут запускать Liquibase.
2. Восстановите `DATABASECHANGELOG` из бэкапа.
3. Восстановите саму схему/данные из бэкапа.
4. Проверьте целостность `DATABASECHANGELOG` и восстановите `DATABASECHANGELOGLOCK`.
5. Обновите процедуры запуска, добавив защиту от `clearCheckSums` и `dropAll` на production окружениях.

---

## Best Practices

1.  **Используйте таймстампы в `id`:** `id: 20240817120000-add-email` вместо `id: 1`, `id: 2`. Исключает коллизии при параллельной разработке.
2.  **Один changeset — одно изменение:** Не объединяйте несколько несвязанных DDL/DML в один файл. Это упрощает откат и аудит.
3.  **Всегда указывайте `rollback`:** Даже для стандартных операций (`addColumn`, `createTable`) явно описывайте откат. Это делает changelog самодостаточным.
4.  **Тестируйте на эфемерной БД:** Перед мерджем запускайте миграции на временной базе в Docker/Testcontainers.
5.  **Запретите `dropAll` и `clearCheckSums` на Prod:** Добавьте проверку в пайплайн: `liquibase status --contexts=prod | grep -q dropAll && exit 1`.
6.  **Валидация в CI:** Всегда запускайте `liquibase validate` в пайплайне перед `update`.
7.  **Fix-Forward вместо отката:** Используйте новые ченджсеты для исправления ошибок, а не `rollback`.
8.  **Минимизируйте права БД:** Liquibase-пользователь должен иметь только необходимые привилегии, но не `SUPERUSER`.
9.  **Используйте `includeAll` для модульности:** Разделяйте миграции по доменам (users, orders, audit) и подключайте через `includeAll`.
10. **Изоляция окружений:** Используйте отдельные `liquibase.properties` или переменные окружения для dev/staging/prod. Никогда не запускайте prod-миграцию из dev-окружения.
11. **Делайте бэкап:** Перед каждой миграцией на production создавайте точку восстановления или снапшот. См. также: [Резервное копирование](../../../Concepts/backups.md).
12. **Мониторьте репликацию:** Длительные миграции данных вызывают лаг репликации. См. также: [Мониторинг миграций](../monitoring.md).
13. **Не изменяйте применённые миграции:** Если ченджсет `3` уже applied в Production — создайте `4` с исправлением. Изменение `3` требует `clearCheckSums` и несёт риск дрейфа.
14. **Используйте Preconditions для безопасных миграций:** Проверяйте наличие индексов, колонок и таблиц перед выполнением, чтобы сделать миграции идемпотентными.

```yaml
databaseChangeLog:
  - changeSet:
      id: 5
      author: devops
      preConditions:
        - onFail: MARK_RAN
        - not:
            indexExists:
              indexName: idx_user_email
      changes:
        - createIndex:
            indexName: idx_user_email
            tableName: users
            columns:
              - column:
                  name: email
```

---

## См. также

- **[Database CI/CD](../database-ci-cd.md)** — общие принципы автоматизации.
- **[Стратегии отката (Rollback)](../rollback_strategies.md)** — теоретическая база.
- **[Мониторинг миграций](../monitoring.md)** — SRE Golden Signals, диагностика блокировок.
- **[Лучшие практики миграций](../migration_practices.md)** — именование, идемпотентность, lock timeout, DDL/DML separation.
- **[Обратно-совместимые миграции (Expand-Contract)](../expand_contract.md)** — архитектура Zero-downtime релизов.
- **[Типовые сценарии миграций](../scenarios.md)** — готовые SQL-рецепты для сложных случаев.
- **[Основы миграций](../migration_basics.md)** — императивный/декларативный подходы.
- **[Flyway: Практическое руководство](./flyway_practical_guide.md)** — альтернативный инструмент с SQL-first подходом.
- **[Резервное копирование](../../../Concepts/backups.md)** — подготовка снапшотов перед миграцией.
- **[Бенчмаркинг СУБД](../../benchmarking.md)** — фиксация поведения планировщика и изоляции ресурсов.
